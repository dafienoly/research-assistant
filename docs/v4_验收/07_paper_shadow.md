# Paper / Shadow Trading 报告

> **生成时间**: 2026-07-08 23:40 CST
> **审计依据**: `commands/factor_lab/paper/standing_paper_trading.py` (989 行)
>                                `commands/factor_lab/paper/shadow_trading.py` (657 行)
> **版本**: V4.8 Paper / Shadow Trading 闭环
> **验收范围**: 模拟交易(Paper) + 影子交易(Shadow) + 成本模型 + 可交易性检查 + NOT_READY判定

---

## 1. 系统架构

### 1.1 Paper Trading (模拟交易)

**引擎**: `StandingPaperTrading` (`standing_paper_trading.py` L33-989)
**V4.8 增强**: `PaperTradingV4` (同文件)

**核心功能**:
1. 加载上次模拟持仓状态 (持久化到 JSON)
2. 对比最新信号, 生成增量调仓
3. 记录模拟成交 (保守滑点模型 + 交易费用)
4. 更新持仓快照到文件
5. 计算日收益率

**持久化位置**: `/mnt/d/HermesData/paper_trading/`
| 文件 | 格式 | 说明 |
|------|------|------|
| `portfolio.json` | JSON | 持仓和现金状态 (进程重启不丢失) |
| `trades.jsonl` | JSONL | 逐笔成交记录 |
| `equity.csv` | CSV | 日权益曲线 |

**成本模型** (源代码 L43-44, 99-110):
```python
COMMISSION_RATE = 0.0003      # 手续费 0.03%
SLIPPAGE_BPS = 10             # 滑点 10bps (0.1%)
STAMP_TAX_RATE_SELL = 0.001   # 印花税 0.1% (仅卖出)

# 滑点计算: 买入成交价 = price × (1 + 0.001), 卖出成交价 = price × (1 - 0.001)
# 买入成本: 成交金额 × 0.0003 (佣金) + 无印花税
# 卖出成本: 成交金额 × (0.0003 佣金 + 0.001 印花税)
```

**增量调仓逻辑** (`PaperTradingV4.run_paper`, 同文件):
```text
1. portfolio_builder 输出组合推荐 (stocks + weights)
2. 对比当前持仓, 生成调仓列表
    └─ 卖: 持仓中不在目标列表的标的
    └─ 买: 目标中尚未持有的标的
3. 对每笔调仓做可交易性检查 (涨跌停/停牌/资金/100股整数倍)
4. 按收盘价模拟成交, 应用滑点+费用
5. 更新 portfolio.json / trades.jsonl / equity.csv
6. 返回 {plan, execution, tradability_check, risk_interceptions, pnl}
```

### 1.2 Shadow Trading (影子交易)

**引擎**: `ShadowTradingEngine` (`shadow_trading.py` L44-657)

**与 Paper Trading 的区别**:
- 不产生真实持仓 (只观察)
- 对比: 策略计划 vs 真实行情
- 统计: 实际可买/可卖/被风控拦截
- 输出: 相对半导体同池等权表现
- 输出: NOT_READY 判定

**核心流程** (`run_shadow` 方法, L79-150):

```
1. 运行 PaperTradingV4 → paper_result              (L113)
2. 可交易统计: 涨跌停/停牌/资金/100股整数倍       (L118, _analyze_tradability)
3. 风控拦截统计: by_reason / by_stage              (L121, _analyze_risk_interceptions)
4. 市场行情概况: 涨跌家数/均值/成交量              (L124, _build_market_context)
5. 相对半导体等权基准表现                           (L127, _calc_relative_performance)
6. NOT_READY 判定: excess_return < 0 → NOT_READY   (L131, _check_not_ready)
7. 汇总摘要                                         (L135, _build_summary)
```

**基准**: `BENCHMARK_NAME = "semiconductor_ew"` (L55)

**NOT_READY 判定逻辑** (L351-356):
```python
def _check_not_ready(self, performance: dict) -> bool:
    excess = performance.get("excess_return_pct")
    if excess is None:
        return True  # 无基准数据默认 NOT_READY
    return excess < 0
```

