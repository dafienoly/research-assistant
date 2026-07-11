# Hermes VNext 开源框架集成边界

## 当前状态

Hermes 采用选择性补强，不把第三方框架对象变成公共协议。跨模块只传递 Hermes 自有 Pydantic/JSON Schema 契约；开源框架位于可禁用 Adapter 或隔离运行环境后方。

| 框架/模式 | Hermes 用法 | 当前落地 | 明确边界 |
|---|---|---|---|
| OpenBB Provider 模式 | 借鉴 Provider/Fetcher/Router、质量评估和冲突记录 | PR-03 已实现 Hermes 自有协议 | 未安装 OpenBB；不替代 Tushare；无静默 fallback |
| FinRL-X 目标权重模式 | 借鉴策略输出目标组合权重 | 核心契约已落地，主链 Adapter 待 PR-04 | 不引入训练/交易执行内部对象 |
| vectorbt | 隔离 Fast Lane | 待 PR-04 | 只读 Hermes 快照，不下载生产数据，不访问 Broker |
| vn.py 模式 | EventEngine、交易对象、Gateway/OMS 和机械风控模式 | 待 PR-05 适配 | Hermes 保留 A 股规则、审批和 ExecutionGuard |
| Qbot | UI/产品工作流参考 | 仅设计参考 | 不引入交易执行路径 |
| FinRL Classic | 默认关闭研究沙箱 | 未启用 | 不进入生产信号或下单链 |

## OpenBB-inspired Provider 层

`commands/factor_lab/vnext/providers.py` 实现：

```text
ProviderQuery
DataFetcher Protocol
FrameFetcher
ProviderRegistry
ProviderRouter
MarketDataEnvelope
DataQualityAssessment
ProviderConflictRecord
AlternativeObservation
ImmutableSnapshotStore
```

已提供数据适配器边界：Tushare、Local CSV、AkShare、腾讯、东方财富、MiniQMT 市场数据和可选 OpenBB Proxy。当前生产日报只启用 Tushare 与允许目录内的 Local CSV；其余未配置 Fetcher 返回 `PROVIDER_ERROR`，不会产生成功数据。

Router 的行为是固定的：

1. 主 Provider 始终保留为主结果；
2. 次级 Provider 只能形成 `AlternativeObservation`；
3. 两个有效源内容不同会生成 `ProviderConflictRecord`；
4. 主源失败时，次级源也不会被提升为成功主源；
5. 成功、缺失和失败包络都进入不可变快照；
6. `silent_fallback_used` 固定为 `false`。

配置位于 `configs/vnext/providers.yaml`。OpenBB Proxy 默认关闭、限制在海外代理/宏观等 Sidecar 范围，并要求单独许可证审查。

## Point-in-Time 与血缘

市场数据使用交易日或源更新时间作为 `observed_at`；财务数据使用报告期作为 `observed_at`、公告日/实际可得日作为 `available_at`。请求时间只属于采集操作元数据，不再冒充观测时间。每个包络包含 query hash、content hash、raw snapshot ID、覆盖率、缺失字段和 Provider 名称。

截至 2026-07-10 的真实聚合快照有 29 个清单，全部通过内容哈希和快照身份复算。整体 DataHub 仍有缺口与 stale 文件，因此单个快照 `OK` 不会解除系统级生产门禁。

## 安全边界

- Provider 层没有 `send_order`/`submit` 能力；MiniQMT Adapter 仅表示市场数据读取；
- OpenBB Proxy 不得作为 A 股主源；
- ResearchSignal 不能直接进入 Broker；
- 只有签名、未过期、nonce 未使用的 `ApprovedOrderEnvelope` 可进入 ExecutionGuard；
- `no_live_trade=true` 和 live broker disabled 不因 Provider、CLI 或 API 改变。

## FinRL-X 风格目标权重主链

