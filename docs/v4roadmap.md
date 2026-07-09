# Hermes V4 系列开发 Roadmap：低频量化研究底座、半导体 Alpha Factory 与实盘前置体系

## 一、用户需求总结

用户当前的核心目标不是做分钟级高频交易，而是建设一套面向 A 股、以半导体 / AI 算力 / 国产替代 / 十五五科技主线为核心研究方向的低频量化系统。

用户主观上长期看好半导体，但要求 Hermes 不能直接把“用户看好”当成投资结论。Hermes 必须通过数据证明：

1. 半导体主题相对全 A 是否有超额；
2. 半导体核心池是否优于广义 AI/半导体池；
3. 因子是否真的能在半导体内部选出强股；
4. 因子是否跑赢半导体同池等权；
5. 因子收益是否只是行业 Beta、市值暴露、高波动暴露或阶段性牛市行情；
6. 当前策略是否具备 Paper Trading、Shadow Trading、小资金实盘的前置资格。

用户不希望 Hermes 只做单一策略，也不希望特化某个半导体趋势策略。Hermes 应该建设的是：

* 可扩展的数据底座；
* 分层股票池体系；
* 因子生成、验证、淘汰体系；
* 半导体专属因子库；
* 多基准对比体系；
* 风险暴露归因体系；
* 低频组合回测体系；
* Paper / Shadow / 小资金实盘 Gate；
* 企业微信通知与人工审批链；
* 可审计、可复现、可追踪的 Alpha Factory。

用户明确不接受 demo 数据、fallback 数据或静默填充。真实数据不可用时，系统必须明确失败并说明原因。

---

## 二、当前系统审计结论

根据 Hermes 已输出的审计报告，当前系统处于：

**短样本探索级 · 价量因子为主 · 半导体主题研究初期**

尚未达到研究型量化闭环，更不具备小资金实盘条件。

当前关键事实包括：

1. 当前 pool.csv 有约 315 只 AI 图谱候选标的，但来源单一、口径过宽，包含大量泛科技或非半导体实质标的，只能作为 U2 广义候选池，不能直接作为因子研究主池。
2. 当前只有 21 只核心半导体标签，覆盖面明显不足。
3. 当前没有 U0 全 A 基础池，没有 U1 用户可交易池，没有 U4 匹配对照池。
4. 当前个股日线行情极有限，仅覆盖少数股票和约 1 年时间，无法做长期因子验证。
5. 当前财务数据只有少数报告期，无法支持稳定的基本面因子。
6. 当前因子体系约 85% 偏价量，LLM 生成因子也主要是价量公式组合。
7. 当前 `beats_peer` 的 peer 定义错误，不是半导体同池等权，导致可能把行业 Beta 误判成 Alpha。
8. 当前缺少半导体同池等权 Gate、风险暴露归因、未来函数检查、交易成本估计、换手率估计和真实可交易约束。
9. 当前不能进入小资金实盘。

上述结论来自 Hermes 审计报告：系统当前无法证明半导体相对全 A 有超额，也无法证明因子挖掘跑赢半导体同池等权；报告同时指出个股日线数据仅覆盖少数股票和约 1 年，因子体系严重偏价量，且当前 `beats_peer` 不是半导体同池等权。

---

## 三、V4 系列总体目标

V4 系列的总目标是：

**把 Hermes 从“短样本价量探索系统”升级为“低频量化研究与半导体 Alpha Factory 系统”。**

V4 系列不追求立刻自动交易，不追求分钟级高频，不追求 Level-2 盘口策略。

V4 的优先目标是：

1. 建立真实全 A 低频数据底座；
2. 建立 U0-U4 分层股票池；
3. 建立半导体同池等权、核心池等权、匹配对照池等权；
4. 建立因子验证、风险归因、交易成本后收益评价；
5. 从价量因子扩展到财务、估值、资金、事件、产业链标签、政策催化和海外映射因子；
6. 让 LLM 从“公式生成器”升级为“产业假设生成 + 可计算因子映射 + 失败归因 + 迭代优化”的研究助手；
7. 建立低频组合回测、Paper Trading、Shadow Trading 和小资金实盘 Gate。

