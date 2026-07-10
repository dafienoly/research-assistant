# 因子指标计算修复计划

> **审计结论:** `commands/factor_lab/batch_compute.py` 中 9 个指标存在 4 类问题 — IC/RankIC 值重复、超额硬编码、最大回撤恒为 0、风险暴露恒为空。见上一轮审计报告。

**Goal:** 修复 batch_compute.py 中 4 个有问题的指标计算逻辑

**Architecture:** 所有修改集中在 `batch_compute.py`（~268 行），部分辅助函数复用 `validate_factor_v4.py`。前端的 factor_results_cache.py 不动，只改 JSON 缓存中存入的值。

**Tech Stack:** Python, pandas, numpy, scipy

---

## 任务 1：拆分 IC 与 RankIC

**Objective:** IC 使用 Pearson 线性相关系数，RankIC 使用 Spearman 秩相关系数。当前两者都是 Spearman。

**Files:**
- Modify: `commands/factor_lab/batch_compute.py` (L192-L230)

**当前代码 (L192-198):**
```python
daily_ics = []
for d, grp in temp.groupby("date"):
    if len(grp) < 5:
        continue
    ic, pval = scipy_stats.spearmanr(grp["factor"], grp["ret1"])
    if not np.isnan(ic):
        daily_ics.append(ic)
```

**问题:** 只用 `spearmanr` 算了一次，`ic` 和 `rank_ic` 赋同一个值。

**修复：**
```python
daily_pearson_ics = []
daily_spearman_ics = []

for d, grp in temp.groupby("date"):
    if len(grp) < 10:
        continue
    factor_vals = grp["factor"].values
    ret_vals = grp["ret1"].values

    # Pearson IC
    pearson_corr, _ = scipy_stats.pearsonr(factor_vals, ret_vals)
    if not np.isnan(pearson_corr):
        daily_pearson_ics.append(pearson_corr)

    # RankIC (Spearman)
    spearman_corr, _ = scipy_stats.spearmanr(factor_vals, ret_vals)
    if not np.isnan(spearman_corr):
        daily_spearman_ics.append(spearman_corr)

# 汇总 IC (Pearson)
if len(daily_pearson_ics) >= 3:
    ic_arr = np.array(daily_pearson_ics)
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
    ic_ir_val = ic_mean / ic_std if ic_std > 1e-8 else 0.0
else:
    ic_mean, ic_std, ic_ir_val = 0.0, 0.0, 0.0

# 汇总 RankIC (Spearman)
if len(daily_spearman_ics) >= 3:
    rank_arr = np.array(daily_spearman_ics)
    rank_ic_mean = float(np.mean(rank_arr))
else:
    rank_ic_mean = 0.0
```

写入结果字典时：
```python
"ic": round(ic_mean, 4),               # Pearson
"rank_ic": round(rank_ic_mean, 4),     # Spearman (原 RankIC)
"icir": round(ic_ir_val, 4),           # 基于 Pearson IC
```

**注意:** ICIR 计算改为基于 Pearson IC 的标准差（与学术惯例一致）。如果 IC 数据不足 3 天则归零。

**危险:** `scipy_stats.pearsonr` 对异常值敏感。因子值分布极端时可能产生异常 IC 值。如影响面大，可考虑加 winsorize 裁剪（1%/99%）。

---

## 任务 2：实现最大回撤计算

**Objective:** 根据 Top-Bottom 的逐日收益序列计算真实最大回撤，替代硬编码 `0.0`。

**Files:**
- Modify: `commands/factor_lab/batch_compute.py` (在 Top-Bottom 计算后追加)

**当前代码 (L210-218):**
```python
# Top-Bottom: 按因子值分 5 组，算 top - bottom 平均收益
temp["quintile"] = temp.groupby("date")["factor"].transform(
    lambda x: pd.qcut(x, 5, labels=False, duplicates="drop")
)
tb_grp = temp.groupby(["date", "quintile"])["ret1"].mean().reset_index()
tb_pivot = tb_grp.pivot(index="date", columns="quintile", values="ret1")
if 4 in tb_pivot.columns and 0 in tb_pivot.columns:
    top_bottom = float(tb_pivot[4].mean() - tb_pivot[0].mean())
else:
    top_bottom = 0.0
```

