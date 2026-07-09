# Hermes V3 详细开发任务分解

> 基于 2026-07-08 量化成熟度审计报告产出。
> 每个任务级别：P0=必须实盘前完成，P1=必须生产级闭环前完成，P2=研究质量改进，P3=体验优化。

---

## V3.1：修复数据可信度（10天，P0）

### V3.1.1：接入真实 benchmark 指数行情（2天，P0）

#### 任务 1.1.1：实现指数日行情加载函数

**文件**：`commands/factor_lab/portfolio/benchmark.py`

- 新增函数 `fetch_index_kline(index_code: str, start_date: str, end_date: str) -> pd.DataFrame`
- 使用 `akshare` 的 `index_daily_em` 获取沪深300(000300)、中证500(000905)、中证1000(000852)
- fallback 到 `baostock` 的 `query_history_k_data_plus`
- 返回含 date, close, volume 的 DataFrame
- 需要考虑 Baostock 大区间超时问题，按 30 天分片查询

**验收标准**：
- `fetch_index_kline("000300.SH", "2023-01-01", "2026-06-30")` 返回 800+ 行数据
- 所有三个指数都能正常获取
- 有统一的错误处理（数据源不可用时抛出明确异常，不静默降级）

#### 任务 1.1.2：替换 benchmark.py 中的 synthetic 实现

**文件**：`commands/factor_lab/portfolio/benchmark.py`

- `_synthetic_benchmark_returns()` 改为只在 `method="synthetic"` 且无真实数据时做最终 fallback
- `get_benchmark_returns()` 默认 `method="index_api"` 走真实 API
- `_etf_proxy_benchmark_returns()` 的 fallback 从 synthetic 改为调用 `fetch_index_kline`
- 移除 `np.random.default_rng(seed)` 及其所有随机生成逻辑
- 新增 `_validate_benchmark_returns()` 检查返回的收益率序列是否合理（非空、非全零、幅度合理）

**验收标准**：
- `make_benchmark_spec("CSI300").returns` 返回真实数据，不是随机数
- `get_benchmark_returns()` 默认走真实路径
- 当数据源不可用时抛出 `DataUnavailableError` 而非生成随机数
- 所有现有调用方（live_readiness.py, portfolio_backtest.py, reports）自动使用真实数据

#### 任务 1.1.3：更新所有回测报告自动使用真实 benchmark

**文件**：`commands/reports/quantstats_report.py`, `commands/reports/top_group_backtest.py`

- 确保 `generate_report()` 和 `run_top_group_backtest()` 在调用 benchmark 时走 `make_benchmark_spec()` 而非 `synthetic`
- 在回测报告 HTML 中标注 benchmark 数据来源（如 "沪深300 | 来源: akshare"）
- 旧报告不需要回溯修复

**验收标准**：
- 新生成的 HTML 报告 benchmark 曲线来自真实指数
- 报告脚注显示数据来源

---

### V3.1.2：因子可信度验证（4天，P1）

#### 任务 1.2.1：对 top 20 因子执行全量验证

**文件**：`commands/factor_lab/validate_factor.py` 新增方法

- 筛选使用频率最高的 20 个因子：ret5, ret10, ret20, ret60, vol_ratio5/20/60, ma_gap(10/20, 20/60), close_gt_ma20, volatility20/60, atr20, reversal5/20, amihud, quality(roe_q/gross_margin_q), macd, boll_width
- 对每个因子执行完整验证管道：
  - IC + ICIR
  - 5层分层回测
  - 同池等权对比
  - Walk-Forward 滚动验证（12个月train + 6个月test，3个窗口）
  - 安慰剂检验（100 trials）
  - 暴露分析（按申万一级行业分组看 IC 差异）
- 输出验证报告 JSON 到 `research_outputs/factor_validation/`

**验收标准**：
- 20 个因子各有完整验证结果 JSON
- 每个 JSON 含 IC_mean, ICIR, 分层单调性, beats_peer, WF verdict, placebo verdict
- 合并 CSV 到 `performance/factor_validation_leaderboard.csv`

