# Hermes Detailed Version Roadmap V3–V9

作者：ChatGPT

用途：这是 Hermes 固定版本路线图的详细规划源规格。Hermes 负责实现、展示和验收，不负责自行决定每个版本要干什么。Dashboard 的“固定版本规划详情”应从本文档或等价结构化数据中读取详细字段。

## 总原则

1. 先投研系统，再交易系统。
2. 先真实数据、可解释报告、可观测 Agent，再策略自动化。
3. 不接受 silent fallback；数据不可用必须明确失败并说明来源、时间、延迟和失败原因。
4. research、test、dry-run、acceptance 类任务可以自动执行。
5. 任何涉及资金、实盘、外部执行、配置变更的阶段必须人工确认。
6. 每个版本必须有交付物、验收标准、测试计划、审计记录。
7. 用户不可买的科创/创业板标的可作为行业温度，不进入可交易组合。

---

## V3.x — Alpha Factory

### V3.0 — Alpha Factory Foundation

**目标**：建立 Alpha 工厂的基础抽象，让因子、假设、评估、生命周期和产物都能被统一管理。

**开发范围**：定义 AlphaSpec、AlphaRegistry、AlphaLifecycle、ArtifactManifest、基础 CLI 和审计日志。

**交付物**：
- `AlphaSpec` 数据结构，包含名称、公式、假设、数据需求、股票池、适用周期、风险和失效条件。
- 文件系统 Alpha Registry，支持 register、list、show、status。
- 生命周期状态机：candidate、research、evaluation、approved、paper、retired、rejected。
- JSONL 审计日志和 manifest。
- `hermes factor:alpha-*` 或等价 CLI。

**验收标准**：能注册、查询、状态流转至少 3 个示例 Alpha；非法状态转换被拒绝；所有操作写审计。

**测试计划**：单元测试覆盖 schema、registry、lifecycle、manifest；CLI smoke test。

**边界**：不做实盘，不自动下单，不把新 Alpha 直接用于组合。

---

### V3.0.1 — Existing Factor Catalog Migration

**目标**：把已有因子迁移进 Alpha Registry，避免旧因子散落在脚本、报告和临时文件中。

**开发范围**：盘点现有因子，生成 AlphaSpec，补齐元数据，标记数据需求和当前可计算状态。

**交付物**：
- 已有因子清单。
- 每个旧因子的 AlphaSpec。
- 迁移报告：可用、缺数据、重复、废弃、待验证。
- 兼容层：旧 factor 名称到新 Alpha ID 的映射。

**验收标准**：所有现有核心因子都有 registry 记录；旧 CLI/报告不因迁移失效；重复因子被合并或标记。

**测试计划**：迁移脚本幂等测试；registry 查询测试；旧因子调用兼容测试。

**边界**：只迁移和整理，不改变因子逻辑，不提升任何因子到交易状态。

---

### V3.1 — Industry Relative Alpha Pack

**目标**：建立行业相对强弱因子，重点服务 A 股半导体、科技主线和用户可买股票池。

**开发范围**：行业内相对动量、行业中性排名、产业链分支强弱、主板可买约束。

**交付物**：
- 行业内 rank 因子。
- 半导体设备、材料、封测、存储、PCB/CCL、光模块、服务器、EDA/IP 分支标签。
- 行业温度指标。
- 用户可买约束过滤器。

**验收标准**：能输出 industry-relative score；科创/创业板只能用于温度，不进入用户不可买组合；报告解释行业相对排名来源。

**测试计划**：行业标签覆盖率测试；不可买股票过滤测试；行业内排名稳定性测试。

**边界**：不做单票推荐闭环，不直接生成订单。

---

### V3.2 — Factor Evaluation & Orthogonality

**目标**：建立统一 Alpha 评估门禁，防止 LLM 或人工因子过拟合、重复、弱于基准。

**开发范围**：IC、RankIC、ICIR、OOS、Walk Forward、同池等权对比、因子相关性和正交性。

**交付物**：
- 统一 evaluation runner。
- 评分卡。
- overfit warning。
- placebo/random baseline。
- 因子相关性矩阵。

**验收标准**：每个 Alpha 晋级必须有评分卡；低于同池等权或高度重复的 Alpha 不能晋级。

**测试计划**：构造正负样例；未来函数防护测试；随机因子 baseline 测试；walk-forward 分段测试。

**边界**：评估只产生研究结论，不修改 paper/live 配置。

---

### V3.3 — Data Enrichment Alpha Pack

**目标**：引入资金流、北向、两融、公告等增强数据，提升 Alpha 解释力。

**开发范围**：资金流因子、两融变化、北向持仓变化、公告事件特征、数据缺失标记。