---

## 四、数据采购与数据源原则

### 4.1 当前数据采购判断

当前阶段建议使用：

* Tushare 15000 积分 30 天作为低频研究主数据源；
* Baostock / AkShare 作为免费交叉验证和兜底；
* 本地 DuckDB / Parquet / SQLite 作为数据仓库；
* miniQMT / QMT 后续作为实盘账户、持仓、委托、成交回报和执行通道；
* 巨潮资讯网、交易所公告、Tushare 公告信息作为中期事件数据来源；
* Tushare 券商研报库或其他研报源作为后期研报语义库来源。

### 4.2 当前暂不购买的数据

当前不建议购买：

* 历史分钟数据；
* 实时分钟数据；
* Level-2 盘口；
* 高频 tick 数据；
* 逐笔委托 / 逐笔成交；
* 专业机构级 Wind / Choice / iFinD 全量终端。

原因：

用户当前明确以低频量化为主。当前 P0 缺口是全 A 日线、长期历史、财务、涨跌停、停牌、ST、半导体同池等权和风险归因，不是分钟级执行优化。

### 4.3 数据源分层

| 数据层     | 主要来源                                    | 用途                               |
| ------- | --------------------------------------- | -------------------------------- |
| 低频研究数据  | Tushare 15000、Baostock、AkShare          | 全 A 日线、财务、估值、涨跌停、停牌、ST、资金、两融、龙虎榜 |
| 主题与标签数据 | atlas、Tushare 概念、ETF 持仓、行业分类、人工维护       | U2/U3 半导体池、产业链标签、核心度评分           |
| 事件数据    | 巨潮、上交所、深交所、Tushare 公告信息                 | 订单、扩产、中标、回购、减持、业绩预告、监管函          |
| 研报语义数据  | Tushare 券商研报库、券商官网、后续 Wind/Choice/iFinD | 半导体产业链逻辑、盈利预测、预期变化、机构关注          |
| 实盘执行数据  | miniQMT / QMT                           | 持仓、资金、委托、成交、撤单、交易回报              |
| 盘中监控数据  | QMT 行情、Tushare 实时日线、指数/ETF实时行情          | 持仓风控、主线跳水、涨跌停风险、企业微信预警           |
| 高频数据    | 历史分钟、实时分钟、Level-2                       | 暂缓，后续用于执行优化而非当前因子验证              |

---

## 五、V4 版本规划总览

| 版本    | 名称                        | 目标                               |
| ----- | ------------------------- | -------------------------------- |
| V4.0  | 数据源接入与本地数据仓库              | 建立 Tushare/Baostock/AkShare 数据底座 |
| V4.1  | 分层股票池体系                   | 建立 U0-U4 股票池和 ETF 替代池            |
| V4.2  | 历史数据扩展与数据审计               | 全 A 日线扩展到至少 2021，目标 2019         |
| V4.3  | 基准体系与同池等权 Gate            | 建立半导体同池等权、核心池等权、匹配对照池等权          |
| V4.4  | 因子评价与风险归因增强               | 加入交易成本、换手率、市值/Beta/波动/流动性暴露      |
| V4.5  | 半导体专属因子库                  | 建立主题择时、内部选股、风险反证三类因子             |
| V4.6  | LLM Alpha Factory 升级      | LLM 从公式生成器升级为研究假设与失败归因助手         |
| V4.7  | 低频组合构建与推荐系统               | 从 TopN 因子推荐升级为组合权重与仓位建议          |
| V4.8  | Paper / Shadow Trading 闭环 | 用真实低频信号跑模拟盘和影子交易                 |
| V4.9  | 小资金实盘 Readiness Gate      | 定义并实现小资金实盘前置门槛                   |
| V4.10 | 事件与研报语义增强                 | 公告 PDF、研报语义库、半导体事件因子             |
| V4.11 | 盘中低频监控与执行前置               | 仅做低频策略的盘中风控，不做高频                 |
| V4.12 | V4 总验收与生产化冻结              | 形成稳定、可复现、可扩展的 V4 低频量化系统          |