#### 任务 1.2.2：实现暴露分析

**文件**：`commands/factor_lab/ic_analyzer.py` 新增函数

- `exposure_analysis(df, factor_col, group_col, ret_col="ret1")` 
  - 按行业分组计算因子 IC
  - 按市值五分位分组计算因子 IC
  - 按波动率五分位分组计算因子 IC
  - 返回各分组的 IC 均值和标准差
- `factor_exposure_report(df, factor_col, industry_col, mcap_quantile_col, vol_quantile_col)` 
  - 组装成完整暴露分析报告

**验收标准**：
- 能正确输出因子在各行业/市值/波动率分组中的 IC
- 暴露报告 JSON 格式规范化

#### 任务 1.2.3：将暴露分析集成到因子评估管线

**文件**：`commands/factor_lab/factor_evaluation.py`

- `evaluate_exposure()` 方法添加到 `FactorEvaluation` 类
- `run_full_evaluation()` 添加暴露分析步骤
- `evaluate_scoring()` 将暴露稳定性纳入评分（因子在多数行业一致为加分，只在少数行业有效为减分）

**验收标准**：
- `ev.evaluate_exposure(df, factor_name)` 返回结构化暴露报告
- `ev.run_full_evaluation()` 输出包含 exposure 段

---

### V3.1.3：数据质量升级（2天，P2）

#### 任务 1.3.1：退市股票审计

**文件**：`commands/strategy_lab/universe.py`

- Universe 构建时从 baostock 获取所有 A 股上市股票代码（含已退市）
- 标记哪些代码已退市
- universe metadata 增加 `delisted_count`, `delisted_symbols` 字段
- 回测时如果 universe 包含已退市股票，标记 `survivorship_bias_warning: critical`

**验收标准**：
- 每个 universe CSV 包含 delisted 标记列
- metadata 显示实际退市股票数量

#### 任务 1.3.2：财务数据 pub_date 严格模式

**文件**：`commands/factor_lab/factor_engine.py`

- 回测使用财报因子时，必须有 pub_date 字段
- 新增 `_check_fundamental_timing(df)` 函数，检查回测日期 T 是否 >= pub_date
- 未满足的因子标记为 `nan` 不参与计算
- 统计被排除的样本比例，记录到 execution_log

**验收标准**：
- 使用季度因子（如 roe_q）回测时自动检查 pub_date
- 日志显示有多少样本因未来数据被排除

---

## V3.2：暴露分析与因子多样性（15天，P1）

### V3.2.1：因子正交化（3天，P1）

#### 任务 2.1.1：截面正交化主流程

**文件**：`commands/factor_lab/composite/factor_combiner.py`

- 现有 `__init__.py` 和 `factor_combiner.py` 代码需要确认是否已经实现正交化
- 如果没有，实现 `orthogonalize(factor_df, method="schmidt")`（Gram-Schmidt 正交化）
- 正交化后保持因子方向不变（符号调整）
- 输出正交前后的相关性矩阵对比

**验收标准**：
- 输入 5 个高相关因子 → 输出 5 个正交因子（相关性 < 0.1）
- 正交化后的因子排名与正交前保持正相关（不破坏排序）

#### 任务 2.1.2：多因子复合评分

**文件**：`commands/factor_lab/composite/factor_combiner.py`

- `combine_factors(factor_df, factors, weights, method="sum")` 
  - 支持 method="sum"（加权求和）、"rank"（等权排名平均）、"zscore"（Z-score 等权）
  - 支持 factors=[{name, weight, direction}] 指定参与复合的因子和权重
  - 自动去除缺失行（至少 50% 有效因子才参与）

**验收标准**：
- 能正确组合 3 个因子生成复合因子
- 复合因子的 IC > 各单因子 IC 的均值（或至少不显著下降）

---

### V3.2.2：基本面估值因子接入（3天，P2）

#### 任务 2.2.1：实现财务数据获取函数

