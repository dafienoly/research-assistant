# Hermes VNext 开源补强开发日志

## 2026-07-11 — PR-00 Current State Reconciliation

### 完成的真实改动

- 完整读取 Goal 和 `hermes_vnext_open_source_upgrade_implementation_plan_2026-07-10.md`；
- 审计 Git、目录、模块、CLI、API、UI、数据库/迁移、Broker 调用、mock/fallback、依赖和真实数据产物；
- 创建 `docs/vnext/current_workspace_status.md`；
- 创建机器可读 `artifacts/vnext/current_workspace_status.json`；
- 创建 `artifacts/vnext/dependency_graph.json`；
- 冻结 PR-00 Python/前端测试基线。

### 运行命令与结果

- `node .gitnexus/run.cjs status`：索引落后于当前提交；
- `node .gitnexus/run.cjs analyze`：GitNexus 1.6.6 因缺失 `tree-sitter-swift` 失败；
- GitNexus 全局/局部修复尝试：安装链卡在 onnxruntime 外部下载，已中止，未修改 Hermes 源码；
- VNext Python 专项：62 passed；
- 前端 Vitest：16 files / 27 tests passed；
- Vite build：passed，4,031 modules；
- oxlint：exit 0，legacy warnings remain。

### 数据结果

- 日线 5,738、估值 5,816、资金流 5,383、财务 5,473；
- miniQMT Probe 真实连接，账户/持仓可读，order channel disabled；
- 港股/海外代理 MISSING，实时/事件源 STALE，概念/行业 PARTIAL。

### 失败、外部阻塞与剩余风险

- GitNexus 当前索引工具不可刷新，状态报告不使用旧索引证明新提交调用图；
- Chrome Native Messaging Host 不可用，真实浏览器 console/click 仍阻塞；
- Telegram 未执行真实消息/回调；
- 核心契约、vectorbt、Event Truth、SBOM 等按状态矩阵进入下一阶段。

### 下一步

PR-01：实现七个 Hermes 自有契约、TargetPortfolioWeights、Approval hash/TTL/nonce/signature、ExecutionGuard 和 hash-chain append-only ledger。

## 2026-07-11 — PR-01 Contracts & Safety Invariants

### 完成的真实改动

- 新增严格 Pydantic 契约：`MarketDataEnvelope`、`ResearchSignal`、`TargetPortfolioWeights`、`OrderDraft`、`ApprovedOrderEnvelope`、`ExecutionEvent`、`ReviewRecord`；
- 新增 `QualityStatus`，避免修改 HIGH blast-radius 的 legacy `DataStatus`；
- 为受限/watch-only/proxy 标的和 ETF substitution 增加目标权重不变量；
- `OrderDraft` 增加 lineage、TTL 和规范化 SHA-256；
- Approval 增加 HMAC-SHA256、TTL、一次性 nonce、allowed mode 和 Modify 失效；
- Execution Service 改为只接受 `ApprovedOrderEnvelope`；
- 新增 ExecutionGuard、持久 nonce registry 和 hash-chain AuditJournal；
- Paper/Shadow CLI 拒绝裸订单和缺签名密钥；
- execution-status 合并最新只读 QMT Probe，并保持订单/撤单通道 DISABLED；
- 默认模式按新规范设为 PAPER，同时保持 `no_live_trade=true`、live disabled；
- 新增 schema 导出 CLI 和 `artifacts/vnext/schemas/`。

### 影响分析

- OrderDraft/SafetyContext/AuditJournal/Approval/ExecutionEngine：LOW（按 MEDIUM 兼容处理）；
- DataStatus：HIGH，因此未修改，新增独立 QualityStatus；
- VNextService.execution_status：HIGH，采用只增字段、缺失即 MISSING 的兼容变更并跑 API/日报回归。

### 测试与静态检查

