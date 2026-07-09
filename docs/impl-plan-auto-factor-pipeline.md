# 自动因子挖掘管线 — 实现方案

基于 ADR-023 的 15 项决策，按实施优先级分三阶段。

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        cron 16:00 (每日)                         │
│                     factor:evolve 产出 (事件)                     │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  [入口] pipeline_orchestrator.py                                │
│  ① 加载因子候选（注册表 + evolved_candidates.json）               │
│  ② 去重（跳过上次验证时间 < 7天的）                               │
│  ③ 调用 factor_engine.compute_all → IC 评估                     │
│  ④ 按 IC 分级路由到队列                                          │
│     ├─ |IC|≥0.03  → task_queue/complete_validation/              │
│     ├─ 015~0.03   → task_queue/quick_backtest/                   │
│     └─ <0.015     → task_queue/skipped/ （仅记录日志）            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  [Worker 框架] pipeline_worker.py                               │
│  消费者进程（可多实例并行）                                       │
│                                                                 │
│  Worker A ── consume complete_validation queue                  │
│  │  ├── backtest:factor-top (快速回测)                           │
│  │  ├── factor:batch (WalkForward + 抗过拟合)                    │
│  │  └── check: Sharpe>1.0 && MaxDD<-20% && WF pass              │
│  │                                                                │
│  Worker B ── consume quick_backtest queue                       │
│  │  └── backtest:factor-top (快速回测)                           │
│  │                                                                │
│  All Workers Done ──→ 汇总报告 → 企微推送 → 影子观察器          │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  [影子观察器] shadow_observer.py                                │
│  注册后每天 factor:mine 增量 IC → 跟踪衰减                       │
│  日频 10 天 / 周频 1月 → 标记可用/不稳定                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、P0 实现任务（8 项，必须第一批完成）

### 任务 1：创建 pipeline_orchestrator.py

**文件**: `commands/factor_lab/pipeline_orchestrator.py`

```
class FactorPipelineOrchestrator:
    - load_candidates()     合并注册表 + 进化候选，去重
    - run_ic_evaluation()   调用 factor_engine.compute_all → IC
    - classify_by_ic()      按 |IC| 分级 → 路由
    - enqueue_tasks()       写入 task_queue JSON
    - run()                 以上全流程串联
```

关键逻辑：
- 去重：跳过 `上次验证时间 < 7天前` 的因子
- 分级：`|IC| ≥ 0.03` → `complete_validation`；`0.015~0.03` → `quick_backtest`；`<0.015` → `skipped`
- `skipped` 只写日志，不入队

### 任务 2：创建 pipeline_worker.py

**文件**: `commands/factor_lab/pipeline_worker.py`

```
class FactorPipelineWorker:
    - poll_queues()              轮询 task_queue 目录
    - consume_quick_backtest()   调用 run_top_group_backtest
    - consume_complete_validation()  快速回测 → factor:batch
    - check_approval_conditions() Sharpe>1.0 && MaxDD<-20% && WF pass
    - auto_register()            调用 alpha:register
    - generate_report()          汇总成推送文本
    - push_wechat()              企微通知
```

队列文件格式：
```json
{
  "task_id": "f_20260707_160000_001",
  "type": "complete_validation|quick_backtest",
  "factor_name": "vwap_bb_squeeze_reversal",
  "expression": "rank(ts_delta(vwap,5)) * rank(-bb_width(close,20,2))",
  "ic_mean": -0.0743,
  "ic_ir": -0.45,
  "created_at": "2026-07-07T16:00:00",
  "retry_count": 0,
  "status": "pending"
}
```

### 任务 3：创建 pipeline_config.py

**文件**: `commands/factor_lab/pipeline_config.py`

```python
class PipelineConfig:
    IC_THRESHOLD_FULL = 0.03
    IC_THRESHOLD_QUICK = 0.015
    SHARPE_MIN = 1.0
    MAX_DD_MAX = -0.20  # -20%
    RETRY_MAX = 1
    SHADOW_DAYS_DAILY = 10
    SHADOW_DAYS_WEEKLY = 30  # 交易日
    REVALIDATE_DAYS = 7  # 7天内不重复验证
    QUEUE_DIR = Path("/mnt/d/HermesReports/pipeline_queue/")
    RESULT_DIR = Path("/mnt/d/HermesReports/pipeline_results/")
```

### 任务 4：cron 配置 16:00 定时触发

用 `cronjob` 创建定时任务：

```
hermes cronjob create --schedule "0 16 * * 1-5" \
  --name "factor-auto-pipeline" \
  --prompt "运行自动因子挖掘管线" \
  --script commands/scripts/daily_factor_pipeline.py \
  --no-agent
```

**文件**: `commands/scripts/daily_factor_pipeline.py`
```python
#!/usr/bin/env python3
"""每日收盘自动因子挖掘管线入口"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "commands"))
from factor_lab.pipeline_orchestrator import FactorPipelineOrchestrator
orch = FactorPipelineOrchestrator()
result = orch.run()
# stdout 会作为 cron 的输出，用于 no_agent=True 的投递
print(result.summary_text())
```

### 任务 5：事件触发 — research:loop 和 factor:evolve 产出后自动入队

在 `research_loop/__init__.py` 的 Phase 4（Update Notes）末尾追加：