**文件**：`commands/factor_lab/data_source/adapters.py` 或新建 `commands/factor_lab/fundamental_data.py`

- 使用 `mx:data` 或 `akshare` 获取季度财务数据
- 字段：pe_ttm, pb, ps_ttm, pcf_ttm, roe_ttm, roe_q, gross_margin_q, net_margin_q, revenue_growth_q, profit_growth_q
- 数据对齐到发布日期（pub_date）
- 缓存到本地 CSV 以减少重复请求

**验收标准**：
- `get_fundamentals(symbols, start_date, end_date)` 返回 DataFrame
- 每列有明确的 pub_date
- 数据覆盖最近 3 年

#### 任务 2.2.2：注册基本面因子

**文件**：`commands/factor_lab/factor_base.py`

- 注册以下因子（使用 `@register` 装饰器）：
  - `pe_ttm_inv`（PE_TTM 倒数，越高越便宜）
  - `pb_lf`（市净率倒数）
  - `roe_ttm`（ROE 质量因子）
  - `profit_growth_q`（单季利润增速）
  - `revenue_growth_q`（单季营收增速）
  - `gross_margin_q`（毛利率质量因子）
- 所有因子 `backtest_allowed=True` 但依赖 pub_date 检查

**验收标准**：
- 6 个新因子出现在 `list_factors()` 中
- `factor_engine.compute_all(df)` 能计算这些因子

#### 任务 2.2.3：基本面因子快速验证

- 对新注册的 6 个因子跑 IC/同池等权/暴露分析
- 输出验证结果到 `research_outputs/factor_validation/`

**验收标准**：
- 每个因子有验证报告
- PE_TTM_INV 在低估值行情中 IC 为正

---

### V3.2.3：资金流因子接入（3天，P2）

#### 任务 2.3.1：资金流数据获取

**文件**：`commands/eastmoney_direct.py`（已有资金流接口，需包装）

- 封装 `get_money_flow(symbol, start_date, end_date)` 返回日度资金流数据
  - 主力净流入/流出
  - 超大单净流入
  - 大单净流入
  - 中单/小单净流入
  - 北向资金净流入

**验收标准**：
- 数据获取稳定，覆盖 2025-2026 年
- 每日资金流数据完整

#### 任务 2.3.2：注册资金流因子

**文件**：`commands/factor_lab/factor_base.py`

- `net_big_order_ratio5/10/20`（大单净流入占比，5/10/20日累计）
- `north_bound_flow_5/10/20`（北向资金净流入累计）
- `money_flow_signal`（主力净流入且股价未涨 = 潜伏信号）

**验收标准**：
- 因子注册到 `fund_flow` 和 `north_bound` 分类
- 能通过 `compute_all()` 计算

#### 任务 2.3.3：资金流因子验证

- 跑 IC/同池等权/暴露分析
- 横截面来看，主力净流入大的股票是否次日有超额收益

**验收标准**：
- 验证报告显示是否有选股能力（IC > 0.02？beats peer？）

---

### V3.2.4：行业因子（3天，P2）

#### 任务 2.4.1：行业动量因子

**文件**：`commands/factor_lab/industry_relative/factors.py`

- 完善现有 `industry_relative` 模块
- `industry_momentum(df, industry_col, window=20)`：行业指数过去 20 日收益率
- `industry_relative_strength(df, industry_col, window=20)`：个股收益 - 行业收益
- `industry_concentration(df, industry_col)`：行业拥挤度（行业 vs 全市场成交额占比）

**验收标准**：
- 因子可持续计算
- `industry_relative_strength` 能剥离行业 Beta

#### 任务 2.4.2：注册行业因子到 factor_base

- 注册以上 3 个行业因子到 `industry_relative` 分类

**验收标准**：
- 出现在 `list_factors()` 中

---

### V3.2.5：AlphaSpec 元数据补齐（2天，P2）

#### 任务 2.5.1：扩展 AlphaSpec 字段

**文件**：`commands/factor_lab/alpha/schema.py`