- PR-01 全 VNext 回归：70 passed，0 failed；
- JUnit：`artifacts/vnext/test_runs/pr01_contracts_security.xml`；
- Python compileall：通过；
- ruff/mypy：当前 `.venv_quant` 未安装，记录为 PR-12 依赖/类型检查缺口；
- 独立安全 Probe：有效签名 PAPER 可进入模拟 broker，真实 broker 调用为 false；raw draft、nonce replay、Kill Switch、错误签名和 live mode 全部阻断；
- Approval audit hash chain：2 events，valid=true。

### 外部阻塞与剩余风险

- HERMES_APPROVAL_SIGNING_KEY 未配置时，系统明确返回 BLOCKED/APPROVED_UNSIGNABLE；
- 尚未完成跨进程 ledger 锁、Telegram webhook 回调和 Delay 重检；
- TargetPortfolioWeights 已有契约/不变量，但尚未进入真实领域主链；
- Fast/Event lanes 尚未实现。

### 下一步

PR-02/03：在保留现有真实数据恢复成果的基础上，补 immutable snapshot manifest、Provider/Fetcher/Router、conflict/alternative observation 和 point-in-time 包络。

## 2026-07-11 — PR-02/03 Data Recovery & Provider Layer

### 完成的真实改动

- `batch_daily`、`batch_fina`、`batch_valuation` 增加稳定 run ID、checkpoint/resume、逐标的批次 manifest、响应/持久行数、日期范围、内容哈希和错误记录；
- 写入改为原子落盘，并与已有历史合并，不截断请求区间外数据；
- 新增非破坏性 ZIP 备份/隔离恢复演练；
- 实现 Hermes 自有 OpenBB-inspired Provider/Fetcher/Registry/Router；
- 实现 Tushare、Local CSV、AkShare、腾讯、东方财富、MiniQMT 市场数据和可选 OpenBB Proxy 边界；
- 次级源永不提升为主源，冲突显式记录，所有路由 `silent_fallback_used=false`；
- HubSnapshotBuilder 的 Tushare 与本地读取全部接入 ProviderRouter；
- Provider schema 升级到 v1.1，修正实时源 `observed_at` 时间语义；
- 新增聚合不可变快照清单、数据缺口/新鲜度/审计导出 CLI 与产物。

### 影响分析

- GitNexus 将三个 legacy batch 函数均评为 HIGH：各有 2 个直接调用者，并进入全量初始化与 `hermes_cli.main`；
- 因此保留其参数和返回类型，仅把函数体委托给兼容的恢复执行器，并运行全部原 CLI/批处理测试；
- 新 Provider/恢复模块未进入旧索引，按未知风险保守处理；GitNexus 刷新仍受 `tree-sitter-swift` 缺失阻塞。

### 真实数据与演练结果

- 数据审计：日线 5,738、估值 5,816、资金流 5,383、财务 5,473、概念 16、行业 1；
- 缺口：资金流 147、财务 57、概念 364、行业 79，另缺 3 个主题/产业链标签文件；
- 新鲜度：legacy DataHub 总体 `stale` 且 `blocking=true`；
- 真实 Provider 快照：29/29 清单验证通过，snapshot ID 可重算一致，无静默 fallback；
- 真实恢复演练：688012.SH 返回/持久化 1,327 行，重跑命中 checkpoint，未二次请求；
- 演练发现并修复两种日期格式导致的重复行，修复前失败清单保留，修复后文件恢复 1,327 行且哈希通过；
- 备份恢复演练：5/5 文件恢复哈希一致，未覆盖生产目录。

### 测试和静态检查

- 数据管线 + Provider 专项：35 passed；
- 数据审计导出：1 passed；
- 备份恢复演练：1 passed；
- Provider point-in-time/冲突/不可变快照：10 passed；
- Python compileall：通过；
- pytest 默认 Windows Temp 权限失败，固定 `TMPDIR=/tmp` 与 `--basetemp` 后真实用例全部执行通过。

### 门禁与剩余风险