---

# V4.0 数据源接入与本地数据仓库

## 目标

建立可靠、可复现、可增量更新的低频数据底座。禁止继续依赖手工 CSV、demo 数据或隐式 fallback。

## 主要任务

### V4.0.1 Tushare Provider

实现 `TushareProvider`，支持：

* `trade_cal`
* `stock_basic`
* `daily`
* `adj_factor`
* `daily_basic`
* `stk_limit`
* `suspend_d`
* `index_daily`
* `index_weight`
* `income`
* `balancesheet`
* `cashflow`
* `fina_indicator`
* `forecast`
* `express`
* `moneyflow`
* `margin`
* `margin_detail`
* `top_list`
* `top_inst`
* `repurchase`
* `share_float`
* `stk_holdertrade`
* `stk_holdernumber`
* 概念 / 行业 / 资金 / 机构调研等套餐内可用数据。

### V4.0.2 免费数据源 Provider

实现：

* `BaostockProvider`
* `AkshareProvider`

用途：

* 交叉验证；
* 补字段；
* 免费兜底；
* 对 Tushare 异常数据做二次校验。

### V4.0.3 本地数据仓库

建立本地数据目录：

```text
data/
  raw/
    tushare/
    baostock/
    akshare/
  normalized/
    market/
    fundamentals/
    limits/
    suspend/
    industry/
    concept/
    funds/
    events/
  warehouse/
    duckdb/
    parquet/
  audit/
    manifests/
    health/
    lineage/
```

### V4.0.4 增量更新机制

支持：

```text
hermes data:bootstrap --source tushare --start 20190101 --end latest
hermes data:update --source tushare --days 5
hermes data:health
hermes data:lineage
```

### V4.0.5 禁止静默 fallback

如果真实数据不可用，必须：

* 明确失败；
* 输出缺失接口；
* 输出缺失字段；
* 输出数据源；
* 输出修复建议。

不得用 demo 数据填补。

## 验收标准

1. `hermes data:bootstrap` 能初始化低频数据目录。
2. `hermes data:update` 能增量更新最近交易日。
3. `hermes data:health` 能输出覆盖率、缺失率、最新日期、异常值。
4. 所有数据文件都有 manifest。
5. 任一关键字段缺失时系统明确报错，不允许静默填充。

---

# V4.1 分层股票池体系

## 目标

把当前单层 315 只 AI 图谱候选池重构为 U0-U4 分层股票池。

## 股票池定义

### U0 全 A 基础池

用途：

* 全市场基准；
* 行业对照；
* 风险暴露分析；
* 市场中性化；
* 半导体相对全 A 超额计算。

字段要求：

```text
ts_code
symbol
name
exchange
board
list_date
delist_date
is_listed
industry
concepts
total_mv
float_mv
```

### U1 用户可交易池

用途：

* 真实账户可买范围；
* 用户主板优先；
* 创业板、科创板、北交所等做权限标记；
* ST、停牌、低流动性、黑名单过滤。

字段要求：

```text
is_mainboard
is_chinext
is_star
is_bse
is_st
is_suspended
is_limit_up
is_limit_down
avg_amount_20d
tradable_by_user
trade_block_reason
```

### U2 AI/半导体广义池

用途：

* 保留 atlas 315 只作为广义候选池；
* 标注来源；
* 标注置信度；
* 标注是否半导体核心相关。

字段要求：

```text
source_atlas
source_concept
source_etf_holding
source_industry
source_manual
source_confidence
ai_chain_layer
theme_tags
is_broad_ai_semiconductor
```

### U3 半导体核心池

用途：

* 半导体主策略研究池；
* 目标覆盖 80-150 只；
* 按细分方向和核心度评分管理。

字段要求：

```text
semiconductor_subsector
core_score
domestic_substitution_score
supply_chain_position
is_equipment
is_material
is_design
is_foundry
is_packaging
is_eda
is_ip
is_storage
is_power
is_pcb
is_cpo_related
```

