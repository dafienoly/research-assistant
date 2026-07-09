# Hermes V3 新功能使用手册

> 基于 2026-07-08 开发会话产出

---

## 一、每日运行流程

### 1.1 盘前信号生成（晨间）

```bash
# 生成盘前信号 → 委托预览 → 风控审批
cd /home/ly/.hermes/research-assistant
PYTHONPATH=commands python3 commands/factor_lab/daily/dry_run_pipeline.py --date $(date +%Y-%m-%d)

# 输出: /mnt/d/HermesReports/dry_run/<yyyymmdd>/
# ├── dry_run_result.json
# └── dry_run_report.md
```

### 1.2 模拟交易（开盘后）

```bash
# 基于盘前信号执行模拟交易
PYTHONPATH=commands python3 -c "
from factor_lab.paper.standing_paper_trading import StandingPaperTrading
import json

engine = StandingPaperTrading()
signal = json.load(open('/mnt/d/HermesReports/premarket/20260708/premarket_signal.json'))
prices = {'688012': 158.3, '000001': 12.5}  # 实际应来自 live_snapshot.csv
result = engine.daily_process(signal, prices, '2026-07-08')
print(f'收益率: {result[\"pnl\"][\"daily_return_pct\"]}%')
print(f'持仓: {result[\"summary\"][\"holdings\"]} 只')
"

# 状态持久化到: /mnt/d/HermesData/paper_trading/
# ├── portfolio.json  (持仓和现金)
# ├── trades.jsonl    (逐笔交易)
# └── equity.csv      (净值曲线)
```

### 1.3 影子对比（盘后）

```bash
PYTHONPATH=commands python3 -c "
from factor_lab.adaptive.shadow_forward import StandingShadowForward
sf = StandingShadowForward()
result = sf.run_daily('2026-07-08')
print(f'策略收益: {result[\"shadow_return\"]:.2%}')
print(f'基准收益: {result[\"baseline_return\"]:.2%}')
perf = sf.get_rolling_performance(window=30)
alert = sf.check_alert(consecutive_loss_days=5)
"
```

### 1.4 复盘报告（收盘后）

```bash
PYTHONPATH=commands python3 -c "
from factor_lab.reports.daily_review import DailyReviewGenerator
gen = DailyReviewGenerator()
review = gen.generate()
print(f'报告: {gen.output_dir}/daily_review.html')
"
```

---

## 二、因子研究流程

### 2.1 因子验证（已有20因子结果）

```bash
# 查看因子验证排行榜
cat research_outputs/factor_validation/validation_leaderboard.csv

# 查看具体因子报告
cat research_outputs/factor_validation/ret5/report.json | python3 -m json.tool | head -30
```

### 2.2 因子正交化

```python
from factor_lab.composite.factor_combiner import (
    orthogonalize_gram_schmidt,
    compute_spearman_correlation,
    combine_factors_after_orthogonalization,
)

# 查看因子间相关性
corr = compute_spearman_correlation(df, ["ret5", "vol_ratio20", "close_gt_ma20"])
print(corr.round(3))

# 正交化（剔除共线性）
df = orthogonalize_gram_schmidt(df, ["vol_ratio20", "close_gt_ma20"], "ret5")
```

### 2.3 IC加权组合

```python
from factor_lab.composite.factor_combiner import (
    compute_ic_weights,
    compare_weighting_methods,
    apply_portfolio_constraints,
)

# 自动计算最优权重
weights = compute_ic_weights(df, ["ret5", "vol_ratio20", "close_gt_ma20"], method="ic_ir")
print(f"ICIR权重: {weights}")

# 对比4种加权方法
results = compare_weighting_methods(df, ["ret5", "vol_ratio20", "close_gt_ma20"])
for r in results:
    print(f"  {r['method']}: Sharpe={r['sharpe']}")

# 应用组合约束（行业/换手/板块过滤）
scores = pd.Series({...})  # {symbol: score}
constrained = apply_portfolio_constraints(
    scores,
    industry_map=industry,
    board_map=board,
    constraints={"max_industry": 0.30, "max_turnover": 0.30, "top_n": 10},
)
```

### 2.4 LLM因子挖掘（含失败模式参考）

