# Hermes VNext 利用开源框架补强升级实施方案

**版本日期：2026-07-10**
**适用对象：Hermes 当前工作区、Codex 后续实施、代码审查与验收**
**范围：vn.py、Qbot、FinRL/FinRL-X、OpenBB、vectorbt 与 Hermes VNext 的工程化集成**

> 状态说明：当前可访问资料包含 VNext 原始目标说明和此前的框架对比报告，但未包含 Codex 最新“工作区实施状态/测试结果”正文。因此本方案不把任何待开发能力误判为已完成，而是加入一个强制的“工作区状态校准 Gate”，让 Codex 先用代码、测试、运行结果确认每个模块处于何种成熟度，再按差量实施。

---

## 1. 最终技术决策

Hermes 不应整体迁移到任何单一开源框架，也不应把五个框架安装到同一个 Python 环境。正确方案是：

```text
Hermes 自有领域核心与安全控制平面
    ├─ A股资产权限、ETF 替代、watch-only/restricted
    ├─ 数据真实性、新鲜度、血缘和 point-in-time
    ├─ Policy Put / Breadth / Style Rotation
    ├─ Semiconductor Mainline State Machine
    ├─ Regime Router
    ├─ Portfolio Risk / False Diversification
    ├─ ML 模型治理
    ├─ Approval / Kill Switch / no_live_trade
    └─ Antifragile Review

隔离的第三方能力层
    ├─ vectorbt：快速研究、事件研究、参数扫描、Walk-Forward
    ├─ vn.py：事件、订单对象、OMS/Gateway 范式、末端机械风控
    ├─ OpenBB-inspired：Provider/Fetcher/Router 和标准数据包络
    ├─ FinRL-X-inspired：目标组合权重作为唯一策略部署契约
    └─ Qbot-inspired：控制台功能入口与产品导航，仅参考
```

### 1.1 采用级别

| 框架          | 决策                           | 生产运行位置           | 禁止事项                                          |
| ------------- | ------------------------------ | ---------------------- | ------------------------------------------------- |
| vectorbt      | **直接采用，隔离依赖**         | Research/Backtest 环境 | 不作为 A 股成交真相，不直连数据源或 Broker        |
| vn.py         | **适配采用**                   | 独立 Execution Service | 策略、UI、API 不得直接调用 `send_order`           |
| OpenBB        | **优先借鉴协议，可选 Sidecar** | 独立数据代理服务       | 不替换 Tushare，不静默 fallback，不复制进核心仓库 |
| FinRL-X       | **借鉴权重中心架构**           | Hermes 自有 Contracts  | 不把其交易执行链直接接入 Hermes                   |
| FinRL Classic | **可选研究沙箱**               | 默认关闭的 RL Sandbox  | 不访问 Broker，不进入主交易链                     |
| Qbot          | **只参考 UI/产品地图**         | 无生产依赖             | 不复用自动交易链，不引入其整套依赖                |

---

## 2. Gate 0：先校准“最新工作区状态”

Codex 的第一项工作不是安装依赖，而是生成一份可机器读取的状态矩阵：

```text
docs/vnext/current_workspace_status.md
artifacts/vnext/current_workspace_status.json
```

### 2.1 成熟度定义

```text
S0 = 不存在
S1 = 只有接口、配置或占位代码
S2 = 有实现和单元测试，但未接入主链
S3 = 已接入主链并通过集成测试
S4 = 有真实数据运行记录、持久化结果和可观测性
```

### 2.2 状态矩阵字段

```yaml
module: target_portfolio_weights
status: S0|S1|S2|S3|S4
evidence_files: []
tests: []
runtime_commands: []
latest_successful_run: null
data_dependencies: []
third_party_dependencies: []
safety_impact: low|medium|high
known_gaps: []
recommended_action: keep|refactor|replace|implement|defer
next_change_set: PR-XX
```

### 2.3 必须核验的模块

- Data recovery、gap/freshness/audit；
- Data Quality/Freshness Gate；
- Universe/Permission/ETF substitution；
- TargetPortfolioWeights；
- vectorbt adapter；
- A 股事件验证回测；
- Policy Put、Breadth、Style、Semi、Regime；
- Portfolio optimizer、false diversification；
- ML Ranker、Model Registry；
- Paper、Shadow、Approval、Telegram；
- MiniQMT ReadOnly/Probe/Live-ready；
- ExecutionGuard；
- API、UI、Antifragile Review；
- 测试、示例报告、运行记录。

