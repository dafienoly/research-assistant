# Hermes VNext 迭代后开源框架对比与实际状态反馈

**反馈日期：2026-07-11**
**对照报告：`hermes_vnext_oss_framework_comparison_report_2026-07-10.md`**
**用途：向 ChatGPT Pro 反馈 VNext 实施后的真实项目状态**

## 一、可直接反馈的结论

原报告的总体技术选型是正确的：Hermes 不应被 vn.py、Qbot、FinRL、OpenBB 或 vectorbt 整体替换，而应继续作为面向 A 股半导体/科技的垂直投研交易控制平面。VNext 迭代后，原报告提出的核心骨架大部分已经从“建议”变成了可运行代码和正式工件：

- `TargetPortfolioWeights` 已成为研究、组合、双回测和执行认证的统一契约；
- vectorbt 已作为隔离 Fast Lane 实际运行；
- Hermes 自有 A 股 Event Truth Lane 已实际运行并与 Fast Lane 对账；
- OpenBB-inspired Provider/Fetcher/Router 已实现；
- vn.py 风格 Event/OMS/Gateway/交易对象已由 Hermes 自研实现第一版；
- HMAC 审批封套、TTL、nonce、ExecutionGuard、哈希链审计已完成；
- Paper/Shadow/LiveDryRun 安全链、七层 Antifragile Review、稳定 API 和 12 页 UI 已完成；
- 独立锁文件、NOTICE、许可证审查、CycloneDX SBOM、漏洞/secret/Broker 边界 CI gate 已完成。

但项目仍不能被描述为“生产交易系统已经完成”。当前正式状态是：

> **工程主链已闭合，真实数据与安全认证可运行；数据/外部连接/连续运营验收仍为 PARTIAL，模型和交易晋级保持 BLOCKED，no_live_trade 永久开启。**

## 二、原报告中“不能回答的项目情况”，现在可以怎样回答

| 原报告待实际审计项 | 迭代后真实答案 | 证据 |
|---|---|---|
| 实际代码依赖图与循环依赖 | 已建立 VNext 依赖图；研究信号、vectorbt、UI/API 到 Broker 的禁边均被 CI 检查 | `artifacts/vnext/dependency_graph.json`、`hardening_report.json` |
| Python/前端兼容性 | Core Python 3.14.4；vectorbt 1.1.0 隔离环境；React/Vite 构建成功 | `requirements/*.lock`、`ui_build_report.txt` |
| miniQMT 实际状态 | QMT bridge 未配置；只读 probe=MISSING，订单通道 DISABLED；没有真实下单 | `execution_certification.json` |
| Telegram 实际状态 | Bot/Chat 未配置；消息只做 DRY_RUN；审批封套和审计链真实通过 | `approval_audit.jsonl`、`execution_certification.json` |
| 数据恢复进度 | 日线/估值 U0 覆盖完整；资金流匹配 5,401/5,530、财务 5,528/5,530，剩余 129/2 均为上游明确空结果；概念 409、行业 511 已转 OK | `data_gap_report.json`、`data_audit_report.json` |
| 不可变快照 | 29/29 manifest 验证；统一 snapshot ID；无 silent fallback | `snapshot_manifest.json` |
| 目标权重主链 | 已实现；当前 65% 投资、35% 现金，Semi failure 将半导体 ETF 权重归零 | `target_weights.json` |
| vectorbt 快车道 | 已直接采用 1.1.0；146 日、7 标的、18 参数、2 OOS folds、3 成本场景 | `fast_backtest_manifest.json` |
| A 股 Event Truth | 已实现 T+1、板块/ST 涨跌停、停牌/权限、100 股、容量、冲击、部分成交/撤单；当前缺官方 limits/suspend/公司行为数据 | `event_backtest_manifest.json` |
| 双回测对账 | 相同 snapshot/weights 已证明；收益差 0.000183、回撤差 0.000215、期末差 ¥182.60/¥1m，容差内 | `reconciliation_report.json` |
| ML 治理 | 208,106 时点样本；XGB OOS RankIC 0.02042，优于 Ridge -0.02040；数据 PARTIAL 使 promotion BLOCKED | `ml_ranker_manifest.json` |
| Paper/Shadow | 安全认证真实运行并产生账本；Paper FILLED、Shadow RECORDED、LiveDryRun 成形不传输；nonce 重放阻断 | `paper_ledger.jsonl`、`shadow_ledger.jsonl` |
| API/UI 是否真实连接 | 18 类稳定 API（含 run/snapshot/reconciliation）与 12 页 UI；真实 API/路由 HTTP 200，DOM 12/12 | `ui_build_report.txt` |
| 第三方治理 | 五环境锁状态、NOTICE、license review、197 组件 SBOM、Python/npm 0 已知漏洞 | `approved_dependencies.yaml`、`sbom.cdx.json` |

