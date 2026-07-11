# Hermes VNext 最终工程验收报告

更新时间：2026-07-11
正式运行日：2026-07-10
验收 Run：`reconcile-2026-07-10-87e7eeb9d701bba1`

## 结论

Hermes VNext 的 PR-00～PR-12 工程链已实现并形成可重复 CLI、API、测试和证据包；当前系统已从“TopN/领域研究 + Paper/审批雏形”升级为“不可变数据快照 → 领域决策 → 目标权重 → 双回测 → 对账 → ML/组合治理 → 签名审批 → Paper/Shadow/LiveDryRun → 七层复盘 → API/UI”的受治理控制平面。

这不等于生产实盘完成。最终状态为 `PARTIAL / promotion BLOCKED / no_live_trade=true`，原因是数据审计和新鲜度未收口、Event Truth 缺官方交易状态/公司行为数据、Telegram/QMT 未配置、连续 Paper/Shadow 权益历史尚未形成，以及应用内浏览器实例不可用。系统不会用 mock、fallback 或自批准测试封套掩盖这些缺口。

## 已完成的工程主链

```text
29/29 verified provider snapshots
  → DomainDecision (RANGE_BOUND / SEMI_FAILURE)
  → TargetPortfolioWeights (65% invested / 35% cash)
  ├─ vectorbt Fast Lane
  └─ A-share Event Truth Lane
       → reconciliation within tolerance
       → portfolio optimization / XGB ranking governance
       → signed ApprovedOrderEnvelope + ExecutionGuard
       → Paper / Shadow / LiveDryRun ledgers
       → seven-layer Antifragile Review
       → stable API + 12-page React console
```

核心契约包括 `MarketDataEnvelope`、`ResearchSignal`、`TargetPortfolioWeights`、`OrderDraft`、`ApprovedOrderEnvelope`、`ExecutionEvent` 和 `ReviewRecord`。订单草案必须绑定数据、组合、账户和持仓快照；审批封套使用 HMAC-SHA256、TTL、allowed mode 和一次性 nonce；修改、过期、哈希不一致、Kill Switch、watch-only、权限/数据/风险失败均阻断。

## 真实数据与运行结果

| 项目 | 结果 | 治理结论 |
|---|---:|---|
| 聚合快照 | 29/29 manifest verified | 无 silent fallback |
| 数据 snapshot ID | `vnext-2026-07-10-3645917185de479e2cdc` | Fast/Event/Review 共用 |
| 日线/估值 | 5,738 / 5,816 文件 | 覆盖较完整 |
| 资金流/财务 | 5,401 / 5,528 个 U0 匹配 | 分别缺 129 / 2；均为上游明确空结果 |
| 概念/行业 | 409/380、511/80 | Tushare `ths_index` 与申万 2021 L1/L2/L3，覆盖门禁 OK |
| 目标权重 | 65% 投资、35% 现金 | Semi failure 将半导体 ETF 归零；BACKTEST_ONLY |
| vectorbt | 146 日、7 标的、18 参数、2 OOS folds、3 成本场景 | 第二 OOS fold -6.03%，保留负结果 |
| Event Truth | 1,332 events、41 orders、41 trades | 0 外部 Gateway；缺 limits/suspend/corporate actions |
| 双通道对账 | 收益差 0.000183、回撤差 0.000215、期末差 ¥182.60/¥1m | 在 0.5% 容差内；仍不允许晋级 |
| XGB Ranker | 208,106 时点样本、192 OOS 日；RankIC 0.02042 | 优于 Ridge -0.02040；因数据 PARTIAL 不晋级 |
| 执行认证 | Paper FILLED、Shadow RECORDED、LiveDryRun | nonce 重放全部阻断；真实 Broker 调用 false |
| Antifragile | Policy 0.463、Box 0.453、Breadth 0.482 | WATCH / BLOCKED；缺 realized labels 与连续权益曲线 |

## 开源框架落地方式