- `artifacts/vnext/data_audit_report.json` 为 `PARTIAL`；正式 ML、Shadow 与 OrderDraft 均 `BLOCKED`；
- 数据恢复未使用 mock、demo 或 fallback；
- OpenBB 本体未安装，Proxy 仅为默认关闭的 Sidecar Adapter；
- 资金流、财务、概念、行业和旧实时/事件新鲜度仍待真实采集器继续恢复。

### 下一步

PR-04/05：接入 TargetPortfolioWeights 主链、隔离 vectorbt Fast Lane、A 股 Event Truth Lane，并用同一快照与权重生成 reconciliation report。

## 2026-07-11 — PR-04/05 Target Weights, vectorbt & Event Truth

### 完成的真实改动

- 新增 TargetWeightPipeline、TopN 兼容 Adapter 和每日多资产 Adapter；
- restricted/watch-only/blocked 权重强制归零，ETF substitution 必须显式 lineage；
- Regime 现金预算和 Semi failure overlay 进入目标权重；无持仓快照时不生成 OrderDraft；
- vectorbt 1.1.0 安装到独立 `.venv_vectorbt`，生成精确版本锁和隔离配置；
- 新增只读 vectorbt Worker、边界 AST 审计、输入 manifest、参数扫描、成本压力、事件研究和 walk-forward；
- 新增 Hermes 自有 EventEngine、对象模型、Paper Event Gateway、OMS、机械风控和 A 股事件回放；
- 新增 Fast/Event reconciliation，强制相同 snapshot ID 与 target weights hash。

### 依赖与许可证事实

- 官方 PyPI 显示 vectorbt 1.1.0 支持 Python >=3.11,<3.15，当前独立环境为 Python 3.14.4；
- 当前许可证为 Apache-2.0 + Commons Clause，不按纯 Apache-2.0 处理；
- 仅条件批准研究用途，未装 Rust/full extras；核心 `.venv_quant` 未安装 vectorbt。

### 真实运行结果

- 目标簿：65% 投资、35% 现金，半导体 ETF 因 `SEMI_FAILURE` 归零，质量 BACKTEST_ONLY；
- Fast Lane：146 日、7 标的、18 参数场景、2 walk-forward folds、3 成本压力场景；vectorbt 1.1.0，网络/下载/Broker 均为 false；
- 第二 OOS fold 总收益 -6.03%，如实保留；
- Event Lane：1,332 events、41 orders、41 trades、0 外部 Gateway 调用；
- Event 缺官方 stk_limit/suspend_d/现金分红/复权因子，状态 PARTIAL；
- Reconciliation：相同 snapshot/weights，收益差 0.000183、回撤差 0.000215、期末差 182.60 元，容差内 OK；
- 即使对账 OK，`promotion_status=BLOCKED`，不能晋级 Paper/Live。

### 测试与验证

- PR-04/05 新增专项：12 passed；
- 实际产物验收：4 passed；
- CLI `vnext:fast-backtest`、`vnext:event-backtest`、`vnext:reconcile` 均 exit 0；
- Worker AST 无数据客户端、Broker、QMT 或 vn.py import；
- Event 单测覆盖 T+1、主板/科创/创业板/北交所/ST 涨跌停、权限、整手、容量和部分成交。

### 剩余风险

- 当前目标权重是 BACKTEST_ONLY，不能生成生产订单；
- 静态目标历史回放带明确 hindsight scenario warning，不作为无偏策略收益；
- Fast Lane event study 在当前 146 日窗口对 -2%/-5% 多资产回撤没有事件样本；
- Event Truth 需等待官方 limits/suspend/corporate action 数据补齐后才能从 PARTIAL 升级。

### 下一步

PR-06–09：把现有领域引擎完整接到目标权重主链，补组合优化/假分散、ML 治理和 Paper/Shadow/Telegram/miniQMT 持久闭环。

## 2026-07-11 — PR-06～12 主链收口与最终加固

### 完成的真实改动

