# Hermes VNext Goal 总验收说明

更新时间：2026-07-10
适用版本：Hermes VNext（默认 `READ_ONLY`，`no_live_trade=true`）

## 结论

Hermes 已在保留原有因子、Alpha、Live、Approval、Risk、Paper/Shadow 和 QMT 框架的前提下，新增一条受治理的 VNext 能力链：

```text
真实数据与新鲜度门禁
  → 指数箱体 / 政策托底代理 / 广度背离 / 风格轮动
  → 半导体主线状态机
  → Regime Router
  → 多资产组合与假分散诊断
  → ML 因子筛选 / 横截面 score-rank
  → Paper / Shadow / Live Dry-run 草案
  → Telegram 审批状态
  → miniQMT 只读探测（真实委托硬阻断）
  → 反脆弱复盘和结构化训练样本
  → API / 12 页控制台 / Markdown 报告
```

VNext 不改变原系统的 `factor_engine.py`、因子注册表、IC/ICIR、Walk-Forward、审批、Kill Switch 等既有核心。新增功能集中在 `commands/factor_lab/vnext/`，可通过删除路由/CLI 入口和关闭配置整体回滚。

## 交付清单

### 代码

- `commands/factor_lab/vnext/contracts.py`：统一状态、可交易性、Regime、主线、复盘决策契约。
- `data_quality.py`：多资产 Universe Registry、文件真实性/字段/新鲜度门禁。
- `snapshot.py`：只使用已配置 Tushare 和明确本地文件构造真实快照；任何失败都记为 MISSING/STALE/PARTIAL，不静默换源。
- `market.py`：固定/动态指数箱体、政策托底代理、广度背离、风格轮动矩阵。
- `semiconductor.py`：12 状态半导体主线状态机。
- `regime.py`：8 状态 Regime Router 与风险/半导体/防守/现金预算。
- `portfolio.py`：20/60/120 日相关性、下行相关、回撤重叠、风险贡献、边际 Sharpe/回撤、科技/半导体 beta、假分散。
- `ml.py`：RankIC 因子筛选、Ridge/ElasticNet/RandomForest/MLP 可解释横截面排序、模型卡、版本、OOS、哈希模型产物；不输出 buy/sell。
- `execution.py`：交易模式状态机、PaperBroker、ShadowBroker、MiniQMTReadOnlyBroker、QMTProbeBroker、不可实盘的 MiniQMTLiveBroker、Telegram 审批、审计日志和全量安全门禁。
- `trading.py`：Paper/Shadow 单次和连续循环。
- `backtest.py`：1/3/5 日假设验证、固定/动态阈值比较、成本/滑点/冲击/频率/多 Regime 稳健性。
- `datasets.py`：从真实 Tushare 指数/ETF 和本地全 A 日线构建政策假设、市场广度与 ML 点时数据集；不做跨源 fallback。
- `review.py`：反脆弱归因、KEEP/TUNE/DOWNGRADE/RETIRE/ESCALATE/WATCH、结构化训练样本。
- `service.py` / `store.py` / `report.py` / `cli.py`：编排、原子产物、API 合约、报告和 CLI。
- `commands/factor_lab/api_server/routes_vnext.py`：VNext API 与审批状态接口。
- `commands/frontend/src/pages/vnext/`：12 页 Hermes 投研交易控制台。

### 配置

- `configs/vnext/index_box.yaml`
- `configs/vnext/universe.yaml`
- `configs/vnext/portfolio.yaml`
- `configs/vnext/ml.yaml`
- `configs/vnext/execution.yaml`
- `configs/vnext/system.yaml`（`HERMES_VNEXT_ENABLED=false` 可整体禁用 VNext，旧系统路由不受影响）

### 测试

`commands/tests/test_vnext.py` 与各模块同名测试覆盖数据缺失/陈旧、受限板块、ETF substitution、策略代理、状态机、Regime 降级、假分散、边际 Sharpe、ML 输出边界/弱 OOS 降级、Paper/Shadow、Telegram、Kill Switch、no-live、安全 SELL、反脆弱复盘、固定/动态回测、非有限 JSON 和 API。

