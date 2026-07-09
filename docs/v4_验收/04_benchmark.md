# 基准体系报告

> **生成时间**: 2026-07-08 23:40 CST
> **审计依据**: `commands/benchmarks_v4.py` (485 行) + `validate_v4.py` 引用逻辑
> **数据来源**: daily_kline CSV (Windows Data Hub) + universes.json

---

## 1. 基准总览

V4.3 定义了 **6 个核心基准**，覆盖半导体主题和全市场:

| 基准名称 | 标签 | 关联股票池 | 说明 |
|---------|------|-----------|------|
| `semiconductor_ew` | 半导体等权 | U3 | U3 半导体核心池等权组合日收益率 |
| `semiconductor_core_ew` | 半导体核心等权 | U3 (同) | semiconductor_ew 的别名 |
| `matched_control_ew` | 匹配对照等权 | U4 | U4 匹配对照池等权组合日收益率 |
| `ew_a_share` | 全A等权 | U0 | U0 全A基础池等权 (限制最大 1000 只) |
| `ew_tradable` | 可交易等权 | U1 | U1 可交易池等权 |
| `etf_basket_ew` | ETF替代池等权 | ETF | ETF 替代池等权 |

代码位置: `benchmarks_v4.py` 第 45-82 行 `BENCHMARK_META` 字典

---

## 2. 基准计算逻辑

### 2.1 计算流程 (`benchmarks_v4.py:get_benchmark_returns()`)

1. 从 `universes.json` 读取对应股票池的代码列表
2. 从 `daily_kline/*.csv` 加载每只标的的日 K 线 (close 列)
3. 构建 date × symbol 的收盘价 pivot 表
4. 计算每只标的日收益率 (pct_change)
5. 每日取所有可用标的的等权平均收益

### 2.2 数据限制

- **KLINE_DIR**: `/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline/`
  - 这是 Windows 侧 Codex 数据中心的只读挂载
  - 实际上当前仅 ~6 只标的 + ~5 只 ETF 有 CSV
- **max_codes**: U0 池限制最多 1000 只 (`benchmarks_v4.py` 第 184-187 行)
- **U1_TRADABLE**: 作为独立子集从 U1 提取 `tradable_by_user=True` 的标的

---

## 3. 基准到因子晋级的映射

### 3.1 V4.3 晋级条件 (validate_v4.py 第 359-364 行)

```python
promotion_eligible = (
    result.get("beats_semiconductor_peer", False)
    or result.get("beats_core_peer", False)
)
# 需要跑赢半导体核心等权 OR 跑赢核心等权
```

### 3.2 V4.4 评分权重 (validate_factor_v4.py 第 493-496 行)

```python
n_beaten = result.get("n_beaten_benchmarks", 0)
benchmark_score = min(n_beaten * 4, 25)  # 满分 25/100
```

6 个基准各占 4 分 (最多 6×4=24, 封顶 25), 占总评分权重 25%。

### 3.3 跑赢判定逻辑 (validate_v4.py 第 96-101 行)

```python
s_cum = (1 + s_ret).cumprod()
b_cum = (1 + b_ret).cumprod()
beats = bool(s_cum.iloc[-1] > b_cum.iloc[-1])
```

因子策略 vs 基准的累计收益比较。要求:
- 日期重叠 ≥5 天
- 策略累计 > 基准累计

---

## 4. 基准 CLI 命令

```bash
# 列出所有基准 (含可用交易日数/波动率)
python3 benchmarks_v4.py list

# 查看指定基准近60日表现报告
python3 benchmarks_v4.py report semiconductor_ew
python3 benchmarks_v4.py report semiconductor_ew --days 120

# 通过 CLI 触发因子验证 (自动使用基准)
python3 hermes_cli.py factor:validate-v4 --factor ret5
python3 hermes_cli.py factor:validate-v4 --factor vol_ratio60
```

---

## 5. 基准数据可用性

| 基准 | 标的数 (目标) | 实际有数据的标的 | 可用交易日数 | 状态 |
|------|-------------|----------------|------------|------|
| semiconductor_ew | 80-150 (U3) | 6 (实际 K 线) | ~247 | ⚠️ 严重受限 |
| matched_control_ew | ~50-200 | 0 (U4 受限) | 0 | ❌ |
| ew_a_share | ~5000 (U0 max 1000) | 6 | ~247 | ⚠️ 严重受限 |
| ew_tradable | ~3000-4000 | 待定 | 待定 | ⚠️ 受限 |
| etf_basket_ew | 15 | 5 (ETF) | ~247 | ⚠️ 受限 |

**核心问题**: 由于 daily_kline 目录中仅 ~6 只标的 + ~5 只 ETF 有 CSV, 所有基准的实际可用数据严重受限。U3 半导体核心池中仅中微公司(688012)、拓荆科技(688072)、华海清科(688120)、北方华创(002371)、长川科技(300604) 等有数据, 半导体 ETF(512480)、芯片 ETF(588290) 等也有数据。

---

## 6. 验证: 半导体同池等权存在

✅ **已实现**: `semiconductor_ew` 和 `semiconductor_core_ew` 已注册并可用于因子比较。

代码证据:
- `benchmarks_v4.py` 第 46-51 行: `semiconductor_ew` 和 `semiconductor_core_ew` 定义
- `validate_v4.py` 第 44-74 行: `check_semiconductor_peer()` 函数使用 `semiconductor_ew` 基准
- `validate_factor_v4.py` 第 242-268 行: `check_benchmark()` 通用函数支持所有 6 个基准
- `live_readiness.py` 第 300-367 行: `SemiconductorPeerGate` 检查 beats_semiconductor_peer

---

## 7. 已知限制

1. **基准计算依赖 daily_kline CSV**: 当前仅 ~11 个 CSV, 基准结果 ≈ 仅基于这 11 只标的
2. **U4 matched_control_ew 不可用**: U4 池构建受限于 U3 (仅 21 只标签), 匹配后无实际 K 线数据
3. **ETF 基准收益率为空**: ETF 替代池虽定义 15 只, 但 daily_kline 中仅 5 只有文件
4. **未区分价量 vs 基本面因子晋级**: 所有因子使用相同基准条件, 无因子类别差异化
5. **无更短周期对比**: 基准仅提供日频等权, 无周频/月频
6. **数据源依赖日 K 线**: 除 K 线外不使用 tick/分钟数据