**交付物**：
- enrichment data contract。
- 资金流 AlphaSpec。
- 两融/北向 AlphaSpec。
- 数据可得性报告。

**验收标准**：缺数据时明确标记 unavailable；增强因子与基础价格量因子分层展示。

**测试计划**：数据源缺失测试；字段类型测试；时点可用性测试。

**边界**：不允许用未来公告或未来修正数据。

---

### V3.4 — Technical Pattern Control Pack

**目标**：把 MACD、KDJ、Boll、均线等传统技术指标作为控制变量，而不是盲目当作主 Alpha。

**开发范围**：技术指标计算、趋势/震荡状态分类、与主 Alpha 的交互分析。

**交付物**：
- 技术指标库。
- 技术状态标签。
- control factor 报告。
- 与主 Alpha 的条件表现分析。

**验收标准**：技术指标可复现；不会覆盖主 Alpha 排名，只作为控制和解释维度。

**测试计划**：指标公式测试；边界窗口测试；停牌/缺失数据测试。

**边界**：不做“金叉买死叉卖”的单规则交易系统。

---

### V3.5 — Event-driven Alpha Pack

**目标**：建立事件驱动 Alpha，如解禁、回购、分红、增减持、监管函、业绩预告。

**开发范围**：事件解析、事件窗口、事件严重性、黑名单/白名单标签。

**交付物**：
- event schema。
- 事件 AlphaSpec。
- 事件窗口回测。
- 风险事件过滤器。

**验收标准**：事件具有 timestamp、source、影响方向和置信度；高风险事件能进入排除理由。

**测试计划**：事件日期对齐测试；公告解析失败测试；事件窗口收益测试。

**边界**：不根据单一新闻事件直接下单。

---

### V3.6 — Alpha Portfolio Intelligence

**目标**：从单因子转向多 Alpha 组合，解决因子拥挤、重复、失效和权重分配问题。

**开发范围**：Alpha 权重、相关性降权、失效检测、组合 score、paper 级信号输出。

**交付物**：
- Alpha ensemble engine。
- 权重配置。
- 相关性降权。
- alpha retirement candidate 列表。

**验收标准**：组合 score 可解释；任一 Alpha 失效不会单独支配组合；输出只进入 paper/research。

**测试计划**：权重归一化测试；相关性降权测试；失效因子剔除测试。

**边界**：paper 级别，不触发真实执行。

---

### V3.7 — LLM Alpha Discovery

**目标**：让 LLM 生成 Alpha 候选，但严格限制在 AlphaSpec，不允许直接交易。

**开发范围**：LLM prompt contract、AlphaSpec 生成、重复检测、不可计算检测、未来函数检测。

**交付物**：
- LLM Alpha prompt 模板。
- AlphaSpec validator。
- candidate queue。
- rejected reason 报告。

**验收标准**：LLM 只能输出候选 spec；低质量、不完整、不可计算、未来函数候选被拒绝。

**测试计划**：构造错误 AlphaSpec；重复候选检测；字段完整性测试。

**边界**：LLM 不得直接改 paper/live 配置，不得发出下单动作。

---

### V3.8 — Alpha Review Queue & Governance

**目标**：建立 Alpha 审核队列，让候选能被人工或自动规则治理。

**开发范围**：review queue、证据附件、审核意见、风险标记、状态流转。

**交付物**：
- review queue 存储。
- 审核 CLI/UI 数据。
- reviewer decision schema。
- 审核审计日志。

**验收标准**：每个候选都有审核历史；通过/拒绝理由可追溯。

**测试计划**：并发审核测试；非法状态测试；审计日志测试。

**边界**：审核通过不等于进入真实执行。

---

### V3.9 — Alpha Promotion/Retirement Engine

**目标**：建立 Alpha 晋级和退役机制，避免策略长期堆积和失效因子继续影响组合。

**开发范围**：晋级规则、退役规则、观察期、降权期、回滚机制。

**交付物**：
- promotion policy。
- retirement policy。
- watchlist。
- promotion report。

**验收标准**：Alpha 晋级必须通过评估门禁；退役有证据；所有变化可回滚。

**测试计划**：晋级/退役状态机测试；回滚测试；阈值边界测试。

**边界**：不自动进入 live。

---

## V4.x — Controlled Execution Readiness

### V4.0 — Controlled Live Pipeline Design

**目标**：设计受控实盘管线，但只做架构和合约，不执行真实交易。

**开发范围**：research signal、proposal、approval、execution intent、audit 的分层合约。

**交付物**：
- execution pipeline design。
- signal-to-proposal contract。
- approval gate spec。
- risk boundary doc。

