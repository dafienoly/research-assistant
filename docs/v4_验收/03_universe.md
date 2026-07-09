# 股票池报告 (U0-U4 覆盖/纯度)

> **生成时间**: 2026-07-08 23:40 CST
> **审计依据**: `commands/universes.py` (1192 行) + `data/universes.json` 构建逻辑
> **数据截止**: 2026-07-07 (Tushare 最新交易日)

---

## 1. 股票池体系总览

| 池 | 名称 | 目标标的数 | 当前状态 | 关键文件 |
|---|------|-----------|---------|---------|
| U0 | 全 A 基础池 | 全 A (约5000+) | ✅ 可构建 (由 Tushare stock_basic 实时构建) | `universes.py:build_u0()` |
| U1 | 用户可交易池 | 约4000-4500 | ✅ 可构建 (从 U0 派生, 含权限/ST/停牌/流动性标记) | `universes.py:build_u1()` |
| U2 | AI/半导体广义池 | 315-500 | ✅ 可构建 (pool.csv + ai_chainmap) | `universes.py:build_u2()` |
| U3 | 半导体核心池 | 80-150 | ⚠️ 部分 (仅 21 只标签, 缺口大) | `universes.py:build_u3()` |
| U4 | 匹配对照池 | 关于 U3 | ✅ 可构建 (从 U3 按市值/波动率/流动性匹配) | `universes.py:build_u4()` |
| ETF | ETF 替代池 | 15 | ✅ 硬编码 15 只 ETF | `universes.py:ETF_REPLACEMENT_POOL` |

**注意**: `data/universes.json` 为空文件 — 运行时需调用 `build_all()` 后写入。

---

## 2. 各池详细分析

### 2.1 U0 全 A 基础池

**数据来源**: Tushare `stock_basic` (list_status=L/D/P)
**构建函数**: `universes.py:build_u0()` (第 151-267 行)

**字段**:
```python
ts_code, symbol, name, exchange, board, list_date, delist_date,
is_listed, industry, concepts, total_mv, float_mv
```

**当前能力**:
- 从 Tushare 拉取所有上市/退市/暂停股票
- 获取最新交易日市值 (daily_basic)
- 获取概念板块映射
- 去除 ST 标记 (通过名称前缀 `_is_st_from_name`)

**限制**: 计算过程中需调用 Tushare API, 需 token 有效; 无本地缓存快照

### 2.2 U1 用户可交易池

**数据来源**: U0 + Tushare `stk_limit`, `suspend_d`, `namechange`, `daily_basic`
**构建函数**: `universes.py:build_u1()` (第 274-434 行)