### U4 匹配对照池

用途：

* 判断因子是否只是小市值、高波动、高 Beta 或成长风格暴露；
* 对 U3 中标的按市值、成交额、波动率、成长风格匹配非半导体标的。

匹配规则：

```text
float_mv ± 20%
avg_amount_20d ± 30%
volatility_60d ± 20%
exclude U2/U3
prefer same board
```

### ETF 替代池

用途：

* 用户账户无法直接买科创/创业板时提供 ETF 替代；
* 与半导体、芯片、科创芯片、AI 算力、PCB、设备等主题挂钩。

## 命令

```text
hermes universe:build
hermes universe:list
hermes universe:show U0
hermes universe:show U1
hermes universe:show U2
hermes universe:show U3
hermes universe:show U4
hermes universe:audit
```

## 验收标准

1. U0 覆盖全 A。
2. U1 明确用户可交易范围。
3. U2 保留原 315 只候选池，但标注来源和置信度。
4. U3 半导体核心池达到 80-150 只。
5. U4 能为每只 U3 股票匹配 1-3 只非半导体对照股。
6. ETF 替代池不少于 10 只。
7. `universe:audit` 输出纯度、覆盖率、权限、流动性和风险标签报告。

---

# V4.2 历史数据扩展与数据审计

## 目标

把当前约 1 年、少数股票的数据扩展为可用于低频因子研究的长期全 A 数据。

## 数据范围

最低要求：

```text
全 A 日线：2021-01-01 至今
半导体核心池：2019-01-01 至今
财务数据：2018 年至今
估值数据：2021-01-01 至今
涨跌停 / 停牌 / ST：2021-01-01 至今
指数 / ETF：2021-01-01 至今
```

优先目标：

```text
全 A 日线：2019-01-01 至今
半导体核心池：2018-01-01 至今
财务数据：2018 年至今
```

## 必须字段

日线行情：

```text
trade_date
ts_code
open
high
low
close
pre_close
change
pct_chg
vol
amount
adj_factor
```

每日指标：

```text
turnover_rate
turnover_rate_f
volume_ratio
pe
pe_ttm
pb
ps
ps_ttm
dv_ratio
total_share
float_share
free_share
total_mv
circ_mv
```

交易约束：

```text
up_limit
down_limit
is_suspended
is_st
list_date
delist_date
```

财务数据：

```text
roe
gross_margin
net_margin
debt_ratio
revenue_yoy
profit_yoy
ocf
eps
bps
report_date
ann_date
```

## 数据审计

实现：

```text
hermes data:health
hermes data:coverage
hermes data:freshness
hermes data:missing
hermes data:outliers
hermes data:survivorship-check
```

## 验收标准

1. 全 A 日线覆盖至少 2021 至今。
2. 半导体核心池行情覆盖至少 2019 至今。
3. 财务数据覆盖至少 2018 至今。
4. 系统可识别停牌、涨跌停、ST、退市、生存偏差。
5. 数据缺失率、异常值、新鲜度能自动报告。
6. 回测不得使用未通过 `data:health` 的数据。

---

# V4.3 基准体系与同池等权 Gate

## 目标

修复当前 `beats_peer` 定义错误，建立正确基准体系，防止把行业 Beta 当成 Alpha。

## 新增基准

```text
benchmark: sh_index
benchmark: csi300
benchmark: csi500
benchmark: csi1000
benchmark: csi_all_share
benchmark: ew_a_share
benchmark: ew_tradable
benchmark: semiconductor_ew
benchmark: semiconductor_core_ew
benchmark: matched_control_ew
benchmark: semiconductor_etf_basket
```

## 核心指标

每个因子必须输出：

```text
excess_vs_csi300
excess_vs_ew_a_share
excess_vs_ew_tradable
excess_vs_semiconductor_ew
excess_vs_semiconductor_core_ew
excess_vs_matched_control_ew
excess_vs_etf_basket
beats_semiconductor_peer
beats_core_peer
beats_matched_control
```

## Gate 规则

因子晋级必须满足：