- 新增字段：
  - `delay: int = 0`（信号滞后天数，默认 0 表示 T+0 可用）
  - `cost_assumption: dict = field(default_factory=lambda: {"commission": 0.0003, "slippage_bps": 10})`
  - `valid_period: str = "2025-01_to_2026-06"`（有效窗口，用于跟踪因子生命周期）
  - `audit_log: list = field(default_factory=list)`（[{date, event, detail}]）
- 保持向后兼容（dataclass default 已有值）

**验收标准**：
- 现有 Alpha Registry 条目不报错
- `AlphaSpec(alpha_id="test").delay == 0`

#### 任务 2.5.2：Alpha Registry 迁移

**文件**：`commands/factor_lab/alpha/registry.py`

- 重新迁移（或补全）现存的 142 个 Alpha 条目
- 每个条目的 `spec.json` 补充新字段
- `audit_log` 初始化为空列表

**验收标准**：
- `alpha:list --json` 显示新字段
- 所有 142 个 Alpha 元数据完整

#### 任务 2.5.3：Factor ↔ Alpha 同步增强

**文件**：`commands/factor_lab/factor_alpha_bridge.py`

- `sync_factors_to_alpha()` 同步时填充新字段（delay, cost_assumption 从因子定义推断）
- 更新因子定义中的 valid_period（按因子首次出现日期到当前日期自动计算）

**验收标准**：
- 同步后 Alpha Registry 条目含完整元数据

---

## V3.3：组合构建系统升级（10天，P1）

### V3.3.1：因子加权组合（3天，P1）

#### 任务 3.1.1：IC 加权组合

**文件**：`commands/factor_lab/composite/factor_combiner.py`

- `ic_weighted_combination(factor_df, factors, ic_history)` 
  - 从 ic_history（DataFrame of {factor, ic_mean, ic_ir}）计算权重
  - 支持 weight = ic_mean × ic_ir（IC + ICIR 双因素）
  - 支持 weight = ic_mean / std(historical_ic)（考虑 IC 稳定性）
  - 支持 max_weight 约束（单个因子不超过 0.3）

**验收标准**：
- 输入 5 个因子 + IC history → 输出组合因子 + 权重分配
- 组合因子 IC > 等权组合 IC

#### 任务 3.1.2：风险平价组合

- `risk_parity_weights(factor_corr_matrix)` 通过凸优化求解风险平价权重
- 使用 `scipy.optimize.minimize` 求解
- 支持因子数量 3-10

**验收标准**：
- 各因子的风险贡献相等
- 总风险低于等权组合

#### 任务 3.1.3：组合权重验证

- 比较等权、IC加权、风险平价三种方式在回测中的表现
- 输出三种方式的 Sharpe/回撤/换手率对比

**验收标准**：
- 至少一种加权方式在多数市场状态下优于等权

---

### V3.3.2：风控约束集成（3天，P1）

#### 任务 3.2.1：行业暴露约束

**文件**：`commands/factor_lab/portfolio/portfolio_backtest.py`

- `PortfolioSpec` 扩展 `industry_exposure_limit: dict = None`（如 `{"电子": 0.3, "半导体": 0.2}`）
- `PortfolioBacktestEngine.run()` 调仓时检查行业集中度，超限则降低超限行业股票权重

**验收标准**：
- 不加约束时行业集中度可能 50%+；加了约束后行业集中度不超过设定值

#### 任务 3.2.2：换手率约束

- `PortfolioSpec` 扩展 `max_turnover: float = None`（如 0.2 = 每期最多换 20%）
- 调仓时比较目标组合和当前组合差异，超过换手率限制时，按排名顺序选择切换

**验收标准**：
- 年化换手率从 >1000% 可约束到 <500%

#### 任务 3.2.3：板块权限过滤

- `PortfolioSpec` 扩展 `allowed_boards: list = ["main", "gem", "star"]`
- `get_board(symbol)` 判断所属板块（main=主板 00/60, gem=创业板 30, star=科创板 688）
- 调仓时跳过不允许板块的股票