| 框架 | 实际落地 | 未做的事 |
|---|---|---|
| vectorbt 1.1.0 | 安装于独立 `.venv_vectorbt`，只读快照 Worker、参数/事件/Walk-Forward/成本压力 | 不下载数据、不接 Broker、不作为成交真相 |
| vn.py | Hermes 自有 EventEngine、Bar/Order/Trade/Position/Account/Contract、OMS、Gateway 和机械风控模式 | vn.py 包未安装；没有成熟 Gateway 重连或真实 QMT adapter |
| OpenBB | 自有 ProviderQuery/DataFetcher/Registry/Router，含 Tushare/Local/AkShare/Tencent/EastMoney/MiniQMT/OpenBBProxy 边界 | OpenBB 未安装；Proxy 默认关闭且不得替代 A 股主源 |
| FinRL-X | `TargetPortfolioWeights` 成为研究—回测—执行统一契约 | FinRL/FinRL-X 未安装；无 RL 主链 |
| Qbot | 只参考产品地图；保留 React/Vite 并实现 12 页控制台 | 未复制 Qbot 页面或自动交易代码 |

许可证已按当前上游复核：vectorbt 为 Apache-2.0 + Commons Clause，只批准隔离研究；vn.py/Qbot 为 MIT；OpenBB 为 AGPL-3.0-only，只允许未来独立 Sidecar 且需法务复核；FinRL classic 为 MIT，FinRL-X/Trading 为 Apache-2.0。

## API、UI 与 CLI

API 已补齐目标清单，包括：

- 领域/status/data-health/candidates/portfolio/ML/backtests/Paper/Shadow/approvals/execution/review/reports；
- `GET /api/vnext/runs/{run_id}`；
- `GET /api/vnext/snapshots/{snapshot_id}`；
- `GET /api/vnext/reconciliation/{run_id}`。

前端 12 个目标页面均存在并连接真实 API。lint exit 0、VNext DOM 12/12、生产构建成功、12 路由 HTTP 200；应用内浏览器运行时无可用实例，因此 console/点击证据保持 BLOCKED，不用独立 Playwright 冒充。

新增 CLI 包括 snapshot/data audit/recovery、target weights、domain decision、portfolio optimize、Fast/Event/reconcile、ML governance、execution certify、Antifragile、SBOM 和 acceptance build，均已注册到顶层 `hermes_cli.py`。

## 安全、依赖与质量门禁

- 安全测试：35/35；单元：13/13；VNext 集成：78/78；受影响旧链回归：139/139；前端：12/12。
- Ruff 通过；选定新安全/工件模块 mypy 通过；compileall 通过。
- Python `pip-audit`：137 个锁定组件、0 已知漏洞。
- npm production audit：240 个生产依赖、0 漏洞。
- CycloneDX 1.5 SBOM：197 个 Core/vectorbt 环境组件。
- CI gate 检查精确 pin/锁哈希、危险许可证、Core 禁止依赖、UI/API Broker 边界、secret、mock/fallback 证据。
- 曾发现的 `scripts/mx_fetch_step.py` 硬编码凭据已移除，改为 `MX_APIKEY` 环境变量；旧凭据必须外部轮换。

## 仍未完成且不能宣称完成的事项

1. 数据恢复和 freshness gate 尚未转为 OK；正式 ML、生产 OrderDraft 和 Shadow 候选仍 BLOCKED。
2. Event Truth 需要官方涨跌停、停牌、现金分红与复权数据。
3. Telegram 与 QMT bridge 未配置；本轮只有真实安全机制和 dry-run，不存在外部消息/券商联调成功证据。
4. Paper/Shadow 只有安全认证账本，没有连续多日权益曲线，因此无法计算真实 `paper_vs_backtest_gap` 和 `shadow_vs_paper_gap`。
5. 浏览器实例缺失，前端 console/点击门禁未通过。
6. Python lock 尚无包文件哈希；vectorbt 商业使用需重新审查。
7. 无真实下单实现。任何 Live 变更都是新的高风险授权范围，不属于本轮完成态。

详细阻塞见 `docs/vnext/unresolved_items.md`；正式 24 项证据位于 `artifacts/vnext/acceptance/reconcile-2026-07-10-87e7eeb9d701bba1/`。
