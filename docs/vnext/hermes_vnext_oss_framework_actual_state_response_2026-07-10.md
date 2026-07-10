# Hermes VNext 迭代后实际状态复核与开源框架对比结论补充

**复核日期：2026-07-10 23:27（Asia/Shanghai）**
**复核对象：当前 `research-assistant` 工作区、VNext 运行产物及《Hermes VNext 与开源量化框架对比分析及优化升级方案》**
**报告用途：向 ChatGPT Pro 反馈 VNext 实施后的真实状态，纠正原报告因缺少仓库访问而无法回答的项目事实**
**安全声明：本报告是工程状态复核，不构成投资建议，也不表示系统已具备实盘交易资格。**

---

## 1. 给 ChatGPT Pro 的结论先行

原报告的战略判断总体正确：Hermes 不应被 vn.py、Qbot、FinRL、OpenBB 或 vectorbt 整体替换，最合理的定位仍然是面向 A 股半导体/科技的垂直投研与交易治理控制平面。

但在看到迭代后工作区后，需要对“完成程度”和“开源框架采用方式”作两项重要修正：

1. **Hermes VNext 已不再只是目标架构。** 当前工作区已经形成可运行的 VNext 研究与治理链，包括真实数据门禁、Policy Put/指数箱体、广度与风格轮动、半导体主线状态机、Regime Router、组合风险诊断、可解释 ML 排序、Paper/Shadow、Telegram 审批记录、miniQMT 只读探测外壳、反脆弱复盘、API、CLI、报告和 12 页控制台。
2. **项目没有按“立即安装多个框架”的方式实现。** 当前核心依赖树中没有引入 vectorbt、vn.py、OpenBB、FinRL 或 Qbot。实际选择是吸收其架构思想，再用现有 Hermes/Tushare/Pandas/FastAPI/React 技术栈实现轻量自有模块。这降低了依赖、许可和运行环境风险，但也意味着这些成熟框架擅长的能力仍有明显缺口。

因此，当前最准确的成熟度描述是：

> **VNext 已完成“可运行的研究控制平面与 no-live 安全原型”，适合继续做真实数据补齐、Paper/Shadow 观察和内部验收；尚未完成统一目标权重生产链、双回测真值链、成熟 OMS/事件执行内核和任何真实交易联调。**

不能把当前状态表述成“全部 Gate 已退出”或“live-ready”。当前系统主动保持 `PARTIAL / READ_ONLY / no_live_trade=true / live_enabled=false`，这是正确行为，不是失败。

---

## 2. 本次复核依据与可信度边界

本次结论不再基于需求说明推演，而是基于以下现场证据：

- GitNexus 索引：29,609 个符号、45,802 条关系、300 条执行流；索引与当前提交一致，并能识别 VNext CLI、API、服务、前端和测试调用关系。
- VNext 后端实现：`commands/factor_lab/vnext/` 下 17 个 Python 模块。
- VNext 配置：`configs/vnext/` 下 6 份 YAML。
- API 与前端：`routes_vnext.py`、VNext API client/hooks、12 个页面路由。
- 真实运行产物：`data/vnext/` 约 1.2 GB，包含快照、数据健康、回测、ML 数据集/模型、候选、组合、Paper/Shadow、审批、报告和执行状态。
- 当前专项验证：VNext Python 测试 60/60 通过；前端 16 个测试文件、27 个用例通过；Vite 生产构建通过；lint 退出码为 0，但存在既有警告。
- 数据恢复现场：Tushare 财务数据拉取进程仍在运行，文件数量持续增长。

需要同时保留三项边界：

- 当前 VNext 代码主要存在于**未提交工作区**。Git HEAD 为 `688e9db`，工作区有 23 个已跟踪改动和 228 个未跟踪项，不能等同于已经合并、发布或可回滚的正式版本。
- 本次重跑的是 VNext 专项测试，不是整个历史测试矩阵；真实浏览器点击/console 验证仍因无可用浏览器实例而未完成。
- anti-cheat/leader 最终审计当前不是全绿。部分失败来自审计器自身异常或把 `Protocol` 的抽象方法误判为占位实现，但在修复审计工具并重新全量通过前，仍不能宣称最终质量 Gate 已关闭。