**验收标准**：
- 科创板票被排除时不影响主板选股

---

### V3.3.3：ETF 替代方案（2天，P2）

#### 任务 3.3.1：ETF 数据库构建

**文件**：`commands/factor_lab/etf/etf_universe.py`

- 使用 akshare 获取 ETF 列表（代码、名称、跟踪指数）
- 构建 ETF 跟踪指数映射（如 "半导体" → ["512480", "588290"]）
- 每个 ETF 有主题标签、跟踪指数、规模、日均成交额

**验收标准**：
- 返回 50+ A 股 ETF 的基本信息

#### 任务 3.3.2：ETF 替代逻辑

**文件**：`commands/factor_lab/etf/etf_selector.py`

- 当个股不可交易时（涨停/停牌/ST/权限不足），寻找最佳替代 ETF
- 匹配规则：同主题 > 同行业 > 宽基指数
- 替代 ETF 的份额数量按等市值计算

**验收标准**：
- 所有不可交易股票都有替代 ETF（降级到宽基指数）
- 替代后组合与目标组合的逻辑误差 < 20%

---

### V3.3.4：100股整数倍/尾盘禁开仓（2天，P2）

#### 任务 3.4.1：整手约束强化

- 确保所有订单生成逻辑（order_preview.py, execution_aware_backtester.py, portfolio_backtest.py）统一使用 `lot_size=100` 且尾数截断

**验收标准**：
- 任何订单的股数都是 100 的倍数

#### 任务 3.4.2：尾盘禁开仓规则

- `live/信号` 生成时检查当前时间，14:30 之后生成的买入信号标记为 `blocked: late_session`
- `order_preview.py` 新增 `late_session_check`，14:30 后的买入订单 `tradable=False`

**验收标准**：
- 14:30 后买入单被阻断

---

## V3.4：Paper / Shadow / Live 管线打通（15天，P1）

### V3.4.1：Governed Dry Run 执行（5天，P1）

#### 任务 4.1.1：Gate 状态检查与修复

**文件**：`commands/factor_lab/adaptive/governed_dry_run.py`

- 逐个检查 6 个 Gate 的当前状态
  - Gate1=signal → 信号生成是否正常
  - Gate2=etf → ETF 替代是否可用
  - Gate3=unified → 统一报告是否生成
  - Gate4=rebalance → 调仓差异分析是否可用
  - Gate5=order → 委托预览是否可用
  - Gate6=approval → 风控审批是否可用
- 对每个 FAIL 的 Gate，记录具体原因
- 修复所有 FAIL 后再次运行

**验收标准**：
- 6-Gate 全部通过
- 输出 `completion.json` 标记 `status: completed`

#### 任务 4.1.2：Dry Run 自动化脚本

- 创建 `hermes factor:daily-premarket` 的一键运行入口
- 顺序执行：signal → unified → rebalance → order_preview → approval
- 每个阶段输出 stage_audit.log

**验收标准**：
- 单命令执行全流程，无人工干预
- 全流程 < 5 分钟

---

### V3.4.2：Paper Trading 持续运行（4天，P1）

#### 任务 4.2.1：Paper Trading 持久化

**文件**：`commands/factor_lab/paper/paper_trading.py`

- PaperTradingEngine 支持持续模式（非一次性）
  - 加载上次模拟持仓状态
  - 对比最新信号，生成增量调仓
  - 记录模拟成交（含滑点模型）
  - 更新持仓快照到 CSV 持久化
- 状态文件：`/mnt/d/HermesData/paper_trading/portfolio.csv`

**验收标准**：
- 连续运行 5 天后，持仓状态正确累积
- 模拟交易记录可查

#### 任务 4.2.2：Paper Trading 日收益率跟踪

- 每日计算模拟组合的收益率
- 与同池等权/沪深300 对比
- 每周自动生成对比报告（PDF 或 HTML）