### 2.4 差量原则

- S3/S4 模块：保留，增加契约适配和回归测试；
- S2 模块：优先完成集成和持久化，不重复重写；
- S1 模块：核实是否为硬编码或 mock，合格则补齐，否则替换；
- S0 模块：按本方案新增；
- 任何高风险模块不能仅凭文件存在判定为完成，必须有测试和运行证据。

---

## 3. 目标架构

```text
Tushare / AkShare / Tencent / EastMoney / Local / optional OpenBB
                              ↓
                 Hermes Provider Registry
                              ↓
             Raw Immutable Snapshot + Manifest
                              ↓
             Quality / Freshness / PIT Gate
                              ↓
          Curated Store / Existing Factor Engine
                              ↓
             Rule Scores + ML Rank Scores
                              ↓
       Universe & Account Permission Resolution
                              ↓
              Raw Target Portfolio Weights
                              ↓
 Regime + Semi State + Portfolio Risk Overlay + Cash Budget
                              ↓
             Feasible TargetPortfolioWeights
                   ↙                         ↘
        vectorbt Fast Lane             Event Truth Lane
                   ↘                         ↙
               Backtest Reconciliation
                              ↓
                       OrderDraft
                              ↓
       PreTrade Safety → Telegram Approval → ExecutionGuard
                              ↓
           Paper / Shadow / LiveDryRun / MiniQMT Gateway
                              ↓
                  Append-only Event Ledger
                              ↓
          Antifragile Review / API / UI / Reports
```

### 3.1 核心依赖方向

```text
contracts        不依赖任何量化框架
research         不依赖 live broker
portfolio        不依赖 Telegram 或 miniQMT
api/ui           不导入 Broker SDK
approval         不导入模型训练代码
execution        只接收 ApprovedOrderEnvelope
vnpy_adapter     不能接收 ResearchSignal
vectorbt_adapter 不能产生 BrokerOrder
rl_sandbox       无网络交易权限
```

---

## 4. 六个必须先稳定的核心契约

建议使用 Pydantic/JSON Schema，由 Hermes 自有，不暴露第三方类作为跨模块协议。

### 4.1 MarketDataEnvelope

```text
dataset
instrument_id
provider
requested_at
observed_at
available_at
ingested_at
as_of
quality_status: OK|MISSING|STALE|PARTIAL|BACKTEST_ONLY|WATCH_ONLY|PROVIDER_ERROR
coverage
missing_fields
warnings
raw_snapshot_id
content_hash
schema_version
lineage
```

### 4.2 ResearchSignal

```text
signal_run_id
as_of
instrument_id
factor_score
ml_score
rank
confidence
regime_applicability
semi_state_applicability
evidence_bundle_id
quality_status
```

### 4.3 TargetPortfolioWeights

```text
portfolio_run_id
account_id
as_of
universe_snapshot_id
data_snapshot_id
strategy_version
model_version
regime_state
semi_mainline_state
raw_weights
eligibility_adjusted_weights
risk_adjusted_weights
cash_weight
constraints
substitutions
evidence_bundle_id
quality_status
schema_version
```

### 4.4 OrderDraft

```text
order_draft_id
portfolio_run_id
account_snapshot_id
position_snapshot_id
instrument_id
side
quantity
order_type
limit_price
reason
risk_summary
data_snapshot_id
draft_hash
expires_at
```

### 4.5 ApprovedOrderEnvelope

```text
approval_id
order_draft_id
order_draft_hash
approved_by
approved_at
expires_at
one_time_nonce
allowed_mode
risk_snapshot_id
kill_switch_snapshot
signature
```

### 4.6 ExecutionEvent / ReviewRecord

```text
event_id
correlation_id
event_type
event_time
broker
mode
order_id
trade_id
position_delta
status
reason_code
payload_hash
previous_event_hash
```

所有 Paper、Shadow、Live Dry Run、未来 Live 必须共用上述对象；差异只能发生在 Broker Adapter 和成交来源。

---

## 5. 开源框架的具体接入方案

## 5.1 vectorbt：Research Fast Lane

### 接入位置

```text
research/backtest/vectorbt_adapter/
```

### 只允许的输入

- Hermes 不可变数据快照；
- `TargetPortfolioWeights` 或显式订单矩阵；
- Hermes 成本模型；
- Hermes 交易日历；
- 明确的执行延迟配置。