```bash
# 查看历史失败记录
PYTHONPATH=commands python3 -c "
from factor_lab.alpha.failure_db import FailureDatabase
db = FailureDatabase()
print(db.get_summary())
print(db.get_recent_failures(10))
"

# LLM生成新因子（自动引用失败记录）
hermes alpha:llm-discover --context "A股半导体板块缩量调整"
# 查看候选
hermes alpha:llm-candidates
# 审批通过
hermes alpha:llm-approve --candidate-id <id>
# 审核
hermes alpha:review --candidate-id <id>
# 晋级注册
hermes alpha:promote --candidate-id <id>
```

### 2.5 LLM因子诊断

```python
from factor_lab.alpha.llm_alpha_discovery import diagnose_factor

# 对已有验证报告做LLM诊断
diagnosis = diagnose_factor("research_outputs/factor_validation/ret5/report.json")
print(diagnosis["strengths"])       # 因子优势
print(diagnosis["weaknesses"])      # 因子劣势
print(diagnosis["improvement_suggestions"])  # 改进建议
```

### 2.6 全自动研究循环

```python
from factor_lab.research_loop import AutoResearchLoop

loop = AutoResearchLoop(config={
    "max_rounds": 5,
    "candidates_per_round": 3,
})
result = loop.run(market_context="A股半导体板块，关注资金流向")
print(f"完成 {result['rounds']} 轮, 最佳评分: {result['best_score']}")
```

---

## 三、Alpha Registry 管理

```bash
# 查看已注册Alpha
hermes alpha:list

# 查看详情
hermes alpha:show --alpha-id <id>

# 从验证结果更新元数据
hermes alpha:update-from-validation \
    --alpha-id <id> \
    --validation-path research_outputs/factor_validation/ret5/report.json

# 批量更新已注册Alpha
hermes alpha:batch-update-from-validation \
    --validation-dir research_outputs/factor_validation

# 退役因子（自动写入失败归因数据库）
hermes alpha:retire --alpha-id <id> --reason "IC衰减"

# 自动检测退化因子
hermes alpha:auto-retire --dry-run
```

---

## 四、风控系统

### 4.1 启动风控守护进程

```python
from factor_lab.risk.risk_sentinel import RiskSentinel
from factor_lab.risk.kill_switch import KillSwitch
from factor_lab.risk.risk_rules import build_default_rules, RuleEvaluator

ks = KillSwitch()
sentinel = RiskSentinel(
    kill_switch=ks,
    rules=build_default_rules(),
    evaluator=RuleEvaluator(),
)
sentinel.start(interval_seconds=30)  # 每30秒检查一次
# ...
sentinel.stop()
```

### 4.2 检查风控状态

```bash
# 查看风控状态快照
PYTHONPATH=commands python3 -c "
from factor_lab.risk.kill_switch import KillSwitch
ks = KillSwitch()
print(f'状态: {ks.state}')
print(f'阻断计数: {ks.status.n_actions_blocked}')

from factor_lab.risk.risk_rules import build_default_rules
rules = build_default_rules()
print(f'风控规则总数: {len(rules)}')
for r in rules:
    print(f'  {r.name}: {r.severity} (threshold={r.threshold})')
"
```

### 4.3 单票止损/组合风控

```python
from factor_lab.risk.multi_layer_risk_manager import MultiLayerRiskManager
from factor_lab.risk.kill_switch import KillSwitch

ks = KillSwitch()
mgr = MultiLayerRiskManager(ks)

# 更新组合状态后自动检查
result = mgr.apply_rules({
    "positions": {"688012": {"weight": 0.20, "unrealized_pnl_pct": -0.09}},
    "capital": 100000,
    "daily_pnl": -0.03,
    "drawdown": 0.05,
})
if result["blocked"]:
    print(f"风控触发: {result['blocker_reasons']}")
```

### 4.4 数据异常检测

```python
from factor_lab.risk.data_anomaly_detector import DataAnomalyDetector
from factor_lab.risk.kill_switch import KillSwitch
from datetime import datetime, timedelta

ks = KillSwitch()
detector = DataAnomalyDetector(ks)

# 检查行情延迟
lag = detector.check_market_lag(datetime.now() - timedelta(seconds=120))
print(f"延迟: {lag['lag_seconds']}s, 状态: {lag['status']}")

# 检查价格异常
anomaly = detector.check_price_anomaly("000001", 15.0, 10.0, "main")
if anomaly["anomaly"]:
    print(f"价格异常: {anomaly['reason']}")

# 检查重复订单
detector.record_order_attempt("688012", "buy", True)
dup = detector.check_duplicate_order("688012", "buy")
if dup["duplicate"]:
    print(f"重复订单: {dup['reason']}")
```