**验收标准**：所有真实执行路径都必须经过人工确认；设计能解释从信号到意图的每一步。

**测试计划**：合约 schema 测试；危险路径拒绝测试。

**边界**：设计阶段，不接真实 broker。

---

### V4.1 — Shadow Live Pipeline

**目标**：构建影子实盘流水线，用真实行情和模拟账户验证信号闭环。

**开发范围**：shadow account、shadow orders、shadow fills、偏差统计。

**交付物**：
- shadow execution ledger。
- signal vs shadow fill 报告。
- slippage 模拟。

**验收标准**：可以看到如果执行会发生什么，但不会发真实委托。

**测试计划**：模拟成交测试；行情缺失测试；账户状态一致性测试。

**边界**：sandbox only。

---

### V4.2 — Broker Adapter Contract & Sandbox

**目标**：定义外部交易适配器合约和沙箱实现，为未来受控接入做准备。

**开发范围**：adapter interface、sandbox adapter、错误码、回执、重试策略。

**交付物**：
- adapter contract。
- sandbox adapter。
- order/fill schema。
- error handling doc。

**验收标准**：沙箱能模拟委托、撤单、成交、失败；真实适配器默认禁用。

**测试计划**：沙箱订单生命周期测试；错误码测试；超时测试。

**边界**：不启用真实适配器。

---

### V4.3 — Order Preview/Rebalance/Approval

**目标**：把信号转成可审阅的调仓预案，而不是直接执行。

**开发范围**：rebalance diff、order preview、审批状态、人工确认记录。

**交付物**：
- order preview report。
- rebalance diff。
- approval record。
- blocked reason。

**验收标准**：所有订单预案都能说明来源、数量、价格、风险和拒绝原因；未经确认不能继续。

**测试计划**：组合差异测试；审批状态测试；拒绝路径测试。

**边界**：manual required。

---

### V4.4 — Kill Switch / Risk Sentinel

**目标**：建立风险哨兵和熔断机制，统一管控数据异常、账户异常、亏损异常和执行异常。

**开发范围**：risk sentinel、kill switch、异常规则、告警记录。

**交付物**：
- risk rules。
- sentinel status。
- kill switch flag。
- incident event log。

**验收标准**：数据延迟、账户异常、连续失败、亏损触发时能阻断后续动作。

**测试计划**：异常注入测试；阈值边界测试；恢复流程测试。

**边界**：熔断优先级高于所有策略信号。

---

### V4.5 — Human Approval Workflow

**目标**：建立人工审批工作流，把关键动作从系统自动化中隔离出来。

**开发范围**：审批人、审批记录、审批过期、撤回、拒绝、二次确认。

**交付物**：
- approval workflow schema。
- approval CLI/UI。
- approval audit。
- pending approval dashboard。

**验收标准**：没有审批记录不能进入下一阶段；审批可追溯、可过期、可拒绝。

**测试计划**：审批状态机测试；过期测试；重复审批测试。

**边界**：manual required。

---

### V4.6 — Live Audit/Rollback/Incident

**目标**：建立审计、回滚和事故复盘框架，保证关键行为可追溯。

**开发范围**：audit trail、incident report、rollback plan、postmortem 模板。

**交付物**：
- audit event schema。
- rollback manifest。
- incident report generator。
- postmortem report。

**验收标准**：每个关键状态变化都能追溯到输入、操作者、时间和结果。

**测试计划**：审计完整性测试；回滚 manifest 测试；事故报告生成测试。

**边界**：只做审计与回滚框架，不替代人工判断。

---

### V4.7 — MiniQMT Adapter Hardening

**目标**：为 MiniQMT 适配器建立沙箱加固和兼容性测试，不直接启用真实账户。

**开发范围**：接口封装、连接检测、错误分类、沙箱映射、权限检查。

**交付物**：
- MiniQMT adapter facade。
- sandbox compatibility layer。
- connection health check。
- error taxonomy。

**验收标准**：真实连接默认关闭；沙箱能覆盖主要接口形态。

**测试计划**：mock 连接测试；异常返回测试；权限缺失测试。

**边界**：sandbox only。

---

### V4.8 — Capital Safety Boundary

**目标**：明确资金安全边界，防止任何自动流程越权。

**开发范围**：权限分级、资产校验、最大风险敞口、人工确认规则、禁止动作列表。

**交付物**：
- capital safety policy。
- permission levels。
- exposure guard。
- forbidden action list。

**验收标准**：任何资金相关动作都有硬门禁；默认状态不能触发外部执行。

**测试计划**：权限测试；越权测试；异常资产测试。

**边界**：manual required。

---

### V4.9 — Controlled Live Readiness Report