**基准加载策略** (`_get_benchmark_return_for_date`, L278-310):
1. 优先从 `benchmarks_v4.get_benchmark_returns("semiconductor_ew")` 读取
2. 失败则从 market_data 中筛选 U3 (半导体核心池) 标的估算等权收益率
3. 若均不可用, 返回 None → NOT_READY

### 1.3 数据流

```
portfolio_builder.py ──→ 组合推荐 (stocks + weights)
        │
        ▼
  PaperTradingV4 (standing_paper_trading.py)
        │
        ├──→ portfolio.json (持仓状态)
        ├──→ trades.jsonl (成交记录)
        ├──→ equity.csv (权益曲线)
        │
        ▼
  ShadowTradingEngine (shadow_trading.py)
        │
        ├──→ tradability (可交易统计: 受阻原因/数量)
        ├──→ risk_interceptions (风控拦截: 按原因/阶段)
        ├──→ performance (vs semiconductor_ew 基准)
        └──→ not_ready flag (跑输同池 = NOT_READY)
```

---

## 2. CLI 命令

```bash
# Paper Trading (V4.8)
python3 hermes_cli.py paper:v4-run                   # 运行 Paper Trading
python3 hermes_cli.py paper:v4-run --date 2026-07-08 # 指定日期
python3 hermes_cli.py paper:v4-run --capital 50000   # 指定资金
python3 hermes_cli.py paper:v4-run --top-n 10        # 指定持有数
python3 hermes_cli.py paper:v4-dashboard             # Paper Trading 看板

# Shadow Trading (V4.8)
python3 hermes_cli.py shadow:v4-run                  # 运行 Shadow Trading
python3 hermes_cli.py shadow:v4-run --date 2026-07-08 --capital 50000 --top-n 10
python3 hermes_cli.py shadow:v4-report               # 多日 Shadow Trading 报告
```

---

## 3. 关键输出结构

### 3.1 Paper Trading 输出

`PaperTradingV4.run_paper()` 返回:
```python
{
    "date": str,                      # 交易日
    "plan": {
        "stocks": [{"symbol", "name", "weight", "is_tradable", "block_reasons"}],
        "weights": [...],
    },
    "execution": {
        "n_filled": int,              # 实际成交数
        "n_missed": int,              # 未成交数
        "fills": [{"symbol", "side", "shares", "price", "cost"}],
    },
    "tradability_check": {
        "plannable": int, "blocked": int,
        "details": [{"symbol", "plannable", "reasons"}],
    },
    "risk_interceptions": [{"symbol", "reason", "stage"}],
    "pnl": {
        "total_return_pct": float,
        "n_holdings": int,
        "cash_remaining": float,
    },
}
```

### 3.2 Shadow Trading 输出

`ShadowTradingEngine.run_shadow()` 返回:
```python
{
    "date": str,
    "plan":                   # 同 paper_result["plan"],
    "execution":              # 同 paper_result["execution"],
    "pnl":                    # 同 paper_result["pnl"],
    "tradability": {
        "n_total": int,       # 计划总数
        "n_tradable_planned": int,   # 实际可交易数
        "n_non_tradable_planned": int,
        "n_check_plannable": int, "n_check_blocked": int,
        "tradable_weight_pct": float,
        "blocked_by_reason": {"涨停": 2, "停牌": 1},
        "details": [{"symbol", "name", "is_tradable", "weight_pct", "block_reasons"}],
    },
    "risk_interceptions": {
        "total_interceptions": int,
        "distinct_symbols_blocked": int,
        "by_reason": {"涨停": 2, "停牌": 1},
        "by_stage": {"pretrade": 3},
        "details": [{"symbol", "reason", "stage"}],
    },
    "market_context": {
        "date": str, "n_stocks_available": int,
        "avg_close": float, "median_close": float,
        "n_up": int, "n_down": int,
    },
    "performance": {
        "date": str,
        "strategy_return_pct": float,
        "benchmark_name": "semiconductor_ew",
        "benchmark_label": "半导体同池等权",
        "benchmark_return_pct": float,
        "excess_return_pct": float,
        "vs_benchmark": "跑赢"|"跑输",
    },
    "not_ready": bool,
    "summary": "📅 2026-07-08 | 计划10只 | 可交易8只 | 风控拦截3次 | 策略+0.52% | 基准+0.38% | 跑赢",
}
```