### 主要用途

- Policy Put 固定/动态阈值扫描；
- Breadth divergence 多阈值、多持有期事件研究；
- Semi 状态收益和状态转移统计；
- Style rotation 矩阵；
- 20/60/120 日相关、下行相关、回撤重叠；
- 组合权重、成本和调仓频率压力测试；
- Walk-Forward、Rolling/Expanding Split；
- ML 标签与样本外评估；
- 参数稳定区而非单点最优搜索。

### 禁止行为

- 不使用 vectorbt 自带数据下载作为生产数据真相；
- 不把 vectorbt 成交直接当作 Paper/Live 成交；
- 不在同一根 K 线上同时生成信号和以不可得价格成交；
- 不用参数热力图替代样本外验证；
- 不默认启用 Rust 引擎，先通过纯 Python/Numba 与 Rust 的 golden parity 测试。

### 输出

```text
FastBacktestRun
  run_id
  data_snapshot_id
  target_weights_hash
  parameter_set
  cost_model
  metrics
  trades
  daily_positions
  warnings
  engine_version
  dependency_lock_hash
```

---

## 5.2 vn.py：Execution Service 与 Event Truth Lane

### 接入位置

```text
execution_service/
research/backtest/event_validation/
integrations/vnpy_adapter/
```

### 推荐复用

- EventEngine 或其事件语义；
- Tick/Bar/Order/Trade/Position/Account/Contract 对象设计；
- BaseGateway 的连接、查询、下单、撤单、回调契约；
- OMS 状态管理思想；
- RiskManager 的活动订单、重复订单、单笔数量、交易频率等机械规则；
- WebTrader 的 Web/交易双进程隔离思想；
- vnpy.alpha 的 Dataset/Model/Strategy/Lab 分层和 Lasso/LightGBM/MLP 基线模板。

### 不建议直接复用

- 不把 Hermes 改写为 vn.py App；
- 不让策略直接使用 `MainEngine.send_order()`；
- 不把 vn.py GUI 作为主控制台；
- 不把 vnpy_riskmanager 当作审批系统；
- 不直接把通用 PaperAccount 当成 A 股高保真撮合真相；
- 不允许 vnpy.alpha 的自动填充掩盖源数据缺失。

### 安全调用链

```text
禁止：ResearchSignal → MainEngine.send_order
禁止：UI/API → Gateway.send_order
允许：ApprovedOrderEnvelope
      → Hermes ExecutionGuard
      → Hermes A股风险规则
      → 可选 vnpy_riskmanager 机械风控
      → MiniQMTGateway/PaperGateway
```

### Event Truth Lane 必须补足的 A 股规则

- T+1；
- 动态涨跌停；
- ST、停牌、退市整理等状态；
- 一手整数和最小交易单位；
- 除权除息与复权一致性；
- 成交优先级、部分成交、撤单；
- 开盘/收盘价格不可得性；
- 流动性容量和冲击成本；
- 创业板/科创板账户权限；
- ETF 与个股替代关系。

---

## 5.3 OpenBB：Provider 协议与可选 Sidecar

### 第一阶段：只借鉴，不引入 OpenBB 核心依赖

在 Hermes 自己实现：

```python
class DataFetcher(Protocol):
    def transform_query(self, params): ...
    async def extract_data(self, query): ...
    def transform_data(self, raw): ...
    def assess_quality(self, data): ...
```

```text
TushareFetcher
AkShareFetcher
TencentQuoteFetcher
EastMoneyFetcher
LocalCsvFetcher
MiniQMTMarketDataFetcher
OpenBBProxyFetcher（可选）
```

### 第二阶段：可选 OpenBB Sidecar

仅用于：

- 纳指、费半、海外科技代理；
- 宏观、利率、汇率、商品；
- 海外新闻或研究补充；
- watch-only / proxy_signal 数据。

### 强约束

- Tushare 缺失时不得自动切换 OpenBB 并标为成功；
- 次级 Provider 只生成 `ProviderConflictRecord` 或 `AlternativeObservation`；
- 主数据冲突必须在 Data Health 和报告中显式展示；
- OpenBB 采用 AGPL-3.0，若直接部署或修改，必须单独完成许可证审查；
- 推荐 Sidecar、独立锁文件、独立进程，不把源码复制进 Hermes 私有核心。

---

## 5.4 FinRL-X：目标权重中心架构