**目标**：生成实盘就绪报告，而不是直接进入实盘。

**开发范围**：数据、策略、执行、风控、审计、人工流程的成熟度评估。

**交付物**：
- readiness checklist。
- gap report。
- go/no-go recommendation。
- manual approval package。

**验收标准**：报告能明确哪些条件未达标；即使达标也只输出建议，不执行。

**测试计划**：checklist 完整性测试；缺项报告测试。

**边界**：readiness report only。

---

## V5.x — Real Data Platform

### V5.0 — Data Source Registry

**目标**：建立统一数据源注册表，解决数据来源混乱和不可追溯问题。

**开发范围**：provider registry、数据类型、优先级、可用性、限流、成本、质量等级。

**交付物**：
- provider registry。
- provider matrix。
- data source health schema。
- CLI 查询。

**验收标准**：每个数据请求能说明来自哪个 provider；不可用时有原因。

**测试计划**：provider 注册测试；优先级测试；不可用 provider 测试。

**边界**：不允许 fallback 伪造数据。

---

### V5.1 — AkShare/BaoStock Provider

**目标**：接入免费 A 股数据源，作为初期真实数据基础。

**开发范围**：日线、基础行情、复权、股票列表、指数数据。

**交付物**：
- AkShare provider。
- BaoStock provider。
- 字段标准化。
- provider audit report。

**验收标准**：数据能落到统一 contract；失败明确报错；时间戳和来源可见。

**测试计划**：字段映射测试；空返回测试；网络失败测试。

**边界**：免费源不稳定时必须显式失败。

---

### V5.2 — Realtime Quote Ingest

**目标**：建立实时行情接入，为盘中监控和实时报告提供基础。

**开发范围**：行情快照、成交额、涨跌幅、盘口可选、延迟检测。

**交付物**：
- realtime quote schema。
- ingest runner。
- latency monitor。
- snapshot storage。

**验收标准**：每条实时数据带 source、timestamp、latency；超过阈值标记 stale。

**测试计划**：延迟测试；断流测试；字段缺失测试。

**边界**：实时行情只用于研究/监控，不直接执行。

---

### V5.3 — Minute/Daily Bar Storage

**目标**：建立分钟线和日线统一存储，支持回测、盘中和盘后分析。

**开发范围**：bar schema、分区存储、增量更新、去重、复权标记。

**交付物**：
- minute bar store。
- daily bar store。
- update CLI。
- integrity checker。

**验收标准**：同一股票同一时间只有一条有效 bar；缺口可检测。

**测试计划**：重复写入测试；断点续传测试；复权字段测试。

**边界**：数据异常不自动修补为假数据。

---

### V5.4 — Data Quality Gate

**目标**：让所有报告和回测先过数据质量门禁。

**开发范围**：完整性、时效性、异常价格、异常成交额、停牌、缺失字段。

**交付物**：
- quality gate rules。
- data quality report。
- block/warn policy。
- quality CLI。

**验收标准**：质量不达标时，报告必须提示或阻断；不能静默继续。

**测试计划**：缺失数据测试；异常值测试；停牌样例测试。

**边界**：质量门禁优先于策略输出。

---

### V5.5 — No-Fallback Data Contract

**目标**：彻底禁止 demo/fallback 数据进入正式报告或策略。

**开发范围**：数据 contract、fallback 检测、demo 标记、失败报告。

**交付物**：
- no-fallback policy。
- source lineage required。
- failure reason schema。
- fallback detector。

**验收标准**：任何正式输出都必须有真实 source；拉不到数据必须失败并展示原因。

**测试计划**：模拟 provider 失败；demo 数据注入测试；报告门禁测试。

**边界**：测试环境 demo 必须显式标记 test_only。

---

### V5.6 — Data Lineage/Manifest/Audit

**目标**：为数据建立血缘、manifest 和审计链条。

**开发范围**：数据批次、来源、生成时间、字段映射、处理步骤、消费者记录。

**交付物**：
- data manifest。
- lineage graph lite。
- audit JSONL。
- report data appendix。

**验收标准**：任何报告能追溯到具体数据批次和 provider。

**测试计划**：manifest 完整性测试；跨步骤 lineage 测试。

**边界**：不追求复杂数据湖，先做本地可追溯。

---

### V5.7 — Market Calendar Engine

**目标**：建立 A 股交易日历和交易时段判断，减少日期错误。

**开发范围**：交易日、节假日、半日市、盘前/盘中/盘后时段、最近交易日。

**交付物**：
- market calendar module。
- session classifier。
- latest trading day resolver。
- calendar CLI。

**验收标准**：相对日期能解析成明确交易日；非交易日不误跑盘中任务。