---

## 3. 原报告“尚未执行事项”的逐项回应

| 原报告缺失信息/未执行事项 | 当前真实状态 | 结论 |
|---|---|---|
| Hermes 仓库/代码快照 | 已可逐文件审计，GitNexus 已建立调用图 | **已补齐** |
| 现有 CLI 注册方式 | `commands/hermes_cli.py` 已接入 VNext 命令分派 | **已实现** |
| 前端 `package.json` 与构建 | React/Vite/Ant Design 继续使用；测试与构建通过 | **已验证** |
| Tushare 数据拉取 | 日线、估值、资金流和财务已真实拉取；财务仍在进行 | **进行中** |
| 代码测试 | 当前 VNext 专项 Python 60/60、前端 27/27 通过 | **专项通过，非全仓最终 Gate** |
| miniQMT Probe | 只读/探测协议和 Windows bridge 外壳已存在；当前未配置 `QMT_BRIDGE_BASE_URL` | **代码就绪，外部联调未做** |
| Telegram | 可生成审批记录、格式化/发送消息并支持四类决策；凭据未配置，webhook 签名与真实回调未验收 | **原型完成，运维联调未做** |
| Python 依赖锁文件 | 工作区未发现 `pyproject.toml`、requirements 或 Python lockfile；测试依赖 `.venv_quant` 和 `PYTHONPATH=commands` | **仍缺失** |
| 数据库 schema/迁移 | VNext 主要使用 JSON/JSONL/CSV 原子文件产物，没有专用事务数据库迁移链 | **未建设** |
| 当前审批与 QMT client | 已能审计现有 QMT client/bridge，并新增 VNext 只读边界 | **已获得代码可见性，真实账户不可用** |
| 第三方许可证/SBOM | 未见 VNext 专用 NOTICE、SBOM 或 Python 依赖许可清单 | **仍缺失** |

---

## 4. 当前端到端能力链：哪些已经真实存在

当前代码与产物支持以下链路：

```text
Tushare / 明确的本地真实文件
  → SourceObservation 与 MISSING/STALE/PARTIAL 门禁
  → 指数箱体 / Policy Support Proxy / 广度背离 / 风格轮动
  → 12 状态半导体主线状态机
  → 8 状态 Regime Router
  → 多资产相关性、下行相关、回撤重叠、风险贡献和假分散诊断
  → Ridge/ElasticNet 等横截面 score/rank（禁止 buy/sell）
  → 候选按权限、流动性、涨跌停/ST/停牌状态分组
  → Paper / Shadow / Live Dry-run 草案
  → Telegram 审批状态记录（API 只改状态，不触发 broker）
  → miniQMT ReadOnly/Probe 外壳（真实委托硬阻断）
  → 反脆弱复盘、API、CLI、Markdown/JSON/CSV 和 12 页控制台
```

其中，安全边界是当前最扎实的部分：

- `configs/vnext/execution.yaml` 固定 `no_live_trade: true`、`live_enabled: false`、`allow_direct_ui_order: false`。
- `TradingModeStateMachine` 明确拒绝进入 `LIVE_ENABLED`。
- `MiniQMTLiveBroker.submit()` 只返回 `BLOCKED/no_live_trade_safety_invariant`，没有真实发送路径。
- 审批 API 明确返回 `execution_triggered=false`。
- watch-only、Kill Switch、数据缺失/陈旧和无真实持仓 SELL 都有阻断测试。
- Paper/Shadow 产物记录 `real_broker_called=false`。

这支持原报告关于“Hermes 必须自己掌握单一安全真相”的判断。

---

## 5. 对五个开源框架结论的实施后回应

### 5.1 vn.py：吸收设计，尚未复用成熟执行内核

当前已实现的 vn.py 风格能力包括：

- 自有 `Broker` Protocol；
- Paper、Shadow、MiniQMT ReadOnly/Probe、永久禁用 Live Broker；
- 交易模式状态机；
- 前置安全检查；
- JSONL 审计日志；
- Web/API 与 Windows QMT bridge 的边界意识。

但当前还没有：