## 三、逐框架修正评价

### 1. vectorbt：从“建议直接采用”变为“已经隔离采用”

原报告对 vectorbt 的定位已实际落地。vectorbt 1.1.0 不在 Core，而在 `.venv_vectorbt`；Worker 只读取 Hermes 的不可变快照和目标权重，AST 边界禁止数据下载客户端、QMT/Broker 和订单输出。

实际 Fast Lane 不只是存在 adapter：已经完成参数扫描、事件研究、Walk-Forward 和成本压力。第二个 OOS fold 为 -6.03%，系统没有选择性隐藏负结果。Fast Lane 的成交只被标记为研究估计，最终成交语义仍由 Event Truth Lane负责。

需要修正原报告的许可证表述：当前 vectorbt 不是纯 Apache-2.0，而是 **Apache-2.0 + Commons Clause**。Hermes 只批准内部隔离研究，商业托管/分发前需重新审查。

### 2. vn.py：核心模式已自研适配，但没有安装 vn.py 运行时

Hermes 已拥有 vn.py 风格的 EventEngine、Bar/Order/Trade/Position/Account/Contract、Paper Gateway、OMS 和机械风控，并实现 A 股 T+1、不同板块/ST 涨跌停、权限、整手、容量、冲击、部分成交和撤单。

因此不能再说“事件/OMS 完全缺失”；更准确的说法是：

> Hermes 已完成 vn.py 模式的第一版等价适配，但没有直接依赖 vn.py，也尚未具备成熟 vn.py Gateway 的异步重连、完整回报生命周期、长期 Paper Account 和真实 MiniQMT adapter。

这保留了安全控制权，也意味着执行成熟度仍低于完整 vn.py 生态。

### 3. OpenBB：Provider 平台第一阶段已完成，Sidecar 未启用

已实现 Hermes 自有 `ProviderQuery/DataFetcher/Registry/Router`，并为 Tushare、Local CSV、AkShare、腾讯、东方财富、MiniQMT 与可选 OpenBB Proxy 定义统一边界。所有原始读取都会产生内容哈希、observed/available 时间、质量状态、manifest 和冲突记录；次级源不会静默升级成主源。

OpenBB 包没有安装，Proxy 默认关闭；A 股主数据仍是 Tushare/明确本地源。由于 OpenBB 为 AGPL-3.0-only，未来只能在独立 Sidecar 和单独法务审查下启用。

### 4. FinRL / FinRL-X：只吸收权重契约，不引入 RL

FinRL-X 最有价值的“权重中心”架构已经实现：研究信号不会直达订单，统一先变成 `TargetPortfolioWeights`，再进入组合约束、Fast/Event 双回测、对账和未来订单差分。

FinRL/FinRL-X 运行时均未安装，RL 沙箱仍关闭。当前 ML 采用时点特征、purge/embargo、Ridge 基线和 XGBoost Ranker；只输出 score/rank/confidence，不输出买卖或订单。这个选择与原报告“RL 不进入主链”一致。

### 5. Qbot：UI 产品参考已经完成，代码仍未复用

Hermes 保留 React/Vite/Ant Design，实现了 Control Tower、Regime、Semiconductor、Candidates、Portfolio、ML、Backtest、Paper/Shadow、Approval、Execution、Review、Data Health 共 12 页。没有复制 Qbot 页面、依赖或自动交易链。

这验证了原报告“Qbot 只参考产品地图”的建议。当前前端构建和 DOM 测试通过，但应用内浏览器实例为空，因此 console/真实点击证据仍为 BLOCKED；不能把 HTTP 200 当成完整浏览器验收。

## 四、Hermes 自研能力现在到了什么程度

| 能力 | 实际成熟度 | 说明 |
|---|---|---|
| 数据真相/恢复/Provider | S4，但质量 PARTIAL | 实跑、持久化、审计、恢复演练均有；覆盖和 freshness 未收口 |
| 领域决策 | S4，PARTIAL | RANGE_BOUND / SEMI_FAILURE 已进入目标权重；部分风格证据不足 |
| 目标权重与组合约束 | S4，BACKTEST_ONLY | restricted/watch-only 强制归零、ETF substitution 显式、无持仓不卖 |
| 双回测与对账 | S4 | Fast/Event 同源同权重；对账 OK，但 Event 证据不全 |
| 组合优化 | S4 | 等权、逆波动、风险平价、最小方差、稳健最大 Sharpe、成本感知六种方法 |
| ML Ranker | S4，promotion BLOCKED | XGB 优于 Ridge，但数据门禁优先于指标 |
| 审批/执行安全 | S4 | 签名、TTL、nonce、Kill Switch、hash-chain；无 live send |
| Paper/Shadow | S4 安全认证，运营历史不足 | 有可回放账本；尚无连续权益曲线 |
| Antifragile Review | S4，PARTIAL | 七层归因与 reason code；真实标签/长期差异指标仍缺 |
| API/UI | S3/S4 混合 | API/构建/DOM 完成；浏览器交互门禁阻塞 |
| SBOM/License/CI | S4 | 依赖隔离、哈希 gate、漏洞/secret/Broker 边界已实跑 |

## 五、当前最重要的剩余工作

1. 为资金流 129 只和财务 2 只上游空结果建立等待/替代源策略，补齐 3 份标签，并把 freshness gate 从 blocking 转为 OK；概念/行业目录已无需重复拉取。
2. 为 Event Truth 补官方 `stk_limit`、`suspend_d`、现金分红和复权因子。
3. 配置 Telegram 与只读 QMT bridge 后做外部联调，但继续保持订单通道 disabled。
4. 连续运行 Paper/Shadow，形成权益、订单、成交、未成交与滑点历史，计算真实 `paper_vs_backtest_gap` 和 `shadow_vs_paper_gap`。
5. 累积 realized Regime/Semi/Style 标签和滚动模型复盘，使 Antifragile 的 null 指标可计算。
6. 在 Codex 提供可用浏览器实例后补跑 12 路由 console/点击/截图门禁。
7. 撤销并轮换曾硬编码在脚本中的旧 MX API 凭据。

在这些项目完成前，正确产品表述是“可审计的研究/回测/Paper-Shadow 安全平台”，不是“生产实盘系统”。

## 六、建议给 ChatGPT Pro 的反馈文本

> 你的原始战略结论已被本轮实施验证：Hermes 应保留领域真相、数据真相和安全真相，把开源框架限制在可替换边界内。VNext 现已实际实现统一目标权重、隔离 vectorbt Fast Lane、Hermes A 股 Event Truth Lane、同源双回测对账、OpenBB-inspired Provider、vn.py 风格 Event/OMS、ML 排序治理、HMAC 审批封套、ExecutionGuard、Paper/Shadow/LiveDryRun 账本、七层复盘、稳定 API/UI 以及 SBOM/CI。需要更新你此前的判断是：这些主干能力不再是“尚未实现”，但多数采用的是 Hermes 自研等价适配，而不是安装完整 vn.py/OpenBB/FinRL/Qbot。当前正式数据审计仍 PARTIAL，Event Truth 缺官方交易状态/公司行为，Telegram/QMT 未配置，连续 Paper/Shadow 历史不足，浏览器交互验收也受运行时实例缺失阻塞。因此工程闭环已形成，但生产晋级仍必须 BLOCKED，且 no_live_trade 保持开启。
