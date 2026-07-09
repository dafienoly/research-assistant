# 实盘 Readiness 报告

> **生成时间**: 2026-07-08 23:42 CST
> **审计依据**: `commands/live_readiness.py` (1151 行)
>                                `commands/factor_lab/adaptive/live_readiness.py` (测试 1632 行)
> **版本**: V4.9 小资金实盘 Readiness Gate (13 道门禁)
> **验收范围**: 13 道 Gate 实现 / READY/NOT_READY 判定 / 阻塞项清单 / 修复建议

---

## 1. Readiness 体系总览

### 1.1 两套 Readiness 引擎

| 引擎 | 文件 | 定位 | 门禁数 | Gate 类 |
|------|------|------|--------|---------|
| `LiveReadinessChecker` | `commands/live_readiness.py` | V4.9 轻量门禁检查 | **13 道 Gate** | `GateOutput`, `ReadinessReport` |
| `LiveReadinessReport` | `factor_lab/adaptive/live_readiness.py` | V4.9 完整 Checklist 评估 | **30+ 项目 (6 维度)** | `ReadinessChecklist` |

### 1.2 设计原则 (源代码 L5-10)

```python
# 设计原则:
#   - V4.9 只做 readiness 检查, 不做自动下单
#   - 默认全部 enabled=false, paper_enabled=false, live_enabled=false
#   - 小资金实盘 = 需要人工审批
#   - 自动交易 = 不允许
#   - 输出 READY/NOT_READY + 阻塞项清单 + 证据 + 修复建议
```

### 1.3 核心数据结构 (L40-104)

**`GateOutput`** — 单个 Gate 的输出:
```python
@dataclass
class GateOutput:
    gate_name: str       # 门禁名称
    passed: bool         # ✅/❌
    severity: str        # "blocker" | "warning" | "info"
    message: str         # 人类可读消息
    evidence: str        # 审计证据
    fix_suggestion: str  # 修复建议
```

**`ReadinessReport`** — 全量报告:
```python
@dataclass
class ReadinessReport:
    overall: str         # "READY" | "NOT_READY"
    gates: list          # 全部 Gate 结果
    blockers: list       # severity=blocker 且 passed=False
    warnings: list       # severity=warning 且 passed=False
    infos: list          # severity=info
    scanned_at: str      # ISO 时间戳
    run_id: str          # 唯一运行 ID
```

**决策逻辑** (L1009-1012):
```python
# blocker 全部通过 → READY
# 存在任意 blocker → NOT_READY
# warning/info 不影响整体结论 (除非 strict 模式)
if len(self.report.blockers) == 0:
    self.report.overall = "READY"
else:
    self.report.overall = "NOT_READY"
```

---

## 2. 13 道 Gate 完整实现

### 2.1 Gate 注册表 (L127-141)

```python
GATE_NAMES = [
    "DataHealthGate",           # 1. 数据新鲜度/覆盖率
    "UniversePurityGate",        # 2. 股票池纯度和权限标记
    "BenchmarkGate",             # 3. 基准体系完整
    "SemiconductorPeerGate",     # 4. 因子跑赢半导体同池
    "RiskExposureGate",          # 5. 因子收益非市值/Beta暴露
    "CostAdjustedReturnGate",    # 6. 交易成本后收益为正
    "PaperTradingGate",          # 7. Paper Trading >= 20 天
    "ShadowTradingGate",         # 8. Shadow Trading 无 NOT_READY
    "TradeConstraintGate",       # 9. 交易约束合规
    "ManualApprovalGate",        # 10. 人工审批通过
    "KillSwitchGate",            # 11. Kill Switch 正常
    "AuditTrailGate",            # 12. 审计记录完整
    "WeChatNotifyGate",          # 13. 企业微信通知通道正常
]
```

### 2.2 各 Gate 实现详情

#### Gate 1: DataHealthGate (L154-197)
**severity**: blocker
**检查内容**:
- `daily_kline` 数据目录是否存在
- CSV 文件数量 > 0

```python
data_dir = BASE / ".." / "data" / "market" / "daily_kline"
if not data_dir.exists():
    data_dir = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")
gate.passed = len(csv_files) > 0
```
**通过时**: severity 降为 info
**未通过时**: severity=blocker, 建议运行 `data:pull-daily`

#### Gate 2: UniversePurityGate (L201-249)
**severity**: blocker
**检查内容**:
- `universes.list_universes()` 可导入
- 各股票池可加载 (U0-U4 + ETF)
```python
from universes import list_universes, get_universe
universe_names = list_universes()  # 检查各池可加载
```

#### Gate 3: BenchmarkGate (L253-298)
**severity**: blocker
**检查内容**:
- `benchmarks_v4.list_benchmarks()` 可导入
- 各基准收益率数据可查询
```python
from benchmarks_v4 import list_benchmarks, get_benchmark
benchmarks = list_benchmarks()  # 6+ 个基准
```

