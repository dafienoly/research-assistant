# Hermes VNext 当前工作区状态校准

更新时间：2026-07-11 00:53（Asia/Shanghai）
分支：`agent/hermes-vnext-upgrade`
基线提交：`86a5377 Add governed Hermes VNext workflow`
## 结论

当前 VNext 已形成真实数据驱动的研究、API、CLI、控制台和 no-live 安全原型，但尚未达到开源补强实施方案定义的完成态。领域研究模块多数已达到 S3/S4；核心跨模块契约、目标权重主链、vectorbt Fast Lane、A 股 Event Truth Lane、完整 ExecutionGuard、Provider Registry、依赖隔离和 SBOM 仍为 S0–S2。

成熟度定义：

- S0：不存在；
- S1：仅有接口、配置、占位或示例；
- S2：有实现和单元测试，但未接入主流程；
- S3：已接入主流程并通过集成测试；
- S4：有真实数据运行记录、持久化结果和可观测性。

## 状态矩阵

| 模块 | 等级 | 现场证据 | 主要缺口 | 差量动作 |
|---|---|---|---|---|
| 数据恢复/gap/freshness/audit | S4 | `data/normalized/*`、`data/audit/*`、`docs/vnext/e2e_acceptance_report.md` | 资金流、概念/行业、停牌、港股、海外代理和实时/事件新鲜度未完整；缺统一 immutable run manifest | PR-02 完善，不重写拉取器 |
| Data Quality/Freshness Gate | S4 | `data_quality.py`、`snapshot.py`、`data/vnext/data-health/latest.json` | provider conflict、PIT available_at、统一 snapshot hash 未完整 | PR-02/03 扩展 |
| Universe/权限/ETF substitution | S4 | `universe.yaml`、`MultiAssetUniverseRegistry`、真实候选产物及安全测试 | 真实账户权限快照尚未进入统一权重契约 | PR-04 适配 |
| Hermes 七个核心契约 | S1 | 仅有枚举、`ComponentResult`、`SourceObservation` 和 execution 内部 dataclass | 缺 MarketDataEnvelope、ResearchSignal、TargetPortfolioWeights、ApprovedOrderEnvelope、ExecutionEvent、ReviewRecord 稳定 schema | PR-01 实现 |
| TargetPortfolioWeights | S0 | 无同名契约/主链；仅有默认研究权重和组合诊断字典 | 未形成 signal→eligibility→risk overlay→weights→orders | PR-01/04 实现 |
| Provider/Fetcher/Router | S1 | 现有 Tushare client 与 snapshot 直接调用；有来源状态 | 无 registry/fetcher/router、conflict/alternative 协议 | PR-03 实现 |
| vectorbt adapter | S0 | 源码与依赖均无 vectorbt | 无隔离环境、manifest、broker 禁依赖证明 | PR-04 实现 |
| A 股 Event Truth Lane | S0 | 只有 Pandas 假设回测和简化 PaperBroker | 无事件撮合、T+1/涨跌停/部分成交/撤单/对账 | PR-05 实现 |
| Policy Put/Index Box/Breadth/Style | S4 | `market.py`、真实 2021–2026 回测与报告 | 仍需通过 Fast/Event 共用权重和快照验证 | PR-06 适配 |
| Semiconductor Mainline | S4 | 12 状态机、真实运行产物、状态测试 | 缺与目标权重的显式预算变换契约 | PR-06 适配 |
| Regime Router | S4 | 8 状态、预算输出、真实运行产物 | 未进入 `TargetPortfolioWeights` risk overlay | PR-04/06 适配 |
| Portfolio optimizer | S1 | YAML 列出优化器；代码只有风险诊断/候选边际影响 | constrained equal/逆波动/风险平价/最小方差/稳健 Sharpe 未实现 | PR-07 实现 |
| False diversification | S4 | 20/60/120 相关、下行相关、回撤重叠、beta、marginal Sharpe 真实产物 | PCA/common beta 与风险簇仍缺 | PR-07 扩展 |
| ML Ranker/Registry | S4 | 666 万行真实训练数据、模型 hash、OOS RankIC、WATCH 降级 | PIT FeatureView、purge/embargo、GBDT ranker、成本后/多 Regime 晋级闸门未完整 | PR-08 扩展 |
| PaperBroker | S4 | CLI、JSONL、真实草案 dry-run、持久产物 | 立即成交过于简化；无 T+1、费用、部分成交和重启重建 | PR-05/09 增强 |
| ShadowBroker | S4 | CLI、JSONL、真实草案 dry-run、发送次数为 0 | 缺行情对照、长期连续运行和可重建状态 | PR-09 增强 |
| Telegram approval | S4 | 凭据只读验证、审批状态、dry-run、持久审计 | 缺 draft hash、TTL、nonce、签名、callback 幂等 | PR-01/09 加固 |
| MiniQMT ReadOnly/Probe | S4 | 2026-07-11 Probe 已连接，账户/持仓可读，订单通道关闭 | execution status 尚未合并最新 probe；无统一 Gateway 对象适配 | PR-09 适配 |
| MiniQMTLiveBroker | S1 | 类存在且永久返回 BLOCKED | 保持默认 disabled；未来只允许接收 ApprovedOrderEnvelope | PR-01/09 安全包装 |
| ExecutionGuard | S2 | `SafetyGate`、`GovernedExecutionEngine` 和 no-live 测试 | 当前可接收 OrderDraft；无 ApprovedOrderEnvelope hash/TTL/nonce 验证；无事务幂等账本 | PR-01 实现 |
| API | S4 | 15+ VNext API、TestClient 运行与报告下载 | 缺 runs/snapshots/reconciliation API 和完整统一包络 | PR-10 扩展 |
| UI | S3 | 12 页 DOM 测试、27/27 前端测试、生产构建 | Chrome Native Messaging 阻塞真实 console/点击；缺新增 artifacts 页面数据 | PR-10 扩展 |
| Antifragile Review | S3 | 结构化结论、API/CLI、测试和持久产物 | 未消费统一 snapshot/weights/order/approval/event correlation chain | PR-11 扩展 |
| Python 依赖与环境隔离 | S0 | 只有现有 `.venv_quant`，测试需 `PYTHONPATH=commands` | 无 pyproject/lock、vectorbt/vn.py 独立环境 | PR-04/12 实现 |
| NOTICE/许可证/SBOM | S0 | 未发现目标资产 | 无 approved dependencies、license review、CycloneDX SBOM | PR-12 实现 |
| FinRL Classic sandbox | S0 | 未实现且未进入生产依赖 | 按方案默认关闭；优先级低于主干 | PR-12 或明确 defer |
| Qbot integration | S0 | 未引入依赖 | 按设计仅参考 UI，不实施运行时 | 保持 S0 |