不把 FinRL-X 作为 Hermes 生产依赖，而是吸收以下约束：

```text
Stock Selection
  → Portfolio Allocation
  → Timing Adjustment
  → Risk Overlay
  → Target Portfolio Weights
```

任何模块只能变换权重，不得跳过契约生成订单。

### Hermes 的扩展

FinRL-X 权重后必须增加：

```text
Account Permission Resolver
ETF Substitution Resolver
A股 Tradability Gate
Order Draft Generator
PreTrade Safety
Telegram Approval
Kill Switch
ExecutionGuard
```

### FinRL Classic

只预留：

```text
research/rl_sandbox/
  enabled: false
  input: immutable snapshots
  output: candidate weights / diagnostics
  broker_access: none
```

本轮不把 RL 作为优先级。

---

## 5.5 Qbot：只借鉴产品工作流

参考：

- 数据—策略—回测—模拟—交易—通知的功能地图；
- 策略实验室和页面入口；
- 多引擎统一入口的产品体验；
- 研究、回测和交易结果的可视化组织。

不引入其运行时依赖。其官方 README 仍说明主要在 Python 3.8/3.9 测试，且仓库是多框架、Notebook 和示例的集合，和 Hermes 的强审计、强契约目标不匹配。

---

## 6. 分阶段变更集

每个变更集必须独立可回滚，并包含：代码、配置、单测、集成测试、示例输出、迁移说明、回滚说明。

## PR-00：Current State Reconciliation

交付：

- 工作区状态矩阵；
- 依赖图、CLI 清单、数据库表清单、API 清单；
- 直接 Broker 调用扫描；
- mock/fallback 数据路径扫描；
- `no_live_trade`、Kill Switch、审批链运行验证；
- 当前测试基线和失败清单。

验收：

- 每个 VNext 模块都有 S0-S4 证据；
- 不以文件名或占位类作为完成证明；
- 给出差量 PR 路径。

## PR-01：Contracts & Safety Invariants

交付：

- 六个核心契约；
- Trading Mode State Machine；
- ExecutionGuard；
- Approval hash/nonce/TTL；
- append-only event ledger schema；
- 安全性质测试。

验收：

- `no_live_trade=True` 时，任何代码路径发送真实订单均失败；
- 未审批、过期、被修改、哈希不匹配的订单均失败；
- API/UI 包不能导入 live Broker；
- Kill Switch 优先于任何 Gateway 调用。

## PR-02：Data Recovery & Immutable Snapshots

数据恢复顺序：

```bash
hermes data:gap-plan
hermes data:freshness-check
hermes data:audit

hermes data:full-init-by-date
hermes data:backfill-timeseries
hermes data:pull-fina --start <START>
hermes data:pull-remaining
hermes data:pull-concept-industry
hermes data:hub-rebuild all

hermes data:gap-plan
hermes data:freshness-check
hermes data:audit
```

必须新增：

- checkpoint/resume；
- 每批 request/response manifest；
- 原始不可变快照；
- content hash；
- 失败重试和限频退避；
- schema version；
- min/max date、行数、覆盖率；
- `available_at` point-in-time 字段；
- 审计前后对比报告；
- 数据备份和恢复演练。

验收：

- 重跑幂等；
- 不存在 silent fallback；
- 数据缺失显示 MISSING/PARTIAL；
- stale 数据不能进入正式信号；
- 财务特征按实际可得日进入样本。

## PR-03：Provider & Data Quality Layer

交付：

- OpenBB-inspired Provider Registry；
- Tushare/AkShare/Tencent/EastMoney/Local 适配器；
- DataEnvelope；
- ProviderConflictRecord；
- Data Health API；
- point-in-time curated views。

验收：

- 同一数据集的字段、时区、交易日和代码语义统一；
- 次级 Provider 不覆盖主源；
- UI 可查看来源、更新时间、覆盖率、缺失字段、血缘。

## PR-04：Target Weights & vectorbt Fast Lane

交付：

- `TargetPortfolioWeights`；
- 旧 TopN 输出到目标权重的兼容适配器；
- vectorbt 独立环境、锁文件、adapter；
- 事件研究、成本矩阵、Walk-Forward；
- 回测 run manifest。

验收：

- 同一策略在旧 TopN 与新权重适配器下候选一致；
- vectorbt 不访问 Broker；
- vectorbt 不直接下载生产数据；
- 每次结果可由数据快照和参数哈希复现。

