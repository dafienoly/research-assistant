# 数据血缘报告

> **生成时间**: 2026-07-08 23:40 CST
> **审计范围**: Hermes 投研系统所有数据源和字段
> **审计方法**: 代码审查 / 数据目录检查 / 配置审计 / 已有报告分析

---

## 1. 数据源总览

| 数据源 | 状态 | 用途 | 关键代码路径 |
|-------|------|------|-------------|
| Tushare Pro (token 配置) | ✅ 活跃 | 行情/财务/估值/资金/事件主数据源 | `commands/data_providers/tushare/tushare_market.py` |
| | | | `commands/data_providers/tushare/tushare_fina.py` |
| | | | `commands/data_providers/tushare/tushare_stock.py` |
| | | | `commands/data_providers/tushare/tushare_fund_flow.py` |
| | | | `commands/data_providers/tushare/tushare_event.py` |
| | | | `commands/factor_lab/data/tushare_client.py` |
| Baostock | ❌ 未接入 | 免费兜底/交叉验证 | — (仅在 roadmap 中列出) |
| AkShare | ❌ 未接入 | 免费兜底/交叉验证 | — (仅在 roadmap 中列出) |
| pool.csv | ⚠️ 静态文件 | AI 图谱 315 只候选标的 | `data/market/pool.csv` (Windows Codex Data Hub) |
| ai_chainmap_watchlist_tags.csv | ⚠️ 静态文件 | AI 产业链标签 | `data/tags/` (Windows) |
| semiconductor_chain_tags.csv | ⚠️ 静态文件 | 半导体核心标签 (21 只) | `data/tags/` (Windows) |

---

## 2. Tushare 数据提供商覆盖

报告来源: `data/audit/health/health_report.json` (2026-07-08 23:00 CST)

| Provider | 状态 | 最新日期 | 数据类型数 | 错误 |
|---------|------|---------|-----------|------|
| tushare_market | ✅ ok | 2026-07-07 | 4 | 无 |
| tushare_fina | ✅ ok | 2026-07-07 | 4 | 无 |
| tushare_stock | ✅ ok | 2026-07-07 | 4 | 无 |
| tushare_fund_flow | ✅ ok | 2026-07-07 | 4 | 无 |
| tushare_event | ✅ ok | 2026-07-07 | 4 | 无 |

**覆盖率**: 100% (5/5 providers ok), 20 个数据类型

---

## 3. 本地数据文件清单

### 3.1 市场数据 (`data/market/`)

| 文件 | 行数 | 数据说明 |
|------|------|---------|
| `pool.csv` | 315 | AI 图谱候选股票池 (单源/单向) |
| `live_snapshot.csv` | ~300 | 实时快照 (已过期) |
| `daily_kline/688012_daily_kline.csv` | ~247 | 中微公司日线 (约1年) |
| `daily_kline/688072_daily_kline.csv` | ~247 | 拓荆科技日线 |
| `daily_kline/688120_daily_kline.csv` | ~247 | 华海清科日线 |
| `daily_kline/002371_daily_kline.csv` | ~247 | 北方华创日线 |
| `daily_kline/300604_daily_kline.csv` | ~247 | 长川科技日线 |
| `daily_kline/159516_daily_kline.csv` | ~247 | 半导体设备ETF日线 |
| `daily_kline/512480_daily_kline.csv` | ~247 | 半导体ETF日线 |
| `daily_kline/588290_daily_kline.csv` | ~247 | 科创芯片ETF日线 |
| `daily_kline/561980_daily_kline.csv` | ~247 | 芯片龙头ETF日线 |
| `daily_kline/*_hist.csv` | ~247 | 历史K线备份 |
| `adjust_factor.csv` | ~500 | 复权因子 |

### 3.2 基本面数据 (`data/fundamentals/`)

| 文件 | 行数 | 数据说明 |
|------|------|---------|
| `financial_snapshot.csv` | ~300 | 财务快照 (仅2期: 2025Q4, 2026Q1) |
| `profit_data.csv` | ~317 | 利润表数据 |
| `balance_data.csv` | ~300 | 资产负债表 |
| `cash_flow_data.csv` | ~300 | 现金流量表 |
| `forecast_report.csv` | ~100 | 业绩预告 |
| `fundamentals_timeseries.csv` | ~3000 | 基本面时间序列 |
| `fund_flow_timeseries.csv` | ~5000 | 资金流时间序列 |
| `announcements_extracted.csv` | ~200 | 公告提取 |

### 3.3 标签数据 (`data/tags/`)

| 文件 | 行数 | 数据说明 |
|------|------|---------|
| `semiconductor_chain_tags.csv` | 21 | 半导体产业链标签 (仅21只) |
| `stock_theme_tags.csv` | 44 | 股票主题标签 |
| `stock_industry.csv` | ~500 | 行业分类 |
| `industry_chain_tags.csv` | ~100 | 产业链标签 |

### 3.4 事件/情绪/资金数据

| 文件 | 行数 | 数据说明 |
|------|------|---------|
| `events/policy_events.csv` | ~100 | 政策事件 |
| `events/preopen_events.csv` | ~50 | 盘前事件 |
| `north_flow_timeseries.csv` | 32512 | 北向资金 (覆盖较全) |
| `margin_timeseries.csv` | ~5000 | 两融数据 |
| `news_sentiment_timeseries.csv` | ~2000 | 新闻情绪 |
| `event_timeseries.csv` | ~1000 | 事件时间序列 |