## 当前调用与依赖主链

```text
React VNext pages
  → /api/vnext/*
  → routes_vnext.py
  → VNextService / VNextArtifactStore
  → HubSnapshotBuilder
  → market / semiconductor / regime / portfolio / ML

hermes_cli.py
  → vnext.cli.handle
  → datasets / backtest / service / trading / approval / QMT probe / review

Paper/Shadow
  → GovernedExecutionEngine
  → OrderDraft + SafetyContext
  → PaperBroker | ShadowBroker

当前缺失主链：
ResearchSignal → TargetPortfolioWeights → ApprovedOrderEnvelope
→ ExecutionGuard → Event Truth/Paper/Shadow
```

## CLI、API、UI 与数据库现状

- CLI：VNext 注册 14 个领域/训练/回测/交易/审批/Probe/复盘命令；使用项目根 `.env` 且显式环境变量优先。
- API：status、data-health、regime、policy-put、semi-mainline、candidates、portfolio-risk、ml-ranker、backtests、paper、shadow、approvals、execution-status、antifragile-review、reports 已注册。
- UI：12 个 VNext 路由连接真实 API client/hooks；无直接实盘下单入口。
- 数据库：VNext 没有专用关系数据库或迁移；当前真相源是 CSV/JSON/JSONL 原子文件。`database_schema_snapshot.sql` 应明确记录为“不适用/文件存储”，而不是伪造表结构。

## 安全路径审计

已证明：

- `no_live_trade=true`、`live_enabled=false`；
- `LIVE_ENABLED` 状态不可达；
- MiniQMT Probe 只读，订单通道关闭；
- Approval API 只改变状态并返回 `execution_triggered=false`；
- UI/API 未导入 QMT/vn.py Broker SDK；
- Paper/Shadow 记录 `real_broker_called=false`；
- 无真实持仓时禁止 SELL；watch-only/restricted 不得进入可执行候选。

尚未证明：

- “只有 ApprovedOrderEnvelope 可进入 Execution Service”；
- 审批 hash、TTL、nonce、签名和一次性消费；
- append-only ledger 的 hash chain、重启恢复和并发幂等；
- Kill Switch 对未来所有 Gateway send 的单一静态调用点覆盖；
- Fast/Event/Paper/Shadow 使用相同 snapshot 和 weights hash。

## 现场测试基线

- Python VNext 专项：62/62 通过，JUnit：`artifacts/vnext/test_runs/pr00_vnext_baseline.xml`。
- 前端：16 个测试文件、27 个测试通过。
- 前端生产构建：成功，4,031 modules；主 bundle 2.99 MB，存在 chunk size warning。
- 前端 lint：退出码 0，存在 legacy unused/react-hooks 警告。
- GitNexus：索引落后于 `86a5377`；刷新被 GitNexus 1.6.6 缺失 `tree-sitter-swift` 及其安装链下载阻塞。已保留工具级阻塞，未以旧索引冒充当前调用图。

## 差量 PR 顺序

1. PR-01：七个契约、TargetPortfolioWeights、Approval hash/TTL/nonce/signature、ExecutionGuard、hash-chain ledger；
2. PR-02/03：不可变 snapshot/manifest 和 OpenBB-inspired provider 协议；
3. PR-04/05：隔离 vectorbt Fast Lane、A 股 Event Truth Lane 和 reconciliation；
4. PR-06–09：把现有 S3/S4 领域能力接入统一权重与事件链，不重写；
5. PR-10–12：补 API/UI、观测、依赖隔离、许可证/SBOM 和最终证据包。