**验收标准**：
- 收益率曲线持续更新
- 周报显示 vs 基准对比

#### 任务 4.2.3：Paper Trading 开通 cron 任务

- 创建 cron 任务 `hermes factor:paper-trade-standing`
- 每日 09:05 自动运行（盘前信号已生成后）
- notify_on_complete = 企业微信通知

**验收标准**：
- cron 每日自动执行
- 企业微信通知每日模拟盘状态

---

### V3.4.3：Shadow Forward 持续运行（3天，P2）

#### 任务 4.3.1：Shadow Forward 自动化

**文件**：`commands/factor_lab/adaptive/shadow_forward.py`

- `ShadowForward.run_standing()` 持续模式
  - 每日运行，对比 baseline（同池等权/沪深300）vs shadow（策略）的当日收益
  - 生成 rolling 30 天对比视图
  - 如果 shadow 连续 5 天跑输 baseline，触发告警

**验收标准**：
- 每日自动运行
- 30 天滚动对比报告
- 跑输告警触发

---

### V3.4.4：复盘报告（3天，P2）

#### 任务 4.4.1：每日复盘报告生成

**文件**：新建 `commands/factor_lab/reports/daily_review.py`

- 输入：当日计划订单 vs 实际成交（模拟）vs 未成交原因
- 输出复盘报告 HTML：
  - 当日期望调仓 vs 实际调仓
  - 风控拦截计算（多少笔被阻断）
  - 模拟组合 vs 基准对比
  - 滑点统计

**验收标准**：
- 每天 15:30 生成复盘报告
- HTML 含交易对比表

---

## V3.5：风控系统实盘化（15天，P0→P1）

### V3.5.1：KillSwitch 守护进程（3天，P0）

#### 任务 5.1.1：Risk Sentinel 常驻

**文件**：新建 `commands/factor_lab/risk/risk_sentinel.py`

- `RiskSentinel` 类持续运行（作为后台进程）
  - 每 30 秒检查数据新鲜度
  - 每 60 秒检查行情延迟
  - 每次管线入口调用 `check_action()`
- 所有规则状态保存在 `/mnt/d/HermesData/risk_sentinel/state.json`

**验收标准**：
- `KillSwitch.trigger("data_freshness")` 阻止后续所有管线操作
- 状态持久化

#### 任务 5.1.2：GateEngine 集成

**文件**：`commands/factor_lab/core/gate.py`

- `GateEngine` 内部持有 `KillSwitch` 引用
- `GateEngine.add_check()` 时自动调用 `KillSwitch.check_action()`
- 如果 KillSwitch 触发，`GateEngine.add_check()` 返回 `{"allowed": false, "blocked": true}`

**验收标准**：
- 触发 KillSwitch 后，所有 Gate 检查自动返回 blocked

---

### V3.5.2：ST/退市/监管名单（2天，P0）

#### 任务 5.2.1：ST 名单实时获取

**文件**：`commands/factor_lab/risk/pretrade_risk_check.py`