- 通用 EventEngine 和事务 Outbox；
- 完整 Tick/Bar/Order/Trade/Position/Account/Contract 对象体系；
- OMS 缓存、订单生命周期、撤单/成交回调和幂等恢复；
- 非阻塞重连、线程安全和独立交易进程；
- A 股高保真撮合（T+1、整手/零股、动态涨跌停、停牌、部分成交、最小佣金、印花税和冲击模型）。

当前 `PaperBroker` 是简化的立即模拟成交，不能被视为 vn.py 级 Paper Account 或真实撮合真相源。

**修正结论：** 继续保持“REFERENCE + OWN”是合理的；是否引入 vn.py EventEngine/OMS 应在真实 QMT 联调前单独决策，不应把当前 Broker 外壳描述成已完成 vn.py 适配。

### 5.2 Qbot：原结论完全成立

Qbot 没有进入依赖树，前端仍为现有 React/Vite 架构。VNext 已新增 12 页垂直控制台，但没有复制 Qbot 页面或实盘脚本。

**修正结论：** 继续只参考产品地图和导航思想，不建议引入 Qbot 核心依赖。

### 5.3 FinRL/FinRL-X：权重中心思想只完成了一半

FinRL/RL Agent 没有进入主链，这是正确的。当前弱 OOS Ridge 模型已经自动降级，说明项目确实坚持“模型不能直接控制交易”。

但原报告最看重的 `TargetPortfolioWeights` 统一契约尚未真正落地：

- 当前存在配置中的默认研究权重、快照中的 `portfolio_weights` 和组合风险归一化权重；
- 存在候选 score/rank、权限过滤和 `execution_eligible`；
- **不存在独立、稳定、可版本化的 `TargetPortfolioWeights`/`FeasibleTargetWeights` 对象**；
- 尚未打通 `signal → raw weights → eligible weights → risk-adjusted weights → order diff`；
- 配置中列出的 risk parity、minimum variance、maximum Sharpe 等优化器没有对应生产实现，当前主要是组合诊断而非组合构建。

**修正结论：** FinRL-X 的核心思想是下一阶段最应补齐的架构缺口，而不是已经完成的能力。

### 5.4 OpenBB：完成了质量包络思想，未完成 Provider 平台

当前已有 `SourceObservation`、统一 `ComponentResult`、source status、evidence/missing_evidence、freshness 和 fail-visible API/UI，且没有用备用源静默冒充真实数据。

但尚未形成 OpenBB 风格的 Provider/Fetcher/Router 插件体系，也没有标准 `MarketDataEnvelope` 的完整字段集合。港股和海外代理目录当前为 MISSING；VNext 数据路径仍直接依赖 Tushare client 和约定文件位置。

**修正结论：** 当前是“OpenBB-inspired response/quality layer”，不是 OpenBB adapter。短期不必安装 OpenBB；只有海外/宏观代理数据成为刚需时，才考虑独立 Sidecar。

### 5.5 vectorbt：研究回测已有，但 vectorbt 快车道和双引擎尚未实现

当前自研 Pandas 回测已支持：

- Policy Put/箱体/广度事件研究；
- 1/3/5 日持有期；
- 固定与动态阈值比较；
- 27 组成本/滑点/冲击组合；
- 3 种调仓频率；
- BULL/BEAR/RANGE_BOUND/LIQUIDITY_SHOCK 分阶段检查。

但代码中没有 vectorbt 依赖或 adapter，也没有 A 股事件回测引擎和 Fast/Event reconciliation。当前输出属于“假设事件研究 + 收益敏感性验证”，不能替代目标权重驱动的组合回测和订单级撮合。

**修正结论：** 原报告把 vectorbt 列为“立即采用”尚未执行。是否仍需要引入，应先用当前 666 万行 ML 数据和组合参数扫描做性能基准；若 Pandas 已满足日频研究，可继续延后，避免为了架构图增加依赖。

---

## 6. 原报告六个核心契约的实际完成度