```text
beats_semiconductor_peer = True
或者
beats_core_peer = True
```

若因子只跑赢上证、沪深 300 或全 A，但跑输半导体同池等权，则不得晋级为半导体选股因子。

## 命令

```text
hermes benchmark:build
hermes benchmark:list
hermes benchmark:report
hermes factor:validate --benchmark-set semiconductor
```

## 验收标准

1. `benchmark:list` 显示所有基准。
2. 因子报告中必须包含半导体同池等权超额。
3. Gate 拒绝跑输半导体同池等权的半导体选股因子。
4. 原有 `beats_peer` 必须废弃或重命名，避免误导。

---

# V4.4 因子评价与风险归因增强

## 目标

把当前基础回测评价升级为研究型因子评价体系。

## 必须新增指标

```text
IC
Rank IC
ICIR
IC positive ratio
分层收益
Top-Bottom 收益
Top-Bottom Sharpe
换手率
交易成本后收益
滑点估计后收益
最大回撤
胜率
CAGR
Calmar
半导体同池等权超额
核心池等权超额
匹配对照池超额
ETF 篮子超额
```

## 风险暴露归因

必须支持：

```text
市值暴露
Beta 暴露
波动率暴露
流动性暴露
行业暴露
细分方向暴露
创业板 / 科创板暴露
低价股暴露
极端个股贡献
Jackknife 剔除分析
```

## 交易成本模型

低频阶段使用简化模型：

```text
手续费
印花税
滑点估计
冲击成本估计
换手率惩罚
涨停买不进
跌停卖不出
停牌不可交易
```

## 命令

```text
hermes factor:validate-v4
hermes factor:risk-attribution
hermes factor:cost-adjust
hermes factor:jackknife
```

## 验收标准

1. 所有因子报告必须包含交易成本后收益。
2. 所有半导体因子必须输出行业、市值、Beta、波动率、流动性暴露。
3. 所有因子必须输出极端个股贡献。
4. 任一因子若收益主要来自少数极端个股，必须降级。
5. 任一因子若跑赢来自高 Beta 或小市值暴露，必须标记为“暴露型收益”，不能标记为“残差 Alpha”。

---

# V4.5 半导体专属因子库

## 目标

从价量因子为主，升级到半导体主题择时 + 半导体内部选股 + 风险反证三类因子体系。

## A 类：主题择时因子

回答：

“什么时候应该重配半导体？”

因子包括：

```text
semi_vs_all_a_strength
semi_vs_growth_strength
semi_turnover_share
semi_amount_share
semi_up_ratio
semi_limit_up_count
semi_leader_strength
semi_etf_amount_trend
semi_etf_volume_trend
semi_subsector_diffusion
semi_policy_heat
semi_overseas_mapping
```

输出：

```text
theme_state: 极弱 / 偏弱 / 中性 / 偏强 / 极强
recommended_theme_weight: 0% / 30% / 50% / 70% / 100%
```

## B 类：半导体内部选股因子

回答：

“在半导体池子里，买谁？”

因子包括：

```text
stock_vs_semi_ew_strength
stock_vs_subsector_strength
subsector_rotation_strength
leader_following
volume_confirmation
breakout_after_volatility_compression
amount_persistence
gross_margin_improvement
revenue_growth_trend
profit_growth_trend
valuation_not_overheated
forecast_revision_proxy
institution_research_heat
margin_financing_change
etf_holding_proxy
event_catalyst_score
```

## C 类：风险反证因子

回答：

“这个因子是不是假的？”

因子包括：

```text
industry_beta_exposure
size_exposure
market_beta_exposure
volatility_exposure
liquidity_exposure
low_price_exposure
board_exposure
extreme_winner_dependence
turnover_cost_drag
```

## 验收标准

1. 新增至少 30 个非纯价量因子。
2. 至少 10 个半导体专属因子进入 AlphaRegistry。
3. 主题择时模块能输出半导体建议仓位。
4. 内部选股因子必须对比半导体同池等权。
5. 风险反证因子必须进入因子报告。

---