- 使用 akshare `stock_st_em()` 获取实时 ST/*ST 名单
- 每日开盘前自动更新
- 缓存到 `/mnt/d/HermesData/st_watchlist/stocks.json`

**验收标准**：
- ST 名单 >100 只
- 识别率 100%（覆盖全部 ST）

#### 任务 5.2.2：监管事件数据库

- 使用 akshare/东方财富接口获取：监管函、关注函、问询函、立案调查
- 构建黑名单（收到立案调查的公司）
- 黑名单上的股票在 pretrade_risk_check 中标记为 `regulatory_risk`
- 缓存到 `/mnt/d/HermesData/regulatory_watchlist/`

**验收标准**：
- 被立案调查的公司被自动标记
- 黑名单实时更新

---

### V3.5.3：多层止损/仓位控制（4天，P1）

#### 任务 5.3.1：单票风控规则实现

**文件**：`commands/factor_lab/risk/risk_rules.py`

- `single_stock_drawdown`：单票 -5% → weight 减半；-8% → 强制止损
- `single_stock_concentration`：单票 <= 25%
- `daily_order_limit`：单日最多买入 50 万元（小资金限制）
- `low_liquidity_rule`：日成交额 < 5000 万元 → 禁止买入

**验收标准**：
- 触发时 KillSwitch.trigger() 被调用
- 规则检查有日志记录

#### 任务 5.3.2：组合风控规则

- `portfolio_daily_loss`：组合当日亏损 2% → 停止开新仓
- `portfolio_daily_loss_severe`：组合当日亏损 3% → 只允许减仓
- `portfolio_drawdown`：最大回撤 8% → 进入防守状态；12% → 停止交易
- `industry_concentration`：单行业 <= 30%

**验收标准**：
- 触发时输出风控状态
- 防守状态下所有买入信号被阻断

---

### V3.5.4：数据异常检测（3天，P1）

#### 任务 5.4.1：行情延迟检测

**文件**：`commands/factor_lab/risk/risk_rules.py`

- 实时检查最新行情时间戳 vs 当前时间
- 延迟 > 60 秒 → `KillSwitch.trigger("market_data_lag")`，停止所有交易操作
- 延迟 > 300 秒 → 发送企业微信告警

**验收标准**：
- 行情中断时 KillSwitch 自动触发
- 恢复后自动释放（auto_recovery）

#### 任务 5.4.2：价格异常检测

- 单日涨跌幅 > 15% 的股票（非 ST/创业板/科创板）标记为 `price_anomaly`
- 价格与前一日收盘差异 > 20% 需人工确认
- 缺失 > 30% 的因子数据时标记 `data_insufficient`

**验收标准**：
- 异常价格被标记，对应的订单被阻断

---

### V3.5.5：企业微信风控告警（3天，P3）

#### 任务 5.5.1：风控事件推送

**文件**：`commands/factor_lab/notify.py`

- `notify_risk_event(event_type, detail)` 推送风控事件到企业微信
- 事件类型：KillSwitch 触发、最大回撤触发、行情中断
- 格式：颜色标记（红=BLOCKER、黄=WARNING、绿=已恢复）

**验收标准**：
- KillSwitch 触发时企业微信在 60 秒内收到推送

---

## V3.6：LLM 因子挖掘升级（20天，P2）

### V3.6.1：因子失败归因数据库（5天，P2）

#### 任务 6.1.1：因子失败记录 Schema

**文件**：新建 `commands/factor_lab/alpha/failure_db.py`

- `FailureRecord` dataclass：
  - factor_name, expression, hypothesis
  - reason（IC衰减/跑输等权/过拟合）
  - ic_curve（各窗口 IC 序列）
  - market_regime（运行期间市场状态：牛/熊/震荡/结构）
  - failed_at, created_by
- 持久化到 `/mnt/d/HermesData/alpha_failures/`

**验收标准**：
- 可存储结构化失败记录
- 支持按原因/市场状态查询

#### 任务 6.1.2：RetirementEngine 写失败记录

**文件**：`commands/factor_lab/alpha/retirement_engine.py`

- `auto_retire()` 或 `retire()` 时自动创建 `FailureRecord`
- 记录 IC 衰减曲线和退役时市场环境

**验收标准**：
- 每个退役的 Alpha 有对应的失败记录

---

### V3.6.2：LLM 参考历史失败模式（5天，P2）

#### 任务 6.2.1：Prompt 增强

**文件**：`commands/factor_lab/alpha/llm_alpha_discovery.py`

- 生成 AlphaSpec 时，在 prompt 中加入最近 10 个失败因子的原因分布
- 如果最近 5 个因子都因 IC 衰减被淘汰，prompt 中强调要求设计低衰减因子

**验收标准**：
- LLM 生成的因子失败率逐步下降

---

### V3.6.3：LLM 参与因子后分析（5天，P2）

#### 任务 6.3.1：因子诊断 Prompt

**文件**：`commands/factor_lab/research_loop.py`

- 实现 LLM 因子诊断接口：
  - 输入：因子表达式 + IC 报告 + 同池等权对比 + 暴露分析 + Walk-Forward
  - 输出：因子诊断报告（成功原因/失败原因/什么条件下有效/改进建议）
- 使用 `llm:ask` 或 `delegate_task` 调用 LLM

**验收标准**：
- 诊断报告包含有意义的分析
- 改进建议可转化为新因子

---

### V3.6.4：全自动因子研究闭环（5天，P2）

#### 任务 6.4.1：ResearchLoop 自动化增强

**文件**：`commands/factor_lab/research_loop.py`

- 完善自动循环的完整流程：
  1. LLM 生成候选因子（3-5 个）
  2. 批量回测评估（IC + IR + 同池等权 + 暴露分析）
  3. LLM 分析结果，判断哪些因子值得保留
  4. 根据分析调整研究方向（收敛方向）
  5. 保留最优因子，注册到 Alpha Registry
  6. 重复直到收敛（连续 N 轮无改善）
- 自动循环限制最多 10 轮，防止无限执行

**验收标准**：
- 自动运行 3 轮后得到至少 1 个 beats_peer 的因子
- 循环在 10 轮内收敛
- 最优因子自动注册到 Alpha Registry

---

## 优先级汇总

| 阶段 | 任务 | 估计人天 | 优先级 | 依赖 |
|---|---|---|---|---|
| V3.1.1 | 真实 benchmark 指数行情 | 2 | P0 | — |
| V3.1.2 | 因子可信度验证 | 4 | P1 | V3.1.1 |
| V3.1.3 | 数据质量升级 | 2 | P2 | — |
| V3.2.1 | 因子正交化 | 3 | P1 | — |
| V3.2.2 | 基本面因子接入 | 3 | P2 | — |
| V3.2.3 | 资金流因子接入 | 3 | P2 | — |
| V3.2.4 | 行业因子 | 3 | P2 | — |
| V3.2.5 | AlphaSpec 元数据 | 2 | P2 | — |
| V3.3.1 | 因子加权组合 | 3 | P1 | V3.2.1 |
| V3.3.2 | 风控约束集成 | 3 | P1 | — |
| V3.3.3 | ETF 替代 | 2 | P2 | — |
| V3.3.4 | 整手/尾盘规则 | 2 | P2 | — |
| V3.4.1 | Governed Dry Run | 5 | P1 | V3.1.1 |
| V3.4.2 | Paper Trading 持续运行 | 4 | P1 | V3.4.1 |
| V3.4.3 | Shadow Forward 自动化 | 3 | P2 | V3.4.1 |
| V3.4.4 | 复盘报告 | 3 | P2 | V3.4.2 |
| V3.5.1 | KillSwitch 守护进程 | 3 | P0 | — |
| V3.5.2 | ST/监管名单 | 2 | P0 | — |
| V3.5.3 | 多层止损/仓位控制 | 4 | P1 | V3.5.1 |
| V3.5.4 | 数据异常检测 | 3 | P1 | V3.5.1 |
| V3.5.5 | 企业微信风控告警 | 3 | P3 | V3.5.1 |
| V3.6.1 | 因子失败归因 | 5 | P2 | — |
| V3.6.2 | LLM 参考历史失败 | 5 | P2 | V3.6.1 |
| V3.6.3 | LLM 因子诊断 | 5 | P2 | — |
| V3.6.4 | 自动因子研究闭环 | 5 | P2 | V3.6.1-3 |

**总计**：约 80 人天（16 周单人全职 / 8 周双人并行）

**最短实盘路径**（P0 最快达标）：
1. V3.1.1 真实 benchmark（2天）
2. V3.5.1 KillSwitch 守护进程（3天）
3. V3.5.2 ST/监管名单（2天）
4. V3.5.3 多层止损/仓位控制（4天，可与前3并行）
5. V3.4.1 Governed Dry Run（5天）

→ **16 天**后可小资金实盘（满足 P0 要求）。