`target_weights.py` 现在把旧 TopN/ResearchSignal 和每日多资产组合统一转换为 `TargetPortfolioWeights`。处理顺序为：原始权重 → 账户/可交易性过滤 → 受限标的 ETF 替代 → Regime/Semi overlay → 风险预算上限 → 现金权重。

当前 2026-07-10 真实目标簿：

- `portfolio_run_id=weights-2026-07-10-c105ced81f021ac9`；
- `data_snapshot_id=vnext-2026-07-10-3645917185de479e2cdc`；
- Regime 为 `RANGE_BOUND`，现金最低预算 30%；
- Semi 为 `SEMI_FAILURE`，半导体 ETF 目标权重降为 0；
- 最终投资权重 65%、现金 35%；
- 数据审计仍为 PARTIAL，因此质量为 `BACKTEST_ONLY`；
- 没有真实持仓快照，`order_drafts_generated=false`，不会生成卖单。

旧 TopN Adapter 保留原候选集合，同时 restricted/watch-only 权重必须为 0；restricted 可显式汇总到带 `substitution_of` 的 ETF 行。

## vectorbt Fast Lane

vectorbt 1.1.0 已安装在独立 `.venv_vectorbt`，完整版本冻结在 `requirements/vectorbt.lock`。核心 `.venv_quant` 不包含 vectorbt。Worker 仅允许读取聚合不可变快照与目标权重输入包，运行环境不传入 Tushare、Telegram 或 QMT 凭据，AST 边界审计禁止数据客户端和执行 SDK import。

当前真实运行：146 个交易日、7 个 ETF/代理、18 组参数、2 个 expanding walk-forward fold、3 组成本/滑点压力场景。Worker 记录 `data_download_used=false`、`external_network_used=false`、`real_broker_called=false`。第二个 OOS fold 为负收益，结果原样保留，不用挑选性指标美化。

当前 vectorbt 许可证不是纯 Apache-2.0，而是 Apache-2.0 + Commons Clause。该依赖被标为 `conditional_research_only`，未启用 Rust/full extras，商业分发前必须重新审查。官方来源：<https://pypi.org/project/vectorbt/>、<https://github.com/polakowo/vectorbt>。

## A 股 Event Truth Lane

Hermes 新增同步 EventEngine、Bar/Order/Trade/Position/Account/Contract 对象、事件 Paper Gateway、OMS 和机械风控。它复用项目已有 A 股 execution-aware 设计语义，并显式覆盖：

- T+1 可卖数量；
- 主板 10%、ST 5%、科创板 20%、创业板制度切换、北交所 30% 动态涨跌停；
- 停牌/零成交量、100 股整数手、账户板块权限；
- 成交量参与率容量、冲击成本、部分成交和日终撤单；
- 次日/当日开盘可得价格语义；
- 复权因子接口与 ETF substitution 契约。

真实事件回放消费与 Fast Lane 相同的 146 日快照和目标权重，生成 1,332 个事件、41 个订单和 41 个模拟成交，外部 Gateway 调用为 0。由于当前快照缺官方 `stk_limit`、`suspend_d`、现金分红和复权因子，Event manifest 准确标为 PARTIAL/BACKTEST_ONLY，不冒充完整成交真相。

## 双引擎对账

Fast/Event 的 `data_snapshot_id` 和 `target_weights_hash` 完全一致。当前静态目标场景对账：

- 总收益绝对差 0.000183；
- 最大回撤绝对差 0.000215；
- 期末权益差 182.60 元（初始 100 万，比例 0.000183）；
- 在预设 0.5% 容差内，reconciliation 为 OK；
- Event 仍缺官方交易真值字段，且目标簿为 BACKTEST_ONLY，因此 `promotion_status=BLOCKED`。

矩阵成交永远不是执行真值，reconciliation 通过也不能绕过 Paper、审批或 ExecutionGuard。

vn.py 本体、FinRL Classic、Qbot 源码均未装入核心环境；Event 模式由 Hermes 自有实现，后续许可证/SBOM Gate 仍需完成。