**测试计划**：节假日测试；周末测试；盘中时段测试。

**边界**：日历不确定时必须提示。

---

### V5.8 — Data Health Dashboard

**目标**：把数据源状态、延迟、失败原因可视化。

**开发范围**：provider status、freshness、error history、质量评分。

**交付物**：
- data health API。
- Dashboard 数据健康页。
- provider failure card。
- freshness badge。

**验收标准**：用户能看到为什么页面没有数据，而不是卡死或空白。

**测试计划**：API 测试；UI 字段测试；失败状态渲染测试。

**边界**：只读展示，不自动切换到不可信数据。

---

### V5.9 — Paid Provider Readiness

**目标**：为未来付费数据源预留接口和评估框架。

**开发范围**：provider capability、成本、限流、权限、字段覆盖、迁移策略。

**交付物**：
- paid provider interface spec。
- capability matrix。
- migration checklist。
- cost/rate-limit config。

**验收标准**：新增付费源不影响现有免费源 contract；字段差异可比较。

**测试计划**：mock paid provider；字段覆盖测试；限流测试。

**边界**：不购买、不接入真实付费账号。

---

## V6.x — Research Automation

### V6.0 — Research Skill Runtime

**目标**：建立投研 skill 运行时，让盘前、盘中、盘后、个股、行业分析可标准化执行。

**开发范围**：skill schema、输入输出、依赖数据、运行状态、报告格式。

**交付物**：
- skill runtime。
- skill registry。
- run manifest。
- Markdown/HTML/JSON 输出。

**验收标准**：至少支持盘前、盘中、个股分析三个 skill；输出结构统一。

**测试计划**：skill 注册测试；运行失败测试；报告格式测试。

**边界**：skill 只输出研究结论，不执行交易。

---

### V6.1 — Strategy Template Registry

**目标**：建立策略模板注册表，让策略开发可复用、可审计。

**开发范围**：趋势、反转、行业轮动、多因子、事件驱动模板。

**交付物**：
- strategy template schema。
- template registry。
- 参数约束。
- 示例策略。

**验收标准**：模板能生成策略实例；参数越界被拒绝。

**测试计划**：模板实例化测试；参数校验测试。

**边界**：模板不是实盘策略。

---

### V6.2 — Backtest Engine Integration

**目标**：整合回测引擎，支持策略统一回测和报告输出。

**开发范围**：回测输入、调仓频率、手续费、滑点、基准、股票池。

**交付物**：
- backtest runner。
- backtest config。
- result schema。
- equity curve/report。

**验收标准**：同一配置可复现；结果包含收益、回撤、Sharpe、换手。

**测试计划**：固定样例回测；费用影响测试；复现测试。

**边界**：回测不等于可交易。

---

### V6.3 — Walk Forward/OOS/Anti-overfit

**目标**：建立反过拟合评估，让策略必须通过 OOS 和 walk-forward。

**开发范围**：训练/测试切分、滚动窗口、参数冻结、样本外报告。

**交付物**：
- walk-forward runner。
- OOS report。
- overfit score。
- parameter stability report。

**验收标准**：策略不能只展示全样本；必须展示 OOS 和失败窗口。

**测试计划**：过拟合样例；稳定策略样例；窗口切分测试。

**边界**：不因单次高收益自动晋级。

---

### V6.4 — Portfolio Backtest/Benchmark

**目标**：支持组合级回测和多基准比较。

**开发范围**：组合权重、再平衡、行业暴露、基准对比、同池等权。

**交付物**：
- portfolio backtest。
- benchmark comparison。
- exposure report。
- attribution report。

**验收标准**：策略必须和同池等权、指数基准比较；暴露可解释。

**测试计划**：权重归一测试；基准对齐测试；收益归因测试。

**边界**：组合结果只作为研究。

---

### V6.5 — Strategy Report Generator

**目标**：自动生成可读策略报告，减少只看指标不看逻辑的问题。

**开发范围**：策略假设、数据来源、绩效、风险、失败窗口、适用场景。

**交付物**：
- report generator。
- HTML/Markdown/JSON 输出。
- chart manifest。
- conclusion template。

**验收标准**：报告包含数据血缘、方法、结论、风险，不只是一张收益图。

**测试计划**：报告字段完整性测试；空结果测试；图表产物测试。

**边界**：报告不输出确定性收益承诺。

---

### V6.6 — Factor Mining Agent

**目标**：建立因子挖掘 Agent，让 LLM/规则系统持续提出、实现、评估候选因子。

**开发范围**：候选生成、代码实现、评估、拒绝、归档、改进循环。

**交付物**：
- factor mining workflow。
- candidate queue。
- auto evaluation hook。
- mining report。