### 4.5 ST/监管名单检查

```python
from factor_lab.risk.st_watchlist import STWatchlist
from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist

wl = STWatchlist()
wl.refresh()  # 更新ST名单
print(f"ST股票: {wl.is_st('000506')}")  # True
print(f"正常股: {wl.is_st('000001')}")  # False

rw = RegulatoryWatchlist()
rw.refresh()
print(f"黑名单: {rw.is_blacklisted('000506')}")
```

---

## 五、委托/审批流程

```bash
# 生成委托预览
hermes factor:order-preview --date 2026-07-08 --plan B

# 查看审批报告
cat /mnt/d/HermesReports/order_preview/20260708/order_preview_report.html

# 风控审批
hermes factor:approval --date 2026-07-08 --plan B

# 查看审批结果（含KillSwitch状态）
cat /mnt/d/HermesReports/approval/20260708/approval_summary.json
```

---

## 六、企业微信通知

系统会自动推送（需 `WECHAT_WEBHOOK_URL` 环境变量）：

| 事件 | 触发条件 | 格式 |
|------|----------|------|
| KillSwitch 触发 | 风控规则被触发 | 🛑 阻断 + 规则名 + 详情 |
| 每日风控摘要 | 检测到 blocker | 📊 风控日结 |
| 盘前信号 | 信号生成完成 | 📈 盘前信号 Top5 |

手动测试：

```python
from factor_lab.notify import notify_risk_event, notify_signal_summary

notify_risk_event("test", "风控通知测试", severity="info")
notify_signal_summary("2026-07-08", "Ret5Ma20Gate", 20, 3, ["688012", "000001"])
```

---

## 七、核心文件索引

| 功能 | 文件路径 |
|------|----------|
| 全链路干跑 | `commands/factor_lab/daily/dry_run_pipeline.py` |
| Benchmark数据 | `commands/factor_lab/portfolio/benchmark.py` |
| 因子验证 | `commands/factor_lab/validate_factor.py` |
| 正交化/组合/约束 | `commands/factor_lab/composite/factor_combiner.py` |
| IC/IR分析 | `commands/factor_lab/ic_analyzer.py` |
| 反过拟合 | `commands/factor_lab/validation/anti_overfit.py` |
| Walk-Forward | `commands/factor_lab/walk_forward.py` |
| 因子评分 | `commands/factor_lab/scoring/factor_score.py` |
| 风险规则/KillSwitch | `commands/factor_lab/risk/risk_rules.py` + `kill_switch.py` |
| 风险哨兵守护 | `commands/factor_lab/risk/risk_sentinel.py` |
| 多层止损/组合风控 | `commands/factor_lab/risk/multi_layer_risk_manager.py` |
| 数据异常检测 | `commands/factor_lab/risk/data_anomaly_detector.py` |
| ST/监管名单 | `commands/factor_lab/risk/st_watchlist.py` + `regulatory_watchlist.py` |
| 盘前风控 | `commands/factor_lab/risk/pretrade_risk_check.py` |
| 审批系统 | `commands/factor_lab/approval/risk_approval.py` |
| GateEngine | `commands/factor_lab/core/gate.py` |
| Paper Trading | `commands/factor_lab/paper/standing_paper_trading.py` |
| Shadow Forward | `commands/factor_lab/adaptive/shadow_forward.py` |
| 复盘报告 | `commands/factor_lab/reports/daily_review.py` |
| 企业微信通知 | `commands/factor_lab/notify.py` |
| Alpha Spec/Schema | `commands/factor_lab/alpha/schema.py` |
| Alpha Registry | `commands/factor_lab/alpha/registry.py` |
| 失败归因数据库 | `commands/factor_lab/alpha/failure_db.py` |
| LLM因子发现+诊断 | `commands/factor_lab/alpha/llm_alpha_discovery.py` |
| 全自动研究循环 | `commands/factor_lab/research_loop.py` |
| ETF替代 | `commands/factor_lab/etf/etf_selector.py` + `etf_universe.py` |
| 行业因子 | `commands/factor_lab/industry_relative/factors.py` |