## 20 个验收问题

### 1. 当前系统从哪里升级到了哪里？

从“规则多因子 TopN + 报告/审批/Paper 雏形”升级到“半导体进攻主线 + 多资产 Regime 风控 + 可解释 ML 排序 + Paper/Shadow/Telegram/miniQMT 安全闭环 + 日常控制台”。原有多因子链仍是研究底座，VNext 是增强和治理层，不是重写。

### 2. 哪些模块复用了原系统？

复用既有 Tushare Client、日线/估值/资金流目录、因子与 Alpha 研究框架、组合/Paper/Shadow 产物、QMT HTTP Client、FastAPI 中间件、统一响应、React/Vite/Ant Design 前端、Kill Switch 和已有审批思想。

### 3. 哪些模块是新增？

新增多资产注册表、真实性/新鲜度门禁、Policy Put 代理、动态箱体、广度背离、风格轮动矩阵、半导体主线状态机、Regime Router、组合假分散/边际贡献、通用 ML 排序、交易模式状态机、Telegram 审批记录、不可实盘的 live-ready broker 外壳、反脆弱复盘、VNext API/CLI/报告和 12 页控制台。

### 4. 是否仍然保持 no_live_trade？

是。`configs/vnext/execution.yaml` 固定 `no_live_trade: true`；`MiniQMTLiveBroker.no_live_trade` 和 `live_enabled` 是类级安全不变量，`submit()` 始终返回 `BLOCKED/no_live_trade_safety_invariant`，没有调用 `client.place_order()` 的代码路径。

### 5. 是否可能绕过审批？

本轮实现不能。UI 审批接口只更新审批记录并返回 `execution_triggered=false`；修改订单后 `requires_reapproval=true`；watch-only 或 Kill Switch 订单不能 Approve；Live 模式也不可达。

### 6. miniQMT 当前处于什么状态？

只读/探测和外围协议已就绪。默认未配置或连接失败会显示 MISSING/PARTIAL；订单、撤单和成交通道均显示 DISABLED。CLI `broker:qmt-probe` 只调用只读健康、账户和持仓接口。

### 7. Telegram 审批如何工作？

每个订单草案先获得 `approval_id`，审批记录包含订单、理由、Regime、半导体状态、策略来源、模型分数、组合影响、新鲜度、账户权限、仓位变化、风险、Kill Switch、ETF 替代和 miniQMT 模式。支持 Approve/Reject/Modify/Delay；审批动作不触发 broker。

### 8. Paper / Shadow 如何运行？

`trading:paper-run` 和 `trading:shadow-run` 读取带 `order` 与 `safety` 的真实草案 JSON，通过 `PaperShadowLoop` 运行。Paper 只写模拟成交；Shadow 只记录计划，不发单。`--cycles` / `--interval` 可连续运行；默认 1 个周期。

### 9. 半导体主线状态机如何判断？

输入相对强度、ETF 成交、科技锚点、分支广度、政策代理、派发风险、回撤压力和流动性支持，输出 12 个状态之一、置信度、evidence、missing_evidence、转移原因、优先工具和动作偏置。输入不足时降级到 `SEMI_DORMANT/watch_only`，不会用默认乐观值冒充确认。

### 10. 政策托底假设如何量化？

只使用 `index_lower_proximity`、指数日内收回、半导体/科技相对强度、ETF 异常成交、科技中军承接和广度背离等代理。输出 `policy_support_proxy_score`，明确声明它不是“国家队出手”的直接观测。

### 11. 指数箱体假设是否被验证？

代码同时计算用户固定箱体和 60/120 日低高点、20/80 分位动态箱体，并提供固定/动态阈值事件回测比较。固定阈值始终标注为待样本外验证的用户假设；没有足够熊市/震荡/流动性冲击样本时报告必须显示 PARTIAL 与样本偏差警告。

### 12. ML/DL 模型做了什么，没有做什么？

实现 RankIC 因子筛选、冗余过滤、Ridge/ElasticNet 基线，以及可选 RandomForest/MLP；预留 LightGBM/XGBoost/CatBoost/序列表征生命周期。输出 score/rank/confidence/attribution/model version/training window/OOS/risk warning。模型没有 buy/sell 输出、没有 broker 依赖、不能绕过组合/风控/审批。