**验收标准**：Agent 能生成候选但必须经过评估门禁；不能直接进入交易。

**测试计划**：候选生成测试；不可计算拒绝测试；评估集成测试。

**边界**：不允许“LLM 说好就采用”。

---

### V6.7 — News/Policy/Event Research

**目标**：建立新闻、政策、公告事件研究流水线，服务盘前和盘中分析。

**开发范围**：新闻抓取、政策解析、产业链映射、个股影响、排除理由。

**交付物**：
- event research pipeline。
- source citation/data lineage。
- impact scoring。
- daily research report section。

**验收标准**：报告能说明消息来源、影响链条、利好分支、排除理由。

**测试计划**：空新闻测试；重复新闻聚合测试；事件分类测试。

**边界**：新闻结论必须可追溯，不做无来源猜测。

---

### V6.8 — A-share Sector Rotation

**目标**：建立 A 股行业轮动研究模块，辅助判断主线扩散和切换。

**开发范围**：行业强弱、资金流、成交占比、趋势状态、轮动信号。

**交付物**：
- sector score。
- rotation dashboard data。
- leader/laggard report。
- semiconductor focus overlay。

**验收标准**：能解释行业为什么强弱；半导体主线有细分分支视图。

**测试计划**：行业分类测试；强弱排序测试；缺失行业数据测试。

**边界**：行业轮动不直接下单。

---

### V6.9 — Strategy Promotion Board

**目标**：建立策略晋级看板，管理从 research 到 paper 的晋级。

**开发范围**：策略评分、晋级条件、观察期、失败原因、候选队列。

**交付物**：
- promotion board data。
- strategy scorecard。
- candidate status。
- rejection report。

**验收标准**：每个策略为何晋级或拒绝可解释；不能绕过评估门禁。

**测试计划**：评分卡测试；状态流转测试；失败策略样例。

**边界**：晋级到 paper 仍需配置确认。

---

## V7.x — Product UI / Ops

### V7.0 — Modern Frontend Dashboard

**目标**：建立现代化本地前端，解决页面卡死、空白、不可解释失败的问题。

**开发范围**：统一布局、状态卡片、报告入口、任务入口、错误展示。

**交付物**：
- modern dashboard shell。
- status cards。
- navigation。
- error boundary。

**验收标准**：页面能解释数据/任务/报告失败原因；不再只显示空白。

**测试计划**：HTML/API smoke test；错误状态渲染测试。

**边界**：先本地 127.0.0.1。

---

### V7.1 — Data Status/Provider Failure UI

**目标**：把数据源失败原因展示给用户，避免“点了没反应”。

**开发范围**：provider card、失败原因、最后成功时间、建议处理。

**交付物**：
- provider status UI。
- freshness badge。
- failure explanation panel。
- retry guidance。

**验收标准**：每个数据缺失都能在 UI 中看到来源和原因。

**测试计划**：失败状态渲染；stale 状态；无 provider 状态。

**边界**：UI 不自动伪造数据。

---

### V7.2 — AgentOps Control Tower

**目标**：建立 AgentOps 控制塔，让用户看到 Agent 会话、任务、产物和当前状态。

**开发范围**：Agent Console、任务队列、实时回答流、诊断流、产物链接。

**交付物**：
- Agent Console 页面。
- answer_delta SSE。
- diagnostic panel。
- session history。

**验收标准**：用户能在前端看到 Hermes Agent/Claude Code 的实时回答正文，而不是日志 tail。

**测试计划**：session API 测试；answer_delta 渲染测试；取消会话测试。

**边界**：日志只能辅助，不能替代主回答。

---

### V7.3 — Task Queue/Run History/Logs

**目标**：建立任务队列、运行历史和日志中心，让后台任务可追溯。

**开发范围**：task list、run detail、logs、status、duration、exit code。

**交付物**：
- task queue UI。
- run history API。
- log viewer。
- artifact links。

**验收标准**：每次任务有状态、日志、产物、失败原因。

**测试计划**：任务列表测试；日志截断测试；失败任务测试。

**边界**：这是诊断中心，不是回答主面板。

---

### V7.4 — Roadmap Progress UI

**目标**：把固定版本路线图做成可展开、可追踪、可验收的产品进度页。

**开发范围**：版本详情、进度、依赖、验收、当前阻断、下一步。

**交付物**：
- roadmap detail UI。
- expandable version cards。
- status/progress badges。
- next action hints。

**验收标准**：每个版本显示详细规划，不只是 objective。

**测试计划**：关键字段渲染测试；展开/折叠测试；API 字段测试。

**边界**：路线图由本文档定义，Hermes 不自行发挥。

---