### 3.5 审计数据 (`data/audit/`)

| 文件 | 数据说明 |
|------|---------|
| `data_freshness_report.json` | 数据新鲜度状态 (overall: stale) |
| `data_gap_report.json` | 数据缺口报告 (total_gaps: 0) |
| `health/health_report.json` | 数据源健康状态 (5/5 ok) |
| `health/coverage.json` | 覆盖率统计 |
| `fetch_log.jsonl` | 采集日志 |

### 3.6 持仓数据 (`data/positions/`)

| 文件 | 数据说明 |
|------|---------|
| `current_positions.csv` | 当前持仓 (3只股票 + 现金, 约5万市值) |

---

## 4. 字段级血缘

### 4.1 日线行情字段

| 字段 | 来源 | 用于 |
|------|------|------|
| trade_date/date | Tushare daily | 所有因子计算, 基准收益率 |
| ts_code/symbol | Tushare stock_basic | 所有模块的标的标识 |
| open/high/low/close | Tushare daily | 因子计算 (动量/反转/波动率) |
| pre_close | Tushare daily | 收益率计算 |
| vol/volume | Tushare daily | 成交量因子 |
| amount | Tushare daily | 成交额因子, 流动性估计 |
| adj_factor | Tushare adj_factor | 复权处理 |

### 4.2 每日指标字段

| 字段 | 来源 | 用于 |
|------|------|------|
| turnover_rate | Tushare daily_basic | 换手率因子 |
| pe/pe_ttm/pb/ps | Tushare daily_basic | 估值因子 |
| total_mv/circ_mv | Tushare daily_basic | 市值因子, 匹配对照 |
| total_share/float_share | Tushare daily_basic | 股本信息 |

### 4.3 股票池字段

| 字段 | 来源 | 用于 |
|------|------|------|
| ts_code/symbol/name | Tushare stock_basic | U0 全A基础池 |
| board/market | Tushare stock_basic | U1 板块权限标记 |
| is_st | Tushare namechange | U1 ST过滤 |
| is_suspended | Tushare suspend_d | U1 停牌过滤 |
| up_limit/down_limit | Tushare stk_limit | U1 涨跌停判断 |
| source_atlas/chain_layer | pool.csv + ai_chainmap | U2 广义AI池 |
| core_score/subsector | semiconductor_chain_tags | U3 半导体核心池 |
| matched_stocks | universes.py 匹配算法 | U4 对照池 |

### 4.4 基准收益率

| 基准 | 计算方式 | 数据来源 |
|------|---------|---------|
| semiconductor_ew | U3 内所有标的等权平均 | daily_kline/*.csv |
| semiconductor_core_ew | 同 semiconductor_ew | daily_kline/*.csv |
| matched_control_ew | U4 内所有标的等权平均 | daily_kline/*.csv |
| ew_a_share | U0 等权 (限制 1000 只) | daily_kline/*.csv |
| ew_tradable | U1 可交易池等权 | daily_kline/*.csv |
| etf_basket_ew | ETF 替代池等权 | daily_kline/*.csv |

---

## 5. 数据完整性问题

### 5.1 关键缺口 (P0)

1. **全 A 日线缺失**: 当前仅 6 只标的 + 5 只 ETF, 远未覆盖全 A (~5000 只)
2. **历史深度不足**: 仅约 1 年 (2025-03 ~ 2026-04), 数据窗口 247 个交易日
3. **财务数据仅 2 期**: 仅 2025Q4 和 2026Q1, 无法做跨期对比/趋势分析
4. **生存偏差**: 无退市股票行情, 不能做生存偏差检验
5. **pool.csv 单源**: 仅来自 aichainmap.com/atlas, 无交叉验证

### 5.2 新鲜度问题

来源: `data/audit/data_freshness_report.json`

| 文件 | 状态 | 实际延迟 | 阈值 |
|------|------|---------|------|
| market/pool.csv | stale | 102184s | 86400s |
| market/live_snapshot.csv | stale | 103335s | 60s |
| events/preopen_events.csv | stale | 103584s | 64800s |
| intraday/live_snapshot_priority.csv | stale | 437322s | 60s |

### 5.3 数据缺口报告

来源: `data/audit/data_gap_report.json`

- **total_gaps**: 0
- **blocking_gaps**: 0
- **说明**: 缺口检查当前仅检查已注册的数据文件, 未检查缺失的预期文件

---

## 6. 已知限制

1. **数据源单一**: 仅有 Tushare Pro, 无 baostock/akshare 兜底
2. **无分钟数据**: 无 Level-1/Level-2 分钟或 tick 数据 (低频研究不需要, 但影响执行层面)
3. **无研报语义数据**: V4.10 规划的 Tushare 券商研报库未接入
4. **uni_verses.json 未持久化**: 构建后写入但被 git 忽略, 每次需重新构建
5. **数据新鲜度检查过松**: market/pool.csv 阈值设为 86400s (24h), 实际盘前可用性重要
6. **cross-platform 路径**: KLINE_DIR 指向 `/mnt/c/Users/ly/.codex/data/a-share-data-hub/`, 是 Windows 侧只读挂载