| 目标契约 | 当前状态 | 主要缺口 |
|---|---|---|
| `MarketDataEnvelope` | **部分实现** | `SourceObservation` 有来源/状态/记录数/消息，但尚缺统一 asset/frequency、ingested_at、snapshot hash、schema version、entitlement 等完整契约 |
| `ResearchSignal` | **部分实现** | 候选字典有 score/rank/attribution/regime/mainline/执行资格，但没有独立 ID、校准置信度、训练/OOS 全字段的稳定模型 |
| `TargetPortfolioWeights` | **未完整实现** | 只有研究默认权重和风险诊断，没有贯穿研究—回测—执行的版本化目标权重对象 |
| `OrderDraft` | **可用原型** | 有 approval、标的、方向、数量、理由、Regime、模型、风险和权限；缺 order hash、expiry、账户 ID、目标/当前仓位、价格策略和 trace/snapshot ID |
| `ApprovedOrderEnvelope` | **未实现** | 当前审批记录没有 draft hash、过期时间、一次性 nonce、签名和 allowed quantity/price policy；Modify 会安全阻断旧审批，但完整重签流程未完成 |
| `ExecutionEvent/ReviewRecord` | **部分实现** | JSONL 追加日志和复盘记录已存在；缺事务性、幂等键、Outbox、跨进程恢复和完整订单/成交/持仓事件模型 |

这张表是对原“从 TopN 升级为目标权重契约”结论最关键的现实校正：VNext 已从单纯 TopN 明显前进，但尚未完成权重中心化。

---

## 7. 数据恢复与真实运行状态

### 7.1 2026-07-10 23:27 现场快照

| 数据项 | 当前数量/状态 | 说明 |
|---|---:|---|
| U0 股票池 | 5,530 | `data/universes.json` 中带 `ts_code` 的标的 |
| 日线 | 5,738 个文件 | 数据健康产物标记 OK |
| 估值 | 5,816 个文件 | 数据健康产物标记 OK；数量高于当前 U0，需统一覆盖分母 |
| 资金流 | 5,383 个文件 | 相对 U0 约 97.3%；数据健康产物以 5,738 为分母时显示 93.8% |
| 财务指标 | 4,001 个文件且持续增长 | 相对 U0 约 72.4%；后台 Tushare 任务仍在运行 |
| 涨跌停数据 | 4,438 个文件 | 尚非全覆盖 |
| 港股数据 | MISSING | 未建设正式数据目录 |
| 海外代理数据 | MISSING | SOX/Nasdaq 等仍是配置占位/代理需求 |
| 事件新闻 | STALE | 当前产物显示 3 天陈旧 |
| 东方财富盘中快照 | STALE | 当前产物显示 7 天陈旧 |

VNext 真实产物还包括：

- 政策假设数据集：2021-01-01 至 2026-07-10，共 1,336 个交易日；
- 固定/动态阈值结果：252 个假设结果；
- ML 训练集：6,668,235 行，约 1.2 GB；
- 当日评分集：5,510 行；
- Ridge OOS RankIC：0.001138，已自动标记 `PARTIAL/WATCH`、`promotion_eligible=false`；
- 盘前报告：Markdown/JSON/CSV 均已生成，整体状态为 PARTIAL。

### 7.2 需要修正的运行与治理问题

- 数据健康产物在 23:11 记录财务文件 2,323 个，而现场 23:27 已增长到 4,001 个，说明运行中数据恢复与控制台健康快照存在刷新滞后；任务结束后必须重跑 health/report。
- U0 为 5,530，但部分覆盖率使用 5,738 作为 expected files，覆盖分母需要统一，避免“覆盖率超过 100%”或不同页面口径不一致。
- 当前财务恢复任务通过内联 Python 逐股写文件并以“文件存在”断点续跑，实用但还不是完整的 run manifest/checkpoint/content hash/不可变 raw snapshot 方案。
- 旧审计显示 0 个 blocking gap、3 个 tag partial gap，但 freshness 报告仍因盘中/事件文件陈旧而 blocking；“缺口审计”和“实时可交易新鲜度”必须继续分开呈现。

---

## 8. 当前能力评分：目标分与实证分应分开

评分仍采用 0=基本没有、1=很弱、3=可用、5=核心强项。下表是本次基于工作区的保守实证分，不是长期上限。