- DomainDecision 将 Policy Put、Breadth、Style、Semi 与 Regime 统一进入目标权重；
- 六种受约束组合优化与 PCA/common-beta/假分散诊断实际运行；
- 208,106 条时点样本训练 Ridge 与 XGBRanker，XGB OOS RankIC 0.02042，但数据门禁阻断晋级；
- 真实 Tushare ETF 快照驱动 Paper/Shadow/LiveDryRun 安全认证，三种模式均验证签名、TTL、nonce 和 hash-chain；
- 稳定 API 增加 run/snapshot/reconciliation 明细，正式回测工件进入 UI Backtest 页面；
- 七层 Antifragile Review 消费统一快照、权重、审批和执行事件，输出 WATCH/BLOCKED；
- 建立五个隔离环境锁状态、NOTICE、许可证审查、CycloneDX SBOM 和 CI hardening gate；
- 移除 `mx_fetch_step.py` 的硬编码 API 凭据，改为环境变量并要求缺失显式失败；
- 生成 24 项 acceptance 证据包与面向 ChatGPT Pro 的迭代后实际状态报告。

### 验证结果

- 安全 35/35、单元 13/13、VNext 集成 78/78、受影响旧链回归 139/139、前端 12/12；
- Ruff、选定模块 mypy、compileall 通过；
- Python 137 个锁定组件和 npm 240 个生产依赖均为 0 已知漏洞；
- SBOM 197 components；CI 锁哈希/secret/Broker/mock-fallback gate 为 OK；
- 应用内浏览器 runtime 可加载但实例列表为空，真实 console/点击验收保持 BLOCKED。

### 最终门禁

- 数据审计仍 PARTIAL；Event Truth、Telegram/QMT、连续 Paper/Shadow 和浏览器交互仍在 `unresolved_items.md`；
- promotion 保持 BLOCKED，`no_live_trade=true`，没有真实 Broker 调用或订单发送。

## 2026-07-11 — 数据补拉自主续跑与覆盖审计纠偏

### 真实推进

- 检测到 01:43 后没有数据恢复进程，主动续跑而未等待用户再次触发；
- 将概念/行业主源改为具名 Tushare `ths_index` 与 `index_classify(src=SW2021)`，MX 只保留为显式 `PARTIAL` 备选观察；
- 概念从 16 行提升到 409 行，行业从 1 行提升到 511 行，均记录来源、质量、观测时间和内容哈希；
- 资金流精确补拉 352 个 U0 缺失代码：223 成功、73,062 行，129 上游空结果，0 失败；
- 财务精确补拉 57 个缺失代码：55 成功、2,027 行，2 个上游空结果，0 失败；
- 修正 VNext 数据审计：由文件总数改为 U0 股票代码集合交集，205 个历史/额外资金流文件不再掩盖 129 个当前缺失标的。

### 验证

- 数据流水线与 VNext 数据审计专项：28 passed；
- 当前 U0：日线 5,530/5,530、估值 5,530/5,530、资金流 5,401/5,530、财务 5,528/5,530；
- 数据仍为 `PARTIAL/STALE`，正式 ML、Shadow 和 OrderDraft 继续 `BLOCKED`，没有为空结果创建占位文件。

### 审计器与旧链回归修复

- 修复 Tushare Stock Provider 的覆盖起始日、空查询参数透传和返回 DataFrame 就地改型问题；40 个测试通过，5 个 live smoke 按标记跳过；
- 发现 Gate 3 会递归运行自己的测试，并被持续运行的 Hermes daemon 过宽 `pkill` 模式误杀；已排除自递归并改用同一虚拟环境的 `python` 入口，不停止自主 daemon、不降低断言；
- 旧链关联集 120 passed / 5 skipped，VNext 集成 78 passed；
- 最终 `leader:anti-cheat-audit --enable-gate5`：56 pass、0 fail、392 warn，状态 PASS；Gate 5 外部 LLM HTTP 403 仍按 warning 保留。