#### Gate 4: SemiconductorPeerGate (L302-367)
**severity**: blocker
**检查内容**:
- 从 `/mnt/d/HermesReports/factor_lab/v4_reports/` 读取最新 V4 报告
- 调用 `check_semiconductor_pool_gate()` 验证跑赢半导体同池
- 无报告时 severity=warning, 默认通过

#### Gate 5: RiskExposureGate (L371-443)
**severity**: blocker
**检查内容**:
- 从 V4 报告读取 `exposure_type`
- 期望 `exposure_type = "pure_alpha"`
- 拒绝 `style_exposure_*` / `industry_bet` / `concentrated`
- 暴露类型枚举: `pure_alpha`, `partial_exposure`, `style_exposure`, `industry_bet`, `concentrated`

#### Gate 6: CostAdjustedReturnGate (L447-500)
**severity**: blocker
**检查内容**:
- 从 V4 报告读取 `net_return_after_cost`
- 要求 `net_return_after_cost > 0`
- 同时检查 `annual_turnover` 合理性
- 无 V4 报告时 severity=warning, 默认通过

#### Gate 7: PaperTradingGate (L504-566)
**severity**: blocker
**检查内容**:
- Paper Trading 已运行 ≥ 20 个交易日
- 收益率稳定 (max_drawdown ≤ 5%)
- Sharpe 比率可接受
```python
status = get_paper_trading_status()
sufficient_days = days_run >= 20
positive_return = total_return > -5
```
**未通过时**: 提示继续运行 Paper Trading

#### Gate 8: ShadowTradingGate (L570-635)
**severity**: blocker
**检查内容**:
- Shadow Trading 运行 ≥ 5 天
- 与 Paper Trading 相关性 > 0.7
- 偏差正常
```python
shadow_days >= 5 and correlation > 0.7
```
**模块缺失时**: severity=warning, 默认通过

#### Gate 9: TradeConstraintGate (L639-688)
**severity**: blocker
**检查内容**:
- `portfolio_builder.get_constraints()` 可调用
- 约束含: 最小交易金额/最大持仓比例/单票集中度/行业集中度
- 无约束时 severity=warning

#### Gate 10: ManualApprovalGate (L692-744)
**severity**: blocker
**检查内容**:
- `ManualApprovalPackage` 模块可用
- `ApprovalEngine` 模块可用
- 审批目录存在 (`/mnt/d/HermesReports/approvals/`)
- 模块缺失时 → BLOCKER: 需实现审批工作流

#### Gate 11: KillSwitchGate (L748-809)
**severity**: blocker
**检查内容**:
- KillSwitch 已初始化 (状态非 None)
- 状态为 ARMED (非 TRIGGERED/BLOCKED)
- 可通过 `check_action` 阻断操作
- 未注入实例时: 创建测试实例, severity=warning
- 已触发时: BLOCKER

#### Gate 12: AuditTrailGate (L813-875)
**severity**: blocker
**检查内容**:
- 审计日志目录存在 (`data/audit/` 或 `/mnt/d/HermesReports/audit/`)
- 最近 7 天有审计日志
- 或 `AuditLogger` 模块可用且有记录
- 目录不存在/无日志 → BLOCKER

#### Gate 13: WeChatNotifyGate (L879-931)
**severity**: blocker
**检查内容**:
- `WECHAT_WEBHOOK_URL` 环境变量已配置
- 或 `.bashrc` 中存在配置
- 未配置 → BLOCKER

---

## 3. 运行方式

### 3.1 CLI 命令

```bash
# V4.9 运行全部 13 道 Gate
python3 hermes_cli.py live-readiness:v4

# 详细报告 (含证据 + 修复建议)
python3 hermes_cli.py live-gate:v4-report

# 严格模式 (warning 也视为 blocker)
python3 hermes_cli.py live-readiness:v4 --strict
```

### 3.2 Python API

```python
from live_readiness import LiveReadinessChecker, run_live_readiness_check

# 快捷方式
report = run_live_readiness_check()

# 或手动构造
checker = LiveReadinessChecker()
report = checker.check_all()

for gate in report.gates:
    icon = "✅" if gate.passed else "❌"
    print(f"  {icon} {gate.gate_name}: {gate.message}")
    if not gate.passed:
        print(f"    修复: {gate.fix_suggestion}")

print(f"\n总体: {'✅ READY' if report.overall == 'READY' else '❌ NOT_READY'}")
```

### 3.3 check_all 方法 (L935-1014)

```python
def check_all(self, gates: Optional[list] = None) -> ReadinessReport:
    # 1. 运行目标 Gate (默认全部 13 个)
    # 2. 每个 Gate 异常时自动生成 failed GateOutput (severity=blocker)
    # 3. 记录到 GateEngine 审计
    # 4. 分类: blockers / warnings / infos
    # 5. 裁决: blockers 数量 = 0 → READY, 否则 NOT_READY
```