| 能力 | 原目标分 | 当前实证分 | 说明 |
|---|---:|---:|---|
| A 股半导体垂直语义 | 5 | **4** | 12 状态机、Universe/ETF 替代和真实候选已存在；仍缺长期 OOS 证明 |
| 资产权限/ETF 替代/watch-only | 5 | **4** | 配置、门禁和测试完整；真实账户权限同步尚缺 |
| Policy Put/箱体/广度背离 | 5 | **4** | 已有真实数据事件研究；仍主要是代理指标和样本内结论 |
| Regime 与多资产路由 | 5 | **4** | 8 状态和预算输出可运行；缺目标权重闭环 |
| ML 截面排序 | 4 | **3** | 数据、模型卡、OOS 和降级治理已实现；当前模型预测力很弱 |
| 多 Provider 标准化 | 4 | **2** | 有状态包络，无插件 Provider 平台，港股/海外缺失 |
| 数据新鲜度/证据链 | 5 | **4** | fail-visible 表现良好；manifest/hash/口径一致性仍需补齐 |
| 大规模研究回测速度 | 3 | **3** | Pandas 日频事件研究可用；未做 vectorbt 性能快车道 |
| A 股高保真事件回测 | 4 | **1** | 没有订单级事件撮合真值引擎 |
| Gateway/OMS/交易事件 | 4 | **2** | Broker/状态机/审计外壳存在；无成熟 OMS/回调/重连/恢复 |
| Paper/Shadow/Backtest 归因 | 5 | **3** | 流程和产物存在；撮合、持久状态和长期对账仍简化 |
| Telegram 审批与 Kill Switch | 5 | **3** | no-live 安全强；真实 Telegram、签名、nonce、expiry 未验收 |
| 反脆弱复盘 | 5 | **3** | 结构化归因和训练样本已实现；缺长期闭环样本 |
| 现代化垂直控制台 | 5 | **4** | 12 页、测试与构建通过；真实浏览器交互验收未完成 |
| 通用生态和连接器 | 3 | **2** | QMT bridge 与既有生态可复用，但第三方 adapter 仍少 |

---

## 9. 测试、审计与工程化状态

### 9.1 本次现场验证结果

- VNext Python 专项：`60 passed in 2.70s`。
- 前端：`16 passed` test files，`27 passed` tests。
- 前端生产构建：成功，4,031 个模块；主 JS 约 2.99 MB、gzip 约 931 KB，存在大 chunk 警告。
- 前端 lint：退出码 0，但历史页面存在 unused vars 和 React hooks 依赖警告。
- VNext 12 页 HTTP/DOM 验证已有既存报告；真实浏览器 console 和点击仍为 BLOCKED。

测试运行还暴露了一个工程问题：从仓库根目录运行 pytest 必须显式设置 `PYTHONPATH=commands`。缺少标准 Python package/lockfile 会降低 CI、复现和第三方依赖隔离能力。

### 9.2 最终审计不能宣称全绿

当前最新审计文件仍显示 failed/`passed=false`，主要原因包括：

- Gate 1 审计器异常：`cannot use 'list' as a set element`；
- 一版 Gate 2 把 `Broker` Protocol 的抽象 `NotImplementedError` 识别为“占位实现”；
- 部分复杂度/空数据/测试命名警告；
- leader audit 另有 tmux 环境项失败。

这些不等同于发现真实下单漏洞，但必须先修复审计规则或提供合法抽象接口豁免，再重跑并获得全绿结果。现阶段最诚实的说法是“专项功能测试通过，最终自动审计仍未闭环”。

---

## 10. 当前不能宣称已完成的事项

以下项目应明确保留在未完成清单中：