**修复：** 在已有的 `tb_pivot` 基础上，计算 top−bottom 逐日收益序列，再算最大回撤。

```python
# Top-Bottom 逐日收益序列 → 最大回撤
daily_spread = None
if 4 in tb_pivot.columns and 0 in tb_pivot.columns:
    top_bottom = float(tb_pivot[4].mean() - tb_pivot[0].mean())
    daily_spread = tb_pivot[4] - tb_pivot[0]
else:
    top_bottom = 0.0

max_drawdown = 0.0
if daily_spread is not None and len(daily_spread) >= 5:
    # 构建净值曲线: 假设初始净值 1, 每日收益累乘
    equity = (1 + daily_spread.fillna(0)).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_drawdown = float(round(dd.min(), 4))
```

写入时：
```python
"max_drawdown": round(max_drawdown, 4),
```

**危险:** 如果 `daily_spread` 方差很大（某些日期极端收益），回撤值可能过于悲观。可考虑加 rolling window 平滑。

---

## 任务 3：实现基础风险暴露分析

**Objective:** 为每个因子计算其对常见风格因子（市值、波动率、动量）的暴露度，替代空列表。

**Files:**
- Modify: `commands/factor_lab/batch_compute.py` (在已有 df 中增加风险暴露计算)

**实现思路：** 在同一批数据中，计算因子值对以下几个代理变量的截面相关性（每日均值）：

| 风险维度 | 代理变量 | 数据来源 |
|---------|---------|---------|
| 市值暴露 | `log_total_mv` | `valuation_*.csv` 中的 `pe_ttm` 倒推？如果无市值，用 `close × volume` 近似 |
| 波动率暴露 | `ret1_std_20d` | 从 K线 `close` 计算 20 日收益标准差 |
| 动量暴露 | `ret_20d` | 过去 20 日累计收益 |
| 流动性暴露 | `turnover_rate` | `valuation_*.csv` 中的 turnover_rate |

**代码：** 在 `temp` DataFrame 上追加风险代理列：

```python
# 计算风险代理变量
# 20日波动率
temp["vol_20d"] = temp.groupby("symbol")["ret1"].transform(
    lambda x: x.rolling(20, min_periods=5).std()
)
# 20日动量
temp["mom_20d"] = temp.groupby("symbol")["ret1"].transform(
    lambda x: x.rolling(20, min_periods=5).sum()
)
# 流动性: 用 turnover_rate (如果 valuation 数据已合并)
if "turnover_rate" in temp.columns:
    temp["liq"] = temp["turnover_rate"]
```

然后计算因子值与各代理变量的截面 Spearman 相关均值：

```python
def _calc_risk_exposure(df: pd.DataFrame, factor_col: str, risk_col: str) -> float:
    """计算因子对某风险维度的暴露 (截面 Spearman 相关均值)"""
    exposures = []
    for d, grp in df.groupby("date"):
        if len(grp) < 10:
            continue
        c, _ = scipy_stats.spearmanr(grp[factor_col].values, grp[risk_col].values)
        if not np.isnan(c):
            exposures.append(c)
    if not exposures:
        return 0.0
    return float(np.mean(exposures))

risk_flags = []
for risk_name, risk_col in [("市值", "log_mv"), ("波动率", "vol_20d"),
                              ("动量", "mom_20d"), ("流动性", "liq")]:
    if risk_col not in temp.columns:
        continue
    exposure = _calc_risk_exposure(temp, "factor", risk_col)
    if abs(exposure) > 0.3:
        risk_flags.append(f"高{risk_name}暴露: {exposure:.2f}")
```

写入：
```python
"risk_flags": risk_flags,
```

**危险:** 
1. 市值数据可能不可用 — `valuation_*.csv` 中未必有市值列。如果缺市值数据，跳过该维度。
2. 计算量增加约 20% — 每次因子要多跑 4 次截面相关循环。可接受。

---

## 任务 4：计算真实半导体等权超额收益（独立任务，可选）

**Objective:** 替代硬编码 `top_bottom * 0.5`，使用真实的半导体等权基准收益率计算超额收益。

**Files:**
- Modify: `commands/factor_lab/batch_compute.py`

**实现思路：**