**交易性判断逻辑**:
| 阻挡条件 | 数据来源 | 阈值 |
|---------|---------|------|
| ST/*ST 标记 | Tushare namechange + 名称前缀 | 任意 ST 即阻挡 |
| 停牌 | Tushare suspend_d | 当日停牌即阻挡 |
| 涨停封板 | Tushare stk_limit | pct_to_up 接近涨停阈值 |
| 北交所权限 | board == "北交所" | 标记权限受限 |
| 低流动性 | daily_basic 近20日均额 | avg_amount_20d < 500万元 |

**当前能力**:
- 正确标记主板/创业板/科创板/北交所
- 支持 tradable_by_user + trade_block_reason
- 日均成交额 20 日滚动计算

### 2.3 U2 AI/半导体广义池

**数据来源**: `pool.csv` (315 只, Windows Data Hub) + `ai_chainmap_watchlist_tags.csv`
**构建函数**: `universes.py:build_u2()` (第 441-500+ 行)

**纯度分析** (来自审计报告):
- pool.csv 收录 315 只 AI 图谱标的
- 数据源单一: 仅来源于 aichainmap.com/atlas 的 AI 产业链图谱
- 口径极宽: 包含美的集团(L3 DCIM)、牧原股份(L5 AI应用)、中国平安(L5)、莲花控股(算力租赁) 等与半导体无实质关联的标的
- **标记字段**: source_atlas, atlas_sector, layer, primary_type, confidence, type_tags

### 2.4 U3 半导体核心池

**数据来源**: `semiconductor_chain_tags.csv` (仅 21 只) + U2 中半导体重叠
**构建函数**: `universes.py:build_u3()` (需查看具体实现)

**覆盖不足**:
- 目标 80-150 只, 当前仅 21 只有明确半导体标签
- 缺少: 江丰电子(300666)、圣邦股份(300661)、韦尔股份(603501) 等核心半导体股
- stock_theme_tags.csv 只有 44 行标记
- 缺少产业链位置信息 (设备/材料/设计/封测/EDA/IP)

**建议字段**:
```python
semiconductor_subsector, core_score, domestic_substitution_score,
supply_chain_position, is_equipment, is_material, is_design,
is_foundry, is_packaging, is_eda, is_ip, is_storage
```

### 2.5 U4 匹配对照池

**构建函数**: `universes.py:build_u4()`

**匹配规则** (代码中定义):
```python
float_mv ± 20%          # 市值匹配
avg_amount_20d ± 30%    # 成交额匹配
volatility_60d ± 20%    # 波动率匹配
exclude U2/U3           # 排除 AI/半导体标的
prefer same board       # 优先同板块
```

**当前能力**: 框架完整, 但受限于 U3 池短缺和数据覆盖不足

### 2.6 ETF 替代池

**硬编码清单** (`universes.py` 第 62-78 行, 15 只 ETF):

| ts_code | 名称 | 跟踪指数 |
|---------|------|---------|
| 512480.SH | 半导体ETF | 中证全指半导体产品与设备指数 |
| 512760.SH | 芯片ETF | 中华交易服务芯片产业指数 |
| 159813.SZ | 半导体ETF | 国证半导体芯片指数 |
| 159995.SZ | 芯片ETF | 国证芯片指数 |
| 588000.SH | 科创50ETF | 上证科创板50成份指数 |
| 588050.SH | 科创芯片ETF | 上证科创板芯片指数 |
| 159859.SZ | 科创芯片ETF | 国证半导体芯片指数 |
| 515050.SH | AI算力ETF | 中证人工智能主题指数 |
| 517050.SH | 5G通信ETF | 中证5G通信主题指数 |
| 159865.SZ | 消费电子ETF | 中证消费电子主题指数 |
| 159997.SZ | 电子ETF | 中证电子指数 |
| 512480.SH | 半导体设备材料ETF | 中证半导体材料设备指数 |
| 159801.SZ | 芯片龙头ETF | 国证芯片指数 |
| 159967.SZ | 科创创业50ETF | 中证科创创业50指数 |
| 588060.SH | 科创信息技术ETF | 上证科创板新一代信息技术指数 |

---

## 3. 股票池 CLI 命令

```bash
# 构建所有股票池
python3 hermes_cli.py universe:build

# 列出所有池
python3 hermes_cli.py universe:list

# 查看指定池详情
python3 hermes_cli.py universe:show U0
python3 hermes_cli.py universe:show U3
python3 hermes_cli.py universe:show ETF

# 审计所有池
python3 hermes_cli.py universe:audit
```

---

## 4. 纯度与覆盖总结

| 指标 | 当前值 | 目标值 | 状态 |
|------|-------|-------|------|
| U0 全 A 覆盖 > 3000 只 | 可构建 (依赖 API) | >3000 | ✅ 框架正常 |
| U1 可交易标记正确 | 可构建 | - | ✅ 框架正常 |
| U2 候选池 315 只 | 315 | 315-500 | ✅ 数量达标 |
| U2 纯度 (真正半导体相关) | ~30% | >70% | ❌ 含大量泛科技标的 |
| U3 核心池数量 | 21 | 80-150 | ❌ 严重不足 |
| U3 产业链标签完整 | 仅基础 | 细分方向/核心度 | ❌ 缺失 |
| U4 匹配对照池 | 可构建 | 每只 U3 匹配 1-3 只 | ⚠️ 框架有但受限 |
| ETF 替代池 | 15 只 | ≥10 只 | ✅ 达标 |
| universes.json 持久化 | 空文件 | 可加载 | ❌ 需运行时构建 |

---

## 5. 已知限制

1. **U3 半导体核心池严重不足**: 仅 21 只有明确标签, 目标 80-150 只, 缺口 60-130 只
2. **U2 池纯度低**: 315 只中大量泛科技/非半导体标的, 无置信度分层
3. **universes.json 未持久化**: 每次使用基准/因子验证前需 re-build
4. **日 K 线数据受限**: 即使池构建完成, 实际可用数据仅 ~6 只标的 + ~5 只 ETF
5. **U4 匹配受 U3 限制**: U3 仅 21 只, 匹配出有意义的 U4 池有限
6. **ETF 替代池未对接实际行情**: ETF 基准收益率为空 (无对应 K 线文件)