---

## 4. 当前状态

### 4.1 当前持仓

来源: `data/positions/current_positions.csv`;

| 标的 | 代码 | 股数 | 成本价 | 现价 | 市值 | 权重 | 来源 |
|-----|------|------|-------|------|------|------|------|
| 新华联 | 000620 | 200 | 3.20 | 3.60 | 720 | 1.4% | manual |
| 星网锐捷 | 002396 | 100 | 22.50 | 23.40 | 2340 | 4.7% | manual |
| 韦尔股份 | 603501 | 100 | 95.00 | 98.50 | 9850 | 19.7% | manual |
| 现金 | CASH | — | — | — | 25000 | 50.0% | — |

**总市值**: ~¥50,000 | **现金比例**: ~50% | **持仓标数**: 3

### 4.2 Paper Trading 持久化状态

Paper Trading 状态保存在 `/mnt/d/HermesData/paper_trading/`:
- `portfolio.json`: 上次运行的持仓状态 (重启不丢失)
- 首次运行: 从 `initial_capital` 开始, 空持仓

### 4.3 Shadow Trading 当前结论

| 日期 | 计划 | 可交易 | 风控拦截 | 策略收益 | 基准收益 | 跑赢/跑输 | NOT_READY |
|------|------|--------|---------|---------|---------|----------|-----------|
| (尚无实际运行数据) | — | — | — | — | — | — | ❌ (默认) |

> **注意**: Shadow Trading 需连接实际 factor_signals 和 market_data 输入。当前 V4.12 阶段信号和数据覆盖不足, 默认使用模拟信号, NOT_READY 为默认状态。

---

## 5. 验证清单

| 检查项 | 状态 | 证据 |
|-------|------|------|
| Paper Trading 存在 | ✅ | `standing_paper_trading.py` (989行) + PaperTradingV4 |
| Shadow Trading 存在 | ✅ | `shadow_trading.py` (657行) + ShadowTradingEngine |
| 模拟成交带成本模型 | ✅ | 手续费 0.03% + 印花税 0.1% (卖出) + 滑点 0.1% |
| 增量调仓逻辑 | ✅ | 卖出不在目标持仓 + 买入新目标 |
| 持久化状态 (JSON/CSV/JSONL) | ✅ | `portfolio.json`, `equity.csv`, `trades.jsonl` |
| 可交易性检查 | ✅ | 涨跌停/停牌/资金/100股整数倍 |
| 风控拦截统计 (by_reason / by_stage) | ✅ | `_analyze_risk_interceptions` |
| 相对半导体等权基准表现 | ✅ | `BENCHMARK_NAME = "semiconductor_ew"` |
| NOT_READY 判定 | ✅ | `excess_return < 0` 或数据不可得 |
| 批量多日运行 | ✅ | `run_shadow_multi()` + `build_report()` |
| 保守滑点: 买入+10bps, 卖出-10bps | ✅ | `_calc_slippage_price` L99-110 |
| 基准降级: 从模块 → 估算 → None | ✅ | `_get_benchmark_return_for_date` 三阶梯 |

---

## 6. 已知限制

1. **数据依赖**: Paper/Shadow Trading 需要真实的 factor_signals 和 market_data 输入, 当前默认使用模拟信号
2. **无真实订单**: 使用模拟成交, 不连接 QMT
3. **持久化路径**: 输出到 `/mnt/d/HermesData/` (Windows D: 盘), 非项目目录
4. **基准数据受限**: semiconductor_ew 基准受 daily_kline 覆盖限制 (~6 只标的)
5. **无自动调度**: Paper/Shadow Trading 需手动 CLI 触发, 无 cron 自动运行
6. **无组合再平衡自动化**: 低频组合建议存在 (`portfolio_builder.py`) 但未自动馈送到 Paper Trading
7. **现金比例过高**: 当前持仓现金占 50%, 反映约束配置偏保守