# V4.6 LLM Alpha Factory 升级

## 目标

让 LLM 从“价量公式生成器”升级为“产业假设生成 + 可计算因子映射 + 失败归因 + 迭代优化”的 Alpha 研究助手。

## 新流程

```text
产业假设生成
→ 数据字段映射
→ 因子公式生成
→ 数据可得性检查
→ 未来函数检查
→ 单因子验证
→ 同池等权对比
→ 风险暴露归因
→ 失败原因总结
→ 下一代因子迭代
→ AlphaRegistry 记录
→ AlphaLifecycle 状态更新
```

## LLM Prompt 必须扩展字段

从当前价量字段扩展到：

```text
price_fields
volume_fields
amount_fields
valuation_fields
fundamental_fields
growth_fields
quality_fields
fund_flow_fields
margin_fields
event_fields
policy_fields
industry_tag_fields
semiconductor_subsector_fields
etf_fields
benchmark_fields
risk_exposure_fields
```

## 新增 Gate

```text
future_leakage_gate
data_availability_gate
semiconductor_peer_gate
risk_exposure_gate
cost_adjusted_gate
trial_count_gate
multiple_testing_gate
```

## 新增记录

每次 LLM 生成因子必须记录：

```text
hypothesis
factor_expression
required_fields
parent_factor_id
trial_id
trial_count
validation_result
failure_reason
next_iteration_suggestion
status_change
```

## 验收标准

1. LLM 生成因子不得只使用价量字段。
2. 每个因子必须有产业假设。
3. 每个失败因子必须有失败归因。
4. 每次迭代必须有父代记录。
5. 试验次数必须进入审计日志。
6. 所有 LLM 因子必须通过未来函数检查。

---

# V4.7 低频组合构建与推荐系统

## 目标

从“因子排行榜”升级为“可执行低频组合建议”。

## 组合输出

每日或每周输出：

```text
主题仓位建议
核心组合
卫星组合
ETF 替代组合
禁止买入清单
减仓观察清单
风控拦截原因
同池等权对比
组合风险暴露
次日风险提示
```

## 组合约束

```text
单票仓位上限
行业集中度上限
细分方向集中度上限
主板优先
创业板/科创板权限过滤
ETF 替代
日成交额过滤
涨停禁买
跌停禁卖
停牌禁交易
100股整数倍
尾盘禁新仓
换手率约束
交易成本约束
```

## 命令

```text
hermes portfolio:build-lowfreq
hermes portfolio:recommend
hermes portfolio:risk
hermes premarket:v4
```

## 验收标准

1. 组合推荐必须说明每只股票入选原因。
2. 组合推荐必须说明每只股票风控状态。
3. 推荐必须给出 ETF 替代方案。
4. 推荐必须输出与半导体同池等权的历史对比。
5. 不满足交易约束的股票不得进入可买清单。

---

# V4.8 Paper / Shadow Trading 闭环

## 目标

把 V4 研究信号接入模拟盘和影子交易，验证低频策略真实可执行性。

## Paper Trading

模拟：

```text
计划买入
计划卖出
可交易性检查
涨跌停检查
停牌检查
资金检查
100股整数倍
手续费/滑点
模拟成交
组合收益
执行偏差
```

## Shadow Trading

对比：

```text
策略计划
真实行情
实际可买
实际可卖
风控拦截
模拟成交
次日表现
一周表现
相对同池等权表现
```

## 命令

```text
hermes paper:v4-run
hermes shadow:v4-run
hermes paper:v4-dashboard
hermes shadow:v4-report
```

## 验收标准

1. Paper Trading 至少连续运行 20 个交易日。
2. Shadow Trading 至少连续运行 20 个交易日。
3. 输出计划交易与实际可交易差异。
4. 输出风控拦截次数和原因。
5. 输出相对半导体同池等权表现。
6. 若 Paper 或 Shadow 跑输同池等权，不得进入小资金实盘 Gate。

---

# V4.9 小资金实盘 Readiness Gate

## 目标

定义小资金实盘前置条件。注意：V4.9 只做 readiness，不默认自动下单。