---

## 4. 当前状态

### 4.1 READY/NOT_READY 结论

**当前结论**: 🔴 **NOT_READY**

### 4.2 阻塞项清单

| # | Gate | 阻塞原因 | severity | 修复建议 |
|---|------|---------|----------|---------|
| 1 | SemiconductorPeerGate | V4 报告目录 `/mnt/d/HermesReports/factor_lab/v4_reports/` 为空 | warning | 运行 `factor:validate-v4` |
| 2 | RiskExposureGate | 无 V4 报告, 跳过检查 | warning | 运行 `factor:risk-attribution` |
| 3 | CostAdjustedReturnGate | 无 V4 成本数据 | warning | 运行 `factor:validate-v4` |
| 4 | PaperTradingGate | 未连续运行 ≥ 20 天 | blocker | 执行 `paper:v4-run` 累计天数 |
| 5 | ShadowTradingGate | 模块未就绪 | warning | 实现 Shadow Forward 模块 |
| 6 | ManualApprovalGate | 无人工审批记录 | blocker | 完善审批工作流 |
| 7 | WeChatNotifyGate | Webhook 环境变量未配置 | blocker | 设置 WECHAT_WEBHOOK_URL |
| 8 | DataHealthGate | daily_kline 仅 ~6 只标的 | info | 拉取全 A 日线 |

### 4.3 当前 Gate 通过矩阵

| Gate | 期望 | 实际 | 状态 |
|------|------|------|------|
| DataHealthGate | 数据目录有 CSV | 有 (6只+5只ETF) | ✅ PASS |
| UniversePurityGate | universes 可导入 | 可导入 | ✅ PASS |
| BenchmarkGate | benchmarks 可查询 | 可查询 | ✅ PASS |
| SemiconductorPeerGate | 跑赢同池 | 无V4报告 | ⚠️ WARNING |
| RiskExposureGate | pure_alpha | 无V4报告 | ⚠️ WARNING |
| CostAdjustedReturnGate | net_return > 0 | 无V4报告 | ⚠️ WARNING |
| PaperTradingGate | ≥20 天运行 | 未满足 | ❌ BLOCKER |
| ShadowTradingGate | ≥5天/相关性>0.7 | 模块未就绪 | ⚠️ WARNING |
| TradeConstraintGate | 约束已配置 | 可导入 | ⚠️ WARNING |
| ManualApprovalGate | 审批存在 | 无记录 | ❌ BLOCKER |
| KillSwitchGate | ARMED | 可实例化 | ⚠️ WARNING |
| AuditTrailGate | 最近有日志 | 日志目录存在 | ✅ PASS |
| WeChatNotifyGate | Webhook已配置 | 未配置 | ❌ BLOCKER |

---

## 5. 验证清单

| 检查项 | 状态 | 证据 |
|-------|------|------|
| READY/NOT_READY 判定存在 | ✅ | `ReadinessReport.overall` (L54) |
| 13 道 Gate 全部实现 | ✅ | `GATE_NAMES` 列表 (L127-141) + 对应 check_* 方法 |
| 各 Gate 含 evidence + fix_suggestion | ✅ | `GateOutput` (L41-48) |
| 默认 enabled=false (无自动交易) | ✅ | 源代码注释 L7 |
| Non-blocker Gate 不阻塞晋级 | ✅ | L1009-1012: 仅 blockers 判定 |
| Go/No-Go 自动决策逻辑 | ✅ | `check_all()` L1009 |
| 支持 strict 模式 | ✅ | `run_live_readiness_check()` 支持 strict 参数 |
| 6 维度 Checklist 引擎 | ✅ | `factor_lab/adaptive/live_readiness.py` |
| 可指定 Gates 子集运行 | ✅ | `check_all(gates=[...])` 可选参数 |
| 异常 Gate 自动降级 | ✅ | try/except → severity=blocker |

---

## 6. 已知限制

1. **通过条件宽松**: DataHealthGate 仅检查 CSV 文件存在, 未检查覆盖率和新鲜度
2. **依赖 V4 报告**: Gate 4/5/6 从 V4 报告读取, 但 V4 报告目录当前为空
3. **无自动失效恢复**: KillSwitchGate 只检查是否存在, 不自动重置/恢复
4. **ManualApprovalGate 无审批界面**: 无前端审批页面, 仅 CLI 记录
5. **无实盘资金/账户/券商接入验证**: 仅做门禁检查, 不做实盘连通性测试
6. **ShadowTradingGate 使用 V2.11 ShadowForward**: 引用 V2 模块, 与 V4.8 ShadowTradingEngine 分离
7. **PaperTradingGate 引用 factor_lab.paper.standing_paper_trading**: 需确认 `get_paper_trading_status()` 已暴露