1. 从 `data/market/daily_kline/` 加载半导体 ETF 成分股（已有半导体主题列表 `semi_stocks`）
2. 计算每日半导体等权基准收益: 所有成分股 `ret1` 的简单平均
3. 因子 top-bottom 收益与其相减得超额

**代码：**
```python
# 半导体成分股列表 (与 analyze_semiconductor 保持一致)
SEMI_STOCKS = [
    "688012.SH", "002371.SZ", "688072.SH", "688120.SH",
    "300604.SZ", "688396.SH", "603986.SH", "300661.SZ",
    # ... 从现有半导体分析模块加载
]

# 计算半导体等权基准每日收益
semi_ret = temp[temp["symbol"].isin(SEMI_STOCKS)].groupby("date")["ret1"].mean().rename("semi_ret")

# 合并到 top_bottom → 超额
excess_df = tb_pivot[[4, 0]].copy()
excess_df["factor_ret"] = excess_df[4].mean() - excess_df[0].mean()  # 简化
# 更精确: 逐日超额
if not semi_ret.empty:
    daily_excess = daily_spread - semi_ret.reindex(daily_spread.index)
    excess_vs_semi = float(daily_excess.mean())
else:
    excess_vs_semi = 0.0
```

**危险:** 半导体成分股列表需要与实际策略保持一致。如果成分股变化或数据不足，超额数据将不可靠。建议从 `universes.py` 的半导体主题池动态加载。

---

## 验证步骤

### Step 1: 单元测试

```bash
cd /home/ly/.hermes/research-assistant/commands
python3 -c "
from factor_lab.batch_compute import compute_all_and_cache
result = compute_all_and_cache()
print(f'Computed: {result[\"computed\"]}, Failed: {result[\"failed\"]}')
"
```

### Step 2: 验证 IC ≠ RankIC

```bash
python3 -c "
import json
d = json.load(open('../data/factor_results.json'))
diff_count = sum(1 for v in d.values() if v.get('ic') is not None and v.get('rank_ic') is not None and abs(v['ic'] - v['rank_ic']) > 0.001)
print(f'Factors where IC != RankIC: {diff_count}/{len(d)}')
assert diff_count > 0, 'IC and RankIC should differ!'
"
```

### Step 3: 验证最大回撤 ≠ 0

```bash
python3 -c "
import json
d = json.load(open('../data/factor_results.json'))
nonzero = sum(1 for v in d.values() if v.get('max_drawdown') is not None and abs(v['max_drawdown']) > 0.00001)
print(f'Factors with non-zero max_drawdown: {nonzero}/{len(d)}')
assert nonzero > 0, 'max_drawdown should not all be zero!'
"
```

### Step 4: 验证风险暴露有值

```bash
python3 -c "
import json
d = json.load(open('../data/factor_results.json'))
with_risk = sum(1 for v in d.values() if v.get('risk_flags') and len(v['risk_flags']) > 0)
print(f'Factors with risk flags: {with_risk}/{len(d)}')
"
```

### Step 5: 前端验证

```
浏览器打开 http://localhost:5173/factors
检查:
  ✅ IC 列 ≠ RankIC 列 (数值不同)
  ✅ 最大回撤列不是全部 0.00%
  ✅ 风险暴露列不再是全部"无"
```

## 执行顺序

| # | 任务 | 工作量 | 依赖 | 风险 |
|---|------|--------|------|------|
| 1 | 拆分 IC/RankIC | ~15 行 | 无 | 低 — 纯新增计算 |
| 2 | 最大回撤 | ~10 行 | 任务 1 的 tb_pivot | 低 — 复用已有数据 |
| 3 | 风险暴露 | ~40 行 | 任务 1 的 temp | 中 — 需数据列存在 |
| 4 | 半导体超额 | ~20 行 | 任务 1 的 daily_spread | 中 — 依赖成分股列表 |

**建议:** 任务 1+2 一起执行，任务 3 单独执行，任务 4 为独立改进可延后。

## 回滚方案

`compute_all_and_cache()` 每次运行覆盖 `data/factor_results.json`。该文件有版本快照：

```bash
cp data/factor_results.json data/factor_results.json.bak
```

修改后不满意可回滚：
```bash
mv data/factor_results.json.bak data/factor_results.json
```