### 13. 组合 Sharpe 如何计算？

由真实资产日收益按归一化权重合成，年化均值/波动计算 Sharpe；对每个资产做小权重扰动计算边际 Sharpe，并同时输出组合波动、最大回撤、风险贡献和边际回撤。

### 14. 如何识别假分散？

同时检查 60 日平均绝对相关、0.75 以上高相关对、权重 HHI/有效资产数、科技 beta、半导体 beta。设备、PCB、光模块、材料等若共同暴露于同一科技/半导体 beta，会触发 `false_diversification_warning`。

### 15. 如何做反脆弱复盘？

每次事件按 Regime、主线、政策代理、箱体、广度、轮动、策略、因子、ML、买点、仓位、风险执行、成交和数据质量评分；区分市场 beta、半导体 beta 与剩余 alpha，输出六类治理结论并把亏损写为结构化训练样本。

### 16. 回测是否仍然可能有牛市样本偏差？

可能。验证器显式要求 BULL/BEAR/RANGE_BOUND/LIQUIDITY_SHOCK 四类覆盖，并在缺少任一类时给出 `sample_bias_warning=true`。漂亮曲线、单一 2025-2026 样本或单一 Sharpe 不构成晋级证据。

### 17. 哪些数据缺失会导致降级？

指数历史、ETF 日线/成交、市场广度、科技锚点、资产收益、真实持仓、账户权限、涨跌停、停牌/ST、流动性、资金/持仓同步、Telegram 配置、QMT 连接及事件数据缺失均会降级；执行关键项缺失直接 blocked。

### 18. 如何证明没有 mock/fallback 冒充真实数据？

VNext `HubSnapshotBuilder` 仅调用已配置 Tushare 和明确路径的真实文件；调用失败返回 MISSING，不自动切 AkShare/百度/其他源。API/UI保留 `source_statuses`、路径、更新时间、记录数和 missing_evidence。示例缺失态也明确标为 MISSING，而不填充数值。

### 19. 如何证明不会真实下单？

代码和测试共同证明：Paper/Shadow 的 `real_broker_called=false`；LiveBroker 的 `submit()` 永久 BLOCKED；UI 没有直接下单按钮；审批 POST 返回 `execution_triggered=false`；Kill Switch 测试阻断所有路由；无真实持仓无法创建 SELL 草案。

### 20. 下一阶段还需要做什么？

下一阶段属于外部运营而非本轮自动实盘：积累连续 Paper/Shadow 历史；补齐不同 Regime 的真实样本；完成 Telegram webhook 运维和签名校验；在券商权限开通后另行安全评审真实 QMT 发送实现；只有 Paper 稳定、Shadow 对账、小额白名单和逐笔审批均通过后，才讨论受控小额实盘。

## 2026-07-10 真实运行证据