## 必须通过的 Gate

```text
DataHealthGate
UniversePurityGate
BenchmarkGate
SemiconductorPeerGate
RiskExposureGate
CostAdjustedReturnGate
PaperTradingGate
ShadowTradingGate
TradeConstraintGate
ManualApprovalGate
KillSwitchGate
AuditTrailGate
```

## 小资金实盘最低条件

必须同时满足：

1. 数据健康检查通过；
2. 半导体核心池有效；
3. 因子跑赢半导体同池等权；
4. 策略跑赢半导体核心池等权；
5. 匹配对照池超额为正；
6. 交易成本后收益仍为正；
7. Paper Trading 连续 20 个交易日稳定；
8. Shadow Trading 连续 20 个交易日稳定；
9. 最大回撤低于阈值；
10. 风控拦截逻辑正常；
11. 企业微信审批链正常；
12. Kill Switch 正常；
13. 审计日志完整。

## 命令

```text
hermes live-readiness:v4
hermes live-gate:v4-report
```

## 验收标准

输出：

```text
READY / NOT_READY
阻塞项
证据
修复建议
是否允许小资金实盘
是否允许自动交易
```

默认情况下：

```text
小资金实盘 = 需要人工审批
自动交易 = 不允许
```

---

# V4.10 事件与研报语义增强

## 目标

补足半导体产业链 Alpha，解决当前因子体系过度价量化的问题。

## 公告事件库

优先覆盖 U3 半导体核心池。

事件类型：

```text
订单
中标
扩产
定增
回购
减持
业绩预告
业绩快报
资产重组
监管函
问询函
大基金入股
国产替代突破
客户认证
```

输出字段：

```text
event_date
announce_time
tradable_date
ts_code
event_type
event_direction
event_strength
amount
product
customer
capacity
risk_flag
source_url
pdf_path
llm_summary
structured_facts
```

## 研报语义库

优先覆盖：

```text
半导体行业研报
半导体设备研报
材料研报
封测研报
存储研报
PCB/载板研报
AI算力链研报
U3 核心公司深度研报
```

提取字段：

```text
report_date
broker
analyst
rating
target_price
eps_forecast
revenue_forecast
profit_forecast
industry_view
subsector_view
company_moat
risk_points
llm_industry_tags
llm_factor_hypotheses
```

## 验收标准

1. 公告事件能映射到股票和交易日。
2. 公告事件不能使用未来信息。
3. 研报语义只作为假设来源，不直接作为买入结论。
4. 事件因子必须经过同池等权验证。
5. LLM 摘要必须保留原文证据路径。

---

# V4.11 盘中低频监控与执行前置

## 目标

只做低频策略的盘中风控和提醒，不做高频交易。

## 监控范围

```text
持仓实时涨跌幅
持仓盈亏
候选股涨跌停状态
半导体 ETF 跳水
半导体核心池扩散度
全 A 情绪
指数风险
当日成交额异常
风险事件公告
企业微信预警
```

## 不做的事情

```text
不做分钟级高频策略
不做 Level-2 盘口策略
不做自动追涨打板
不做无审批自动下单
不做无数据审计的实时推荐
```

## 命令

```text
hermes intraday:monitor
hermes intraday:risk
hermes intraday:wechat-alert
```

## 验收标准

1. 能监控持仓和候选池。
2. 能识别涨停买不进、跌停卖不出、停牌。
3. 能触发企业微信提醒。
4. 能输出盘中风险报告。
5. 不触发自动交易。

---

# V4.12 V4 总验收与生产化冻结

## 目标

冻结 V4 低频量化系统，形成稳定可复现版本。

## 总验收条件

必须证明：

1. 数据真实、完整、可审计；
2. 股票池分层清晰；
3. 半导体核心池不是单一 atlas 候选池；
4. 半导体同池等权基准存在；
5. 因子必须跑赢半导体同池等权才可晋级；
6. 因子能输出风险暴露归因；
7. 交易成本后收益可计算；
8. LLM 不是单纯价量公式生成器；
9. Paper / Shadow 结果可复现；
10. 小资金实盘 Gate 能明确给出 READY / NOT_READY；
11. 所有报告有 manifest 和 audit trail；
12. 无 demo 数据、无静默 fallback。