## PR-05：A 股 Event Truth Lane & Reconciliation

交付：

- A 股事件撮合；
- 订单、成交、持仓、账户状态；
- T+1、涨跌停、停牌、ST、一手、部分成交；
- Fast Lane 与 Truth Lane 对账。

对账指标：

```text
signal_match_rate
weight_l1_error
order_intent_match_rate
fill_rate_gap
turnover_gap
cost_gap
return_gap
unexplained_divergence_count
```

验收：

- 信号和目标权重阶段无未解释差异；
- 所有成交差异均有 A 股规则、成本或撮合 reason code；
- 不允许用 vectorbt 结果绕过 Truth Lane 晋级 Paper。

## PR-06：Policy Put / Breadth / Style / Semi / Regime

交付：

- 固定箱体与动态箱体；
- Policy Support Proxy；
- Breadth Divergence；
- Style Rotation Matrix；
- Semiconductor State Machine；
- Regime Router；
- evidence/missing_evidence/confidence。

实施顺序：

1. 规则和统计基线；
2. vectorbt 事件研究和参数稳定性；
3. 状态转移回放；
4. 再考虑 ML Regime 分类器。

验收：

- 固定 3950/4050/4100 与动态阈值并行比较；
- 无足够证据时降置信度，不伪造状态；
- 状态和 Regime 只影响风险预算和权重，不直接产生 BrokerOrder。

## PR-07：Portfolio Risk & False Diversification

实施顺序：

```text
约束等权
→ 逆波动
→ 风险预算/风险平价
→ 最小方差
→ 稳健最大 Sharpe
→ 成本感知优化
```

交付：

- 20/60/120 日相关；
- downside correlation；
- drawdown overlap；
- PCA/共同 beta；
- 风险簇；
- technology/semi beta；
- marginal Sharpe；
- marginal drawdown；
- ETF substitution；
- 防守和现金预算。

验收：

- 新候选加入前后风险和 Sharpe 变化可解释；
- 假分散可识别；
- 优化器不能突破权限、主题、单票、流动性和现金约束；
- 最大 Sharpe 不得先于稳健协方差和约束基线进入主流程。

## PR-08：ML Ranker & Model Registry

接入方式：

```text
Existing Factor Store
  → Hermes FeatureView
  → 可选 vnpy.alpha-compatible Dataset Adapter
  → Ridge/ElasticNet/LightGBM Ranker
  → ModelScoreBatch
  → Target Weight Pipeline
```

交付：

- Ridge/ElasticNet 基线；
- LightGBM/XGBoost 横截面排序；
- 可选 MLP；
- Purged/Embargo 时间切分；
- 横截面按日期分组；
- 特征重要性/SHAP 或替代解释；
- 模型注册、晋级、降级和退役；
- OOS、Regime 分段和成本后评估。

验收：

- 模型只输出 score/rank/confidence；
- 模型类无 Broker 依赖；
- 训练和评分均绑定数据快照；
- 数据泄漏检查通过；
- 只有通过 OOS、成本、稳定性和多 Regime 门槛的模型可进入生产评分。

## PR-09：Paper / Shadow / Telegram / QMT Probe

服务边界：

```text
Research/API Service：无 Broker 凭据
Approval Service：审批状态、签名、TTL、回调
Execution Service：只接收 ApprovedOrderEnvelope
Ledger/Review Service：不可变事件和归因
```

交付：

- PaperBroker；
- ShadowBroker；
- LiveDryRunBroker；
- MiniQMTReadOnlyBroker；
- QMTProbeBroker；
- MiniQMTLiveBroker（存在但默认 disabled）；
- Telegram Approve/Reject/Modify/Delay；
- 订单哈希、nonce、allowlist、幂等；
- vn.py Event/OMS/Gateway 适配；
- 可选 vnpy_riskmanager 末端机械风控。

验收：

- Shadow 永不发单；
- Paper 不加载真实 Broker 凭据；
- Modify 后旧审批失效；
- Delay 后重新检查数据、价格和风险；
- `connected != permitted`、`approved != live_send_allowed`；
- QMT Probe 只读；
- MiniQMTLiveBroker 默认无法发送真实订单。

## PR-10：VNext API & UI

保持现有 React/Vite，不复用 Qbot 页面代码。

首批优先页：

1. Control Tower；
2. Data Health；
3. Regime & Policy Put；
4. Semiconductor Mainline；
5. Candidates；
6. Portfolio & Risk；
7. Paper/Shadow；
8. Approval/Execution；
9. Backtest/ML；
10. Antifragile Review。