```python
# Phase 4 末尾：自动入队
if hasattr(self, "_auto_enqueue"):
    self._auto_enqueue(candidates)
```

在 `factor_evolution.py` 或 `factor:evolve` 的 CLI handler 中，写入 `evolved_candidates.json` 后调用入队。

入队函数：写入 `QUEUE_DIR / "incoming" / {factor_name}.json`

### 任务 6：企微推送模板

在 `notify.py` 中新增 `notify_pipeline_result(results: list[dict])`：

```python
def notify_pipeline_result(results: list[dict]):
    """自动因子挖掘管线结果推送"""
    passed = [r for r in results if r["status"] == "registered"]
    failed = [r for r in results if r["status"] == "failed"]
    skipped = [r for r in results if r["status"] == "skipped"]
    
    lines = ["📊 自动因子挖掘报告", f"时间: {datetime.now():%Y-%m-%d %H:%M}"]
    if passed:
        lines.append(f"\n✅ 新注册 ({len(passed)}):")
        for r in passed:
            lines.append(f"  {r['name']}: IC={r['ic']:.4f} Sharpe={r['sharpe']:.2f}")
    if failed:
        lines.append(f"\n❌ 失败 ({len(failed)}):")
        for r in failed:
            lines.append(f"  {r['name']}: {r['error']}")
    if skipped:
        lines.append(f"\n⏭️ 跳过 ({len(skipped)}): IC<0.015")
    
    from factor_lab.notify import notify_goal_done
    notify_goal_done("自动因子挖掘管线", "\n".join(lines))
```

### 任务 7：失败重试封装

创建 `commands/factor_lab/pipeline_retry.py`：

```python
def run_with_retry(fn, task_id: str, max_retries: int = 1):
    """带重试和告警的封装"""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries:
                time.sleep(5)
                continue
            # 二次失败 → 企微告警
            notify_pipeline_failure(task_id, str(e))
            return {"status": "failed", "error": str(e)}
```

### 任务 8：异步队列目录结构

```
/mnt/d/HermesReports/pipeline_queue/
├── incoming/           # 新任务（事件触发写入，cron 扫描）
├── quick_backtest/     # 快速回测任务（worker 消费）
├── complete_validation/ # 完整验证任务（worker 消费）
├── completed/          # 已完成任务（存档）
└── failed/             # 失败任务（重试用）
```

---

## 三、P1 实现任务（后期）

### 任务 9：影子观察器 shadow_observer.py

```
class ShadowObserver:
    - register_for_shadow(factor_name, holding_period)
    - daily_tick()              每天 factor:mine 后调用，追加 IC
    - check_maturity()          检查观察期是否到期
    - compute_decay_rate()      (首日IC - 末段IC均值) / |首日IC|
    - mark_available() / mark_unstable()
```

### 任务 10：Alpha Registry 注册表扩展

在 `alpha_registry.py` 中新增字段：
```python
@dataclass
class AlphaSpec:
    ...
    last_validated: Optional[str] = None   # 上次验证日期
    shadow_status: str = "pending"         # pending/observing/available/unstable
    shadow_start: Optional[str] = None
    shadow_end: Optional[str] = None
    ic_decay_rate: float = 0.0
```

### 任务 11：并行 worker 隔离

- 每个 worker 写入独立输出目录 `/mnt/d/HermesReports/pipeline_results/{task_id}/`
- 任务锁文件 `{queue_dir}/.lock_{task_id}`，获取锁后才消费
- `os.kill(pid, 0)` 检查 worker 存活

---

## 四、工作量估算

| 任务 | 文件 | 预估行数 | 依赖 |
|------|------|---------|------|
| 1. pipeline_orchestrator.py | 新文件 | ~150 | factor_engine, factor_base |
| 2. pipeline_worker.py | 新文件 | ~200 | backtest:factor-top, factor:batch, alpha:register |
| 3. pipeline_config.py | 新文件 | ~30 | 无 |
| 4. cron + entry script | 新文件 | ~20 | pipeline_orchestrator |
| 5. 事件触发接入 | 改 3 个文件 | ~40 | pipeline_orchestrator |
| 6. 企微推送模板 | 改 notify.py | ~50 | notify.py |
| 7. 失败重试封装 | 新文件 | ~40 | notify.py |
| 8. 队列目录结构 | 创建目录 | ~5 | 无 |
| 9. 影子观察器 | 新文件 | ~120 | factor:mine 增量 IC |
| 10. Alpha Registry 扩展 | 改 2 文件 | ~50 | alpha registry |
| 11. worker 隔离 | 改 pipeline_worker | ~30 | 无 |

**P0 合计**: 约 535 行（8 项任务）
**P1 合计**: 约 200 行（3 项任务）
**总计**: ~735 行

---

## 五、实施顺序

```
Phase 1 (P0):
  Task 3 (config) → Task 8 (目录) → Task 7 (重试) → Task 1 (编排器)
  → Task 2 (worker) → Task 4 (cron) → Task 6 (推送) → Task 5 (事件触发)

Phase 2 (P1):
  Task 10 (注册表扩展) → Task 9 (影子观察器) → Task 11 (worker隔离)
```

Phase 1 完成后即可上线全自动闭环，Phase 2 的观察器是增强功能。