## 输出文档

```text
V4 Architecture Report
V4 Data Lineage Report
V4 Universe Report
V4 Benchmark Report
V4 Factor Library Report
V4 Alpha Factory Report
V4 Paper/Shadow Report
V4 Live Readiness Report
V4 User Manual
```

---

## 六、V4 开发优先级

### P0：必须优先

1. V4.0 数据源接入与本地数据仓库；
2. V4.1 U0-U4 股票池；
3. V4.2 全 A 历史数据扩展；
4. V4.3 半导体同池等权基准和 Gate；
5. V4.4 风险归因与交易成本评价；
6. 未来函数检查。

### P1：研究闭环增强

1. V4.5 半导体专属因子库；
2. V4.6 LLM Alpha Factory 升级；
3. V4.7 低频组合构建；
4. V4.8 Paper / Shadow Trading。

### P2：生产前置

1. V4.9 小资金实盘 Readiness；
2. V4.11 盘中低频监控；
3. 企业微信审批；
4. Kill Switch；
5. 审计日志完善。

### P3：增强型 Alpha

1. V4.10 公告 PDF 深度解析；
2. 研报语义库；
3. 政策催化因子；
4. 海外映射因子；
5. ETF 持仓与资金因子。

---

## 七、重要约束

1. 不做分钟级高频量化。
2. 不买 Level-2 作为当前 P0。
3. 不允许 demo 数据。
4. 不允许 fallback 冒充真实数据。
5. 不允许只和上证指数或沪深 300 比较。
6. 半导体因子必须和半导体同池等权比较。
7. 半导体策略必须和半导体核心池等权比较。
8. 所有因子必须检查未来函数。
9. 所有因子必须检查交易成本后收益。
10. 所有因子必须检查市值、Beta、波动率、流动性暴露。
11. 所有 LLM 生成因子必须记录试验次数。
12. 所有版本必须有测试、报告、审计日志和用户说明。

---

## 八、V4 最终交付目标

V4 完成后，Hermes 应该能够回答以下问题：

1. 当前半导体主题是否强于全 A？
2. 半导体核心池是否强于广义 AI/半导体池？
3. 某个因子是否真的能在半导体内部选股？
4. 某个因子是否跑赢半导体同池等权？
5. 某个因子收益是否来自市值、Beta、高波动或少数极端股票？
6. 当前组合是否比直接买半导体 ETF 更好？
7. 当前策略是否通过 Paper / Shadow 验证？
8. 当前是否允许进入小资金实盘？
9. 如果不允许，阻塞项是什么？
10. 下一步应该优化哪个因子、哪个股票池、哪个数据源或哪个风控规则？

---

## 九、给 Hermes 的执行指令

请从 V4.0 开始执行，不要跳到后面的因子挖掘或实盘模块。

执行顺序必须是：

```text
V4.0 数据源接入
→ V4.1 股票池分层
→ V4.2 历史数据扩展
→ V4.3 基准体系与同池等权 Gate
→ V4.4 因子评价与风险归因
→ V4.5 半导体专属因子库
→ V4.6 LLM Alpha Factory 升级
→ V4.7 低频组合推荐
→ V4.8 Paper / Shadow
→ V4.9 小资金实盘 Readiness
→ V4.10 事件与研报语义增强
→ V4.11 盘中低频监控
→ V4.12 V4 总验收
```

每个版本完成后必须输出：

```text
1. 变更摘要
2. 新增命令
3. 数据目录变化
4. 测试结果
5. 审计结果
6. 用户可执行示例
7. 已知限制
8. 下一版本建议
```

不要为了推进版本而降低 Gate。无法通过真实数据验证的功能，必须标记为 NOT_READY。

V4 的核心不是“尽快实盘”，而是建立一套能长期持续挖掘、验证、淘汰半导体 Alpha 的低频量化研究系统。