所有 API 返回统一包络：

```json
{
  "run_id": "...",
  "as_of": "...",
  "status": "OK|MISSING|STALE|PARTIAL|BLOCKED",
  "data": {},
  "evidence": [],
  "missing_evidence": [],
  "confidence": 0.0,
  "provider": [],
  "warnings": [],
  "lineage": {}
}
```

验收：

- UI 不硬编码成功数据；
- loading/error/empty/stale 均有独立状态；
- UI 不包含直接下单入口；
- UI 进程不导入 miniQMT/vn.py Broker SDK；
- 审批动作只改变审批状态，不直接触发无守卫发送。

## PR-11：Antifragile Review & Observability

交付：

- Backtest/Paper/Shadow/LiveDryRun 统一归因；
- Regime、Semi、Policy Put、Factor、ML、Portfolio、Execution、Data 分层归因；
- KEEP/TUNE/DOWNGRADE/RETIRE/ESCALATE/WATCH；
- 数据、订单、审批和执行 correlation_id；
- 结构化指标和告警。

验收：

- 每个损益、未成交和阻断均有 reason code；
- Paper vs Backtest、Shadow vs Paper 差异可量化；
- 无法解释的差异单独计数并阻止晋级。

## PR-12：SBOM / License / Hardening / Final Acceptance

交付：

- 四套独立锁文件；
- SBOM；
- 许可证清单；
- 依赖漏洞扫描；
- secrets 扫描；
- 安全路径静态检查；
- 最终验收报告。

---

## 7. 推荐代码目录

以下路径应映射到当前项目实际 package root，不强制重写现有结构：

```text
hermes/
  contracts/
    data.py
    signal.py
    portfolio.py
    order.py
    approval.py
    execution.py
    review.py

  data/
    providers/
    ingestion/
    quality/
    lineage/
    point_in_time/
    snapshots/

  research/
    factors/
    ml/
    policy_put/
    semiconductor/
    regime/
    backtest/
      vectorbt_adapter/
      event_validation/
      reconciliation/

  portfolio/
    allocators/
    risk_overlay/
    diversification/

  execution/
    guard/
    ledger/
    brokers/
      paper/
      shadow/
      live_dry_run/
      miniqmt/
    vnpy_adapter/

  approval/
    telegram/
    policy/

  review/
    antifragile/
    attribution/

  api/vnext/
  ui/

  integrations/
    openbb_sidecar/
    finrl_sandbox/

  third_party/
    NOTICE.md
    licenses/
```

---

## 8. 环境与依赖隔离

```text
hermes-core
  自有 contracts、data quality、domain、portfolio、approval、API

hermes-research-vectorbt
  vectorbt + 科学计算依赖
  无 Broker SDK

hermes-execution-vnpy
  vn.py + 可选 riskmanager + MiniQMT SDK
  无训练依赖、无 UI 构建依赖

hermes-openbb-sidecar（可选）
  OpenBB 与海外/宏观 Provider
  只能输出 DataEnvelope
```

### 8.1 版本策略

- 先做兼容性 spike，再锁定精确版本和哈希；
- 不使用宽松的 `>=` 进入生产；
- vectorbt 的 Rust 引擎单独 feature flag；
- miniQMT 的 Python/Windows 约束优先决定 Execution Service 版本；
- Qbot、FinRL Classic 不进入生产锁文件；
- OpenBB AGPL Sidecar 与核心代码分仓或至少分包、分进程并做法务审查。

---

## 9. 关键验收闸门

## Gate A：安全不变量

- 真实下单调用路径只有一条；
- 未审批、过期、修改、哈希不匹配均被阻断；
- Kill Switch 和 `no_live_trade` 无法绕过；
- API/UI 对 live Broker 的静态依赖为零；
- 所有拒绝有审计事件。

## Gate B：数据真相

- 必需表的日期、标的和字段覆盖达到项目设定阈值；
- 所有缺口有 reason code；
- 不存在 mock/fallback 冒充 OK；
- point-in-time 审计通过；
- 数据恢复可断点续传、可重复、可校验。

## Gate C：研究一致性

- 旧 TopN 与权重适配器候选一致；
- Fast Lane 与 Truth Lane 的目标权重差异为零或完全解释；
- 所有成交差异有规则/成本原因；
- 结果可由 run manifest 重现。