### V7.5 — Report Center

**目标**：建立报告中心，集中管理盘前、盘中、盘后、个股、策略报告。

**开发范围**：报告索引、筛选、预览、下载、数据血缘展示。

**交付物**：
- report index。
- report viewer。
- metadata panel。
- export links。

**验收标准**：用户能按日期、类型、标的查找报告；报告来源清晰。

**测试计划**：索引测试；空报告测试；HTML 报告加载测试。

**边界**：不生成未经验证的数据报告。

---

### V7.6 — Risk Dashboard

**目标**：建立风险仪表盘，展示策略、数据、组合、任务和系统风险。

**开发范围**：风险指标、告警、熔断状态、异常任务、数据质量风险。

**交付物**：
- risk overview。
- alert list。
- kill switch status。
- risk history。

**验收标准**：用户能快速看到系统是否安全、为何阻断。

**测试计划**：风险状态渲染；告警列表；历史记录。

**边界**：风险面板不提供绕过按钮。

---

### V7.7 — Paper Trading Dashboard

**目标**：展示 paper trading 的信号、组合、模拟成交和执行质量。

**开发范围**：paper portfolio、orders、fills、PnL、slippage、benchmark。

**交付物**：
- paper dashboard。
- performance cards。
- execution quality report。
- paper history。

**验收标准**：paper 结果和研究信号可对齐；执行质量可见。

**测试计划**：paper 数据渲染；空账户；异常成交。

**边界**：paper 不等于 live。

---

### V7.8 — User Feedback/Task Intake UI

**目标**：让用户从前端提交反馈和任务，而不是只改文件或命令行。

**开发范围**：反馈表单、任务草稿、优先级、状态跟踪、人工确认。

**交付物**：
- task intake UI。
- feedback queue。
- status tracking。
- task detail。

**验收标准**：用户提交的问题能进入任务系统并被追踪。

**测试计划**：表单提交；字段校验；任务状态渲染。

**边界**：用户提交不等于自动执行高风险动作。

---

### V7.9 — One-click Local Ops

**目标**：提供本地一键启动、停止、健康检查，降低运维门槛。

**开发范围**：start/stop scripts、health check、port check、process status。

**交付物**：
- local ops CLI。
- start dashboard script。
- stop script。
- diagnostics report。

**验收标准**：用户能一键启动 Dashboard 和关键服务；失败原因明确。

**测试计划**：端口占用；重复启动；缺依赖。

**边界**：本地运维，不做公网部署。

---

## V8.x — Multi-Agent Engineering

### V8.0 — Agent Role Registry

**目标**：定义 Agent 角色、权限、能力边界和适用任务。

**开发范围**：角色注册、能力标签、权限级别、默认 backend、禁用动作。

**交付物**：
- agent role registry。
- role schema。
- capability matrix。
- permission policy。

**验收标准**：每个 Agent 能做什么、不能做什么都可查询。

**测试计划**：角色加载；权限边界；未知角色。

**边界**：角色定义不赋予越权能力。

---

### V8.1 — Agent Router

**目标**：把任务路由给合适的 Agent，而不是所有任务都走同一个后端。

**开发范围**：任务分类、路由规则、fallback policy、成本/能力权衡。

**交付物**：
- routing engine。
- routing rules。
- backend selection report。
- rejection reason。

**验收标准**：任务能解释为什么交给某个 Agent；不可执行任务会拒绝。

**测试计划**：路由样例；无可用 backend；高风险任务阻断。

**边界**：路由不绕过人工门禁。

---

### V8.2 — Auto Bugfix Loop

**目标**：建立自动 bugfix 循环，让测试失败能生成修复任务、执行、复测、记录。

**开发范围**：失败捕获、bug ticket、修复计划、patch、复测、回滚。

**交付物**：
- bugfix loop。
- failure parser。
- patch report。
- retry policy。

**验收标准**：小型测试失败能自动形成修复闭环；多次失败会停止并报告。

**测试计划**：模拟测试失败；修复成功；修复失败停止。

**边界**：不得自动修改敏感配置。

---

### V8.3 — Regression Test Planner

**目标**：根据改动文件和影响范围自动选择回归测试。

**开发范围**：file-to-test map、test impact analysis、分层测试计划。

**交付物**：
- regression planner。
- test selection report。
- coverage hints。
- CI command generator。

**验收标准**：每次改动有对应测试建议；关键模块不漏测。

**测试计划**：映射规则测试；未知文件测试；多模块改动。

**边界**：测试选择不能替代最终验收。

---

### V8.4 — GitHub Issue/PR Pipeline

**目标**：建立 GitHub issue/PR 流水线，支持任务、分支、PR、审查和同步。