1. 显式、版本化、可审计的 `TargetPortfolioWeights` 和 `FeasibleTargetWeights` 契约。
2. 由目标权重统一驱动的 Fast Research 与 A 股 Event Truth 双引擎，以及差异归因。
3. 配置中 risk parity、minimum variance、maximum Sharpe 等组合优化器的真实实现与 OOS 验证。
4. vn.py 级 EventEngine/OMS/订单—成交—持仓—账户生命周期。
5. A 股高保真 Paper 撮合、连续持仓账本、费用税费、T+1、涨跌停和部分成交。
6. 审批草案 hash、expiry、one-time nonce、签名校验、重复回调幂等和重启恢复。
7. Telegram webhook 运维、身份验证、回调签名和真实消息链路测试。
8. miniQMT 真实健康、账户、资金、持仓和回调联调；真实下单继续明确禁止。
9. 港股、海外代理、事件新闻和盘中快照的数据补齐与交易日/时区/复权对齐。
10. Python lockfile、独立 extras/environment、NOTICE、SBOM、许可证和漏洞扫描。
11. 全仓测试、真实浏览器验收、审计工具修复后的最终全绿 Gate。
12. 把当前大规模未提交工作区拆分为可评审、可回滚的提交/PR，并建立发布版本。

---

## 11. 对原升级路线的重新排序建议

当前不应优先继续扩展页面或引入 RL。建议按以下顺序收口：

### P0：完成当前数据任务并冻结可复现实验快照

- 等财务/资金流恢复结束；
- 统一 U0、日线、估值、资金流和财务覆盖分母；
- 重跑 gap/freshness/data-health/premarket report；
- 为每次拉取补 run manifest、失败清单、checkpoint 和内容哈希；
- 保存一个不可变的 VNext 验收 snapshot ID。

### P1：补齐权重中心契约

- 落地 `ResearchSignal → TargetPortfolioWeights → FeasibleTargetWeights → OrderDraft`；
- 把权限、watch-only、ETF 替代、Regime 预算和组合风险变成可审计约束；
- 先实现等权/风险平价/最小方差基线，再决定是否需要复杂优化器。

### P2：建立双回测真值链

- 先写最小 A 股事件撮合引擎和统一 reconciliation；
- 用真实参数扫描基准决定是否引入 vectorbt；
- vectorbt 只在能显著降低研究耗时且不破坏契约时引入。

### P3：执行治理硬化

- 完整 Approval Envelope：hash、expiry、nonce、signature、idempotency；
- 事件账本改为可恢复存储；
- 完成 Telegram dry-run 到真实回调联调；
- miniQMT 仍只做 ReadOnly/Probe，保持无真实委托。

### P4：工程发布收口

- 建立 Python 包定义与锁文件；
- 增加 SBOM/NOTICE/依赖许可清单；
- 修复自动审计器异常与误报；
- 完成全仓测试、真实浏览器验证和可回滚提交拆分。

FinRL/RL、OpenBB Sidecar 和 vn.py 执行内核均可继续延后，等待真实瓶颈出现后再引入。

---

## 12. 最终反馈口径

建议向 ChatGPT Pro 使用以下表述：

> 你的原始战略结论基本成立，尤其是“不整体替换 Hermes、不把五个框架塞进同一环境、交易安全和领域真相必须自有”。VNext 迭代后，Hermes 已经具备可运行的垂直研究控制平面和 no-live 安全原型，而不是停留在设计文档。项目实际没有直接引入 vn.py、Qbot、FinRL、OpenBB 或 vectorbt，而是自研实现了其部分架构思想。当前最需要校正的是：目标权重统一契约、vectorbt/事件双回测、成熟 OMS、签名审批包络和第三方依赖治理尚未完成；数据恢复仍在进行，真实 Telegram/QMT 也未联调。因此项目可以进入数据收口、Paper/Shadow 和内部验收阶段，但不能宣称已具备生产实盘能力或全部 Gate 已通过。

综合判断：

- **产品定位：正确且已经被代码初步证明；**
- **核心研究功能：基本完成；**
- **数据恢复：接近完成但仍在运行，实时/海外/事件侧仍有缺口；**
- **安全策略：正确，真实下单默认不可达；**
- **执行工程成熟度：仍明显低于 vn.py；**
- **数据 Provider 成熟度：仍明显低于 OpenBB；**
- **研究扫描与双回测成熟度：仍低于 vectorbt + 事件引擎组合；**
- **ML：治理合格，但当前模型有效性不足；**
- **当前发布状态：可运行工作区原型，尚不是已提交、全审计通过的正式版本。**

这比原报告的“目标态推演”更贴近当前项目事实，也保留了对剩余风险的准确边界。