## Gate D：策略稳健性

- 固定阈值与动态阈值均被验证；
- 牛、熊、震荡、流动性冲击分段；
- 手续费、滑点、冲击成本和调仓频率压力测试；
- 与同池等权、半导体 ETF、宽基和旧 TopN 比较；
- 失败样本和失效条件明确。

## Gate E：Paper/Shadow 闭环

建议最小运行样本：不少于 20 个交易日或 4 个完整调仓周期，并满足：

- 调度成功率达到项目阈值；
- 持仓、资金、订单账本可重建；
- Shadow 的真实发送次数为 0；
- 未解释的 Paper/Shadow 差异为 0；
- 所有阻断和未成交均有原因；
- Telegram 审批回调幂等。

## Gate F：Live Dry Run

- 只生成真实格式订单草案；
- 经过完整审批和执行守卫；
- 最终 Broker send 被硬阻断；
- UI 明确显示“不会真实下单”；
- 任何模式或配置组合都不能使 live send 可达。

---

## 10. 当前最应立即执行的三个变更集

### 第一：PR-00 + PR-01

先确认 Codex 最新代码到底实现了什么，并冻结安全边界。没有这一步，后续引入 vn.py 会放大直接下单面，接入 vectorbt 会放大研究与执行语义漂移。

### 第二：PR-02 + PR-03

数据已被误删，所有模型、状态机和回测都依赖恢复后的真实数据。先完成恢复、快照、manifest、freshness 和 point-in-time，再训练模型或生成正式回测。

### 第三：PR-04 + PR-05

建立 `TargetPortfolioWeights`，然后同时接入 vectorbt Fast Lane 和 A 股 Event Truth Lane。这一步打通“研究—组合—Paper—Shadow—未来执行”的统一语义，是整个升级的主干。

完成上述三组后，再并行推进领域策略、组合风险、ML 和交易闭环。

---

## 11. 交给 Codex 的直接执行要求

```text
1. 先生成 current_workspace_status.md/json，不得猜测模块完成度。
2. 保持 no_live_trade=True，保持默认 READ_ONLY/PAPER。
3. 禁止先安装全部第三方框架；按环境拆分并锁定版本。
4. 先创建 Hermes 自有 Contracts，再编写所有 Adapter。
5. vectorbt 只消费 Hermes snapshot/weights，不下载生产数据、不发单。
6. vn.py 只存在于 Execution Service/Event Validation，不进入 UI/API/策略模块。
7. OpenBB 第一阶段只借鉴 Provider/TET/Router 设计；需要海外代理时再加 Sidecar。
8. FinRL-X 只吸收 weight-centric contract；FinRL RL sandbox 默认关闭。
9. Qbot 只参考页面入口，不复制交易代码或整套前端。
10. 所有新模块都必须有 feature flag、回滚方式和安全性质测试。
11. 每个 PR 输出：代码、配置、测试、示例、运行命令、风险、未完成项。
12. 最终更新 docs/vnext/hermes_vnext_goal_report.md 和 hermes_vnext_ui.md。
```

---

## 12. 最终判断

本轮升级的关键不是“接入多少开源框架”，而是把开源框架限制在可替换的能力边界内：

- **vectorbt 提高研究速度；**
- **vn.py 提高事件、订单和 Gateway 工程成熟度；**
- **OpenBB 的 Provider 模式提高数据接口一致性；**
- **FinRL-X 的权重契约消除研究到执行的语义漂移；**
- **Qbot 提供产品入口参考。**

Hermes 自己必须掌握单一数据真相、单一领域真相和单一安全真相。只有这样，VNext 才会成为可审计、可回放、可逐步进入 Paper/Shadow/Live Dry Run 的半自动投研交易系统，而不是一个依赖复杂、结果难复现、交易权限难控制的框架拼盘。

---

## 13. 官方参考资料

- vn.py: https://github.com/vnpy/vnpy
- vn.py PaperAccount: https://github.com/vnpy/vnpy_paperaccount
- vn.py RiskManager: https://github.com/vnpy/vnpy_riskmanager
- vn.py WebTrader: https://github.com/vnpy/vnpy_webtrader
- vectorbt: https://github.com/polakowo/vectorbt
- FinRL-X: https://github.com/AI4Finance-Foundation/FinRL-Trading
- FinRL: https://github.com/AI4Finance-Foundation/FinRL
- OpenBB: https://github.com/OpenBB-finance/OpenBB
- OpenBB Provider architecture: https://docs.openbb.co/odp/python/developer/architecture_overview
- Qbot: https://github.com/UFund-Me/Qbot