**开发范围**：issue intake、branch naming、PR creation、review checklist、sync report。

**交付物**：
- GitHub sync module。
- issue template。
- PR template。
- merge gate policy。

**验收标准**：版本完成后能同步到 GitHub；PR 有说明、测试和产物。

**测试计划**：dry-run GitHub sync；缺 token；dirty tree。

**边界**：自动合并需单独门禁。

---

### V8.5 — Documentation Generator

**目标**：自动生成和维护用户说明、开发说明、API 文档和版本报告。

**开发范围**：doc templates、change summary、API extraction、release notes。

**交付物**：
- doc generator。
- version docs。
- command reference update。
- user guide snippets。

**验收标准**：功能完成后有用户可读说明；命令和 API 不失配。

**测试计划**：文档生成测试；缺字段测试；链接检查。

**边界**：文档不能声称未实现功能。

---

### V8.6 — Release Manager

**目标**：建立发布管理，控制版本号、变更摘要、验收状态和回滚包。

**开发范围**：version bump、release checklist、artifact packaging、rollback notes。

**交付物**：
- release manager。
- release manifest。
- changelog。
- rollback package。

**验收标准**：每次发布可追溯到 commit、测试、产物和风险。

**测试计划**：版本号测试；manifest 测试；缺测试阻断。

**边界**：发布不等于部署到公网。

---

### V8.7 — Self-Diagnostics

**目标**：让 Hermes 自己诊断环境、依赖、任务、数据和 Agent 后端状态。

**开发范围**：env check、dependency check、backend check、data check、task consistency。

**交付物**：
- self-diagnostics CLI。
- diagnostics report。
- fix hints。
- dashboard diagnostics card。

**验收标准**：常见故障能给出明确原因和建议。

**测试计划**：缺依赖；错误路径；backend 不可用。

**边界**：诊断建议不自动执行危险修复。

---

### V8.8 — Cost/Token/Backend Policy

**目标**：管理不同 Agent backend 的成本、token、可用性和任务适配。

**开发范围**：backend policy、cost estimate、token budget、fallback rules。

**交付物**：
- backend policy config。
- cost report。
- budget guard。
- model selection explanation。

**验收标准**：系统能解释为什么使用某个 backend；超预算会阻断或降级。

**测试计划**：预算阈值；不可用 backend；fallback 规则。

**边界**：fallback 不能改变安全边界。

---

### V8.9 — Continuous Improvement Engine

**目标**：建立持续改进循环，把失败、反馈、表现退化自动转成改进任务。

**开发范围**：反馈采集、失败聚类、改进建议、优先级、任务生成。

**交付物**：
- improvement engine。
- feedback-to-task mapper。
- priority scoring。
- improvement report。

**验收标准**：用户反馈和系统失败能形成可追踪改进项。

**测试计划**：反馈分类；重复合并；优先级排序。

**边界**：改进任务仍需走正常验收。

---

## V9.x — Backlog / Future

### V9.0 — Cloud/Local Hybrid Runner

**目标**：研究云端与本地混合执行架构，解决本地资源和可用性问题。

**范围**：只做方案评估、接口边界、安全评估和成本估算。

**交付物**：hybrid runner design、security assessment、cost model。

**验收标准**：明确是否值得做、何时做、风险是什么。

**边界**：backlog，不实现生产能力。

---

### V9.1 — Distributed Backtest

**目标**：评估分布式回测能力，用于大规模参数和股票池回测。

**范围**：任务拆分、结果合并、缓存、资源调度设计。

**交付物**：distributed backtest design、benchmark plan。

**验收标准**：明确本地单机瓶颈和分布式收益。

**边界**：backlog。

---

### V9.2 — Multi-account Governance

**目标**：评估多账户治理能力，包括权限、账户隔离和审计。

**范围**：账户模型、权限、风险隔离、审计设计。

**交付物**：multi-account governance design。

**验收标准**：明确多账户前置条件和安全边界。

**边界**：backlog，不接真实账户。

---

### V9.3 — External Notification Center

**目标**：评估企业微信、邮件、Webhook 等外部通知中心。

**范围**：通知渠道、模板、频率限制、失败重试、隐私边界。

**交付物**：notification center design、channel matrix。

**验收标准**：明确哪些通知可自动发、哪些必须人工确认。

**边界**：backlog。

---

### V9.4 — Enterprise-grade Audit

**目标**：评估企业级审计能力，包括不可篡改日志、权限、合规留痕。

**范围**：审计存储、签名、权限、归档、查询。

**交付物**：enterprise audit design、gap report。

**验收标准**：明确与当前 JSONL 审计的差距和升级成本。

**边界**：backlog。