- Tushare/本地快照生成 16 类风格矩阵：半导体、科技、科创芯片、港股科技、红利、金融、消费、周期、军工、AI、黄金、债券、纳指代理、光模块真实股票篮子、PCB 真实股票篮子和显式零收益现金基准。
- 政策假设数据集覆盖 2021-01-01 至 2026-07-10 的 1,336 个交易日；固定与动态两套共 252 个假设结果。动态阈值样本内加权超额优于固定阈值，但只标记 `DYNAMIC_BETTER_IN_SAMPLE`，不视为永久规律。
- 稳健性验证包含 27 组成本/滑点/冲击组合、3 种调仓频率以及 BULL/BEAR/RANGE_BOUND/LIQUIDITY_SHOCK 四类 Regime。旧版 TopN 历史被误删后无法比较，状态明确为 PARTIAL。
- ML 点时数据集包含 5,722 个证券、6,668,235 条训练样本和 5,510 条当日评分样本。Ridge 样本外 RankIC 仅 0.00114，因此自动降级为 `PARTIAL/WATCH`、`promotion_eligible=false`、置信度 0.0228；没有把弱模型包装成可交易信号。
- 真实盘前报告位于 `data/vnext/reports/vnext_premarket_2026-07-10.{md,json,csv}`；当前报告整体 PARTIAL，且 `no_live_trade=true`、`live_enabled=false`。
- 数据恢复子任务通过现有 Tushare 客户端真实执行：U0=5,530；归一化日线 5,738、估值 5,816、资金流 5,383、财务指标 5,473 个股票文件。财务补齐逐股查询完 5,402 个缺失代码，新增成功 5,345、57 只接口真实空结果、0 次失败；没有用 mock/fallback 冒充空结果。`data:gap-plan`、`data:freshness-check`、`data:audit` 已保存缺口与 stale 证据。`MX_APIKEY` 已配置并成功调用 mx-data，但概念仅 16/380、行业仅 1/80，均按 PARTIAL 记录。Telegram Bot/Chat 与 QMT Bridge 已通过只读验证；QMT 账户和持仓可读，订单通道保持禁用。CLI 已修复为自动读取项目根 `.env`（不覆盖显式 shell 变量），无需手动 `source`。外部数据 Hub 中的真实 pool、快照、财务汇总和事件文件已以保留时间戳复制到 legacy 兼容目录，旧审计当前为 0 个 blocking gap、3 个 tag partial gaps。

## 整体禁用与回滚

设置 `HERMES_VNEXT_ENABLED=false` 后，所有 VNext CLI 返回 BLOCKED，所有 `/api/vnext/*` 返回 503；旧 API 和旧页面路由继续工作。移除 `routes_vnext`、VNext CLI 分派和 12 条前端路由即可完整回滚，原有因子/Alpha/审批/风险代码未被替换。

## CLI

```bash
.venv_quant/bin/python commands/hermes_cli.py portfolio:multi-regime --date 2026-07-10
.venv_quant/bin/python commands/hermes_cli.py strategy:policy-put --date 2026-07-10
.venv_quant/bin/python commands/hermes_cli.py semi:mainline-state --date 2026-07-10
.venv_quant/bin/python commands/hermes_cli.py ml:ranker-train --start 2021-01-01 --end 2026-07-10 --input data/vnext/ml/training.csv
.venv_quant/bin/python commands/hermes_cli.py vnext:ml-dataset-build --start 2021-01-01 --end 2026-07-10
.venv_quant/bin/python commands/hermes_cli.py ml:ranker-score --date 2026-07-10 --input data/vnext/ml/scoring_2026-07-10.csv
.venv_quant/bin/python commands/hermes_cli.py vnext:backtest-validate --date 2026-07-10 --input data/vnext/backtest-inputs/policy_hypotheses.csv
.venv_quant/bin/python commands/hermes_cli.py vnext:backtest-build --start 2021-01-01 --date 2026-07-10
.venv_quant/bin/python commands/hermes_cli.py trading:paper-run --date 2026-07-10 --input data/vnext/orders/2026-07-10.json
.venv_quant/bin/python commands/hermes_cli.py trading:shadow-run --date 2026-07-10 --input data/vnext/orders/2026-07-10.json
.venv_quant/bin/python commands/hermes_cli.py approval:telegram-test
.venv_quant/bin/python commands/hermes_cli.py broker:qmt-probe
.venv_quant/bin/python commands/hermes_cli.py review:antifragile --date 2026-07-10 --input data/vnext/review-inputs/2026-07-10.json
.venv_quant/bin/python commands/hermes_cli.py report:vnext-premarket --date 2026-07-10
```

所有命令默认 dry-run / no-live-trade。输入缺失时命令返回 MISSING 产物，不生成示例信号。

## 风险说明

- 政策托底只能被代理和回测，不能被当成确定事实。
- 动态箱体也可能过拟合；必须使用滚动样本外验证。
- ETF/个股/港股/海外代理的数据时区、交易日和复权口径必须在正式组合前对齐。
- ML 模型文件仅可从内部模型注册表按 SHA-256 校验加载，不能加载用户未知 pickle/joblib。
- 本轮不提供任何真实委托实现；未来新增真实发送代码必须重新进行 GitNexus 影响分析、安全审计和审批链验收。