---

## 14. 建议的默认配置基线

以下配置体现“第三方能力默认最小权限、真实交易默认不可达”。字段名称可按当前项目配置体系调整，但语义不得弱化。

```yaml
vnext:
  enabled: true
  schema_version: "1.0"

third_party:
  vectorbt:
    enabled: true
    mode: research_only
    allow_network_data_download: false
    allow_broker_access: false
    require_snapshot_id: true
    require_run_manifest: true

  vnpy:
    enabled: false
    mode: execution_service_only
    allow_strategy_direct_send: false
    allow_ui_direct_send: false
    allow_api_direct_send: false

  openbb:
    enabled: false
    mode: optional_proxy_sidecar
    allowed_asset_roles: [proxy_signal, watch_only]
    allow_primary_source_override: false
    allow_silent_fallback: false

  finrl:
    enabled: false
    mode: research_sandbox
    broker_access: false
    output_contract: target_weight_proposal

  qbot:
    enabled: false
    mode: reference_only

trading:
  mode: PAPER
  no_live_trade: true
  live_broker_enabled: false
  live_send_compiled: false
  approval_required: true
  approval_ttl_seconds: 300
  approval_one_time_nonce: true
  kill_switch_required: true

execution:
  accepted_input_contract: ApprovedOrderEnvelope
  reject_stale_market_data: true
  reject_missing_position_snapshot_for_sell: true
  reject_watch_only: true
  reject_restricted: true
  revalidate_before_send: true

data_quality:
  fail_visible: true
  allow_mock_in_production: false
  allow_fallback_as_primary: false
  point_in_time_required: true
  immutable_snapshot_required: true
```

---

## 15. 状态驱动的差量实施规则

Codex 在 PR-00 得到实际工作区状态后，应按下表决策，而不是机械新增重复模块。

| 实际状态                              | 差量动作                                                     |
| ------------------------------------- | ------------------------------------------------------------ |
| 现有因子/Alpha/IC/Walk-Forward 已稳定 | 保留；增加 `ResearchSignal` 和 `TargetPortfolioWeights` 输出适配器 |
| 已存在组合权重对象但字段不全          | 做 schema migration 和兼容读取；不另建第二套权重对象         |
| 已存在 vectorbt 回测                  | 审计数据来源、信号延迟、成本和输出清单；通过后纳入 Fast Lane |
| 已存在事件回测                        | 补 A 股规则和 Fast/Event 对账；不要并行维护第三套回测        |
| 已存在 QMT client                     | 以 `MiniQMTGatewayAdapter` 包装；禁止直接从策略或 API 调用   |
| Paper/Shadow 只有类和 CLI             | 优先补持久化循环、重启恢复和事件账本，而不是增加更多 Broker 类 |
| Telegram 已能发消息                   | 升级为带签名、哈希、TTL、nonce、幂等的审批状态机             |
| UI 已有页面                           | 保留 React/Vite；统一 API 包络和安全状态，不重写前端         |
| 已有数据恢复任务                      | 加 checkpoint、manifest、快照、幂等和审计；不要另起重复拉取器 |
| 某模块只有示例 JSON 或硬编码输出      | 标为 S1，不得视为完成；必须接入真实快照和集成测试            |
| 某模块已有测试但无真实运行记录        | 标为 S2；先运行并持久化，再决定是否重构                      |

---

## 16. 最终验收证据包

每个正式验收版本至少生成：

```text
artifacts/vnext/acceptance/<run_id>/
  workspace_status.json
  dependency_graph.json
  cli_inventory.json
  api_inventory.json
  database_schema_snapshot.sql
  data_gap_report.json
  data_freshness_report.json
  data_audit_report.json
  snapshot_manifest.json
  target_weights.json
  fast_backtest_manifest.json
  event_backtest_manifest.json
  reconciliation_report.json
  paper_ledger.jsonl
  shadow_ledger.jsonl
  approval_audit.jsonl
  execution_guard_report.json
  security_test_report.xml
  unit_test_report.xml
  integration_test_report.xml
  ui_build_report.txt
  license_review.md
  sbom.cdx.json
  unresolved_items.md
```

没有上述证据时，不能仅凭“代码文件已创建”宣称 VNext 模块完成。