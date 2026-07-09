# V3.2.3 资金流因子数据源接通 — 子代理 Spec

## 依赖：已完成

## 现状

`factor_base.py` 已注册 25 个资金流相关因子（fund_flow 11个、north_bound 6个、margin 8个），但**所有因子返回 nan 或 0**，因为数据列（`net_main_force`、`nb_net_flow_1d` 等）未被合并到 K-line DataFrame 中。

`factor_engine.py` 已有：
- `load_fund_flow()` — 从本地 CSV 加载资金流数据
- `merge_fund_flow()` — 合并到 K-line df
- `load_north_bound()` — 加载北向资金数据
- `merge_north_bound()` — 合并到 K-line df

`data_hub_rebuilder.py` 已有：
- `refresh_fund_flow_timeseries()` — 刷新资金流时间序列

## 目标

让 25 个资金流因子能实际计算并产生有效因子值，而不是返回 nan/0。

## 检查路径

### 1. 数据管道排查

```python
# 检查资金流数据文件是否存在
from pathlib import Path
from config import PATHS

flow_path = PATHS["data"] / "fund_flow" / "fund_flow.csv"
north_path = PATHS["data"] / "fund_flow" / "north_bound.csv"

print(f"资金流文件: {flow_path}")
print(f"  存在: {flow_path.exists()}")
if flow_path.exists():
    import pandas as pd
    df = pd.read_csv(flow_path, nrows=5)
    print(f"  列: {list(df.columns)}")
    print(f"  行数: {len(pd.read_csv(flow_path))}")

print(f"北向文件: {north_path}")
print(f"  存在: {north_path.exists()}")
```

### 2. 排查以下场景并按需修复

**场景A：文件缺失**
→ 运行 `python3 commands/data_hub_rebuilder.py` 刷新资金流数据
→ 或单独运行 `python3 commands/fund_flow.py` 拉取

**场景B：文件存在但列名不匹配**
→ `factor_base.py` 中的因子使用 `net_main_force` 列名
→ 检查 CSV 中使用的实际列名（可能是 `net_amount`, `net_main`, `主力净流入` 等）
→ 在 `merge_fund_flow()` 中统一列名映射

**场景C：merge 逻辑缺失**
→ 确认 `factor_engine.py` 中的 `load_data_and_compute()` 或 `compute_all()` 调用了 `merge_fund_flow()`
→ 如果缺少，在 `compute_all()` 中添加自动合并

**场景D：数据范围太窄**
→ 确认 fund_flow 数据覆盖了回测所需的全部日期范围
→ 如果只有近期数据，IC 分析只能跑近期样本

### 3. 修复后的验证

```python
from factor_lab.factor_engine import load_data_and_compute
from factor_lab.ic_analyzer import calc_daily_ic, calc_rankic_ir

# 加载数据并计算所有因子（含资金流）
symbols = ["000001", "000002", "000651", "002415", "600519",
           "601318", "300750", "688012", "002371", "688981"]
df = load_data_and_compute(symbols, "2025-01-01", "2026-06-30", 
                           include_categories=["fund_flow", "north_bound", "margin"])

# 检查是否有有效数据
for factor in ["net_inflow_1d", "nb_net_flow_1d", "margin_buy_ratio"]:
    col = factor
    if col in df.columns:
        non_null = df[col].notna().sum()
        non_zero = (df[col] != 0).sum()
        print(f"{factor}: non_null={non_null}, non_zero={non_zero}")

# 计算 IC（如果数据充分）
ic_df = calc_daily_ic(df, "net_inflow_1d")
if not ic_df.empty:
    stats = calc_rankic_ir(ic_df)
    print(f"net_inflow_1d IC: mean={stats['mean_ic']}, IR={stats['ir']}")
```

### 4. 如果数据源不可用的替代方案

如果 `data_hub_rebuilder.py` 或 `fund_flow.py` 的数据源（mx:data）在 WSL 下不可用，改用 `eastmoney_direct.py` 已有接口：

```python
from commands.eastmoney_direct import get_money_flow

# 逐只股票获取资金流（etf_dive_prediction 项目中已有类似逻辑）
# 参考 datahub_supplement.py 中的 pull_fund_flow()
```

## 验收标准

```python
# 底线要求：至少 3 个资金流因子能计算出非零值
from factor_lab.factor_engine import load_data_and_compute
df = load_data_and_compute(
    ["000001", "000651", "600519", "300750"], 
    "2026-01-01", "2026-06-30",
    include_categories=["fund_flow", "north_bound"]
)

fund_flow_factors = ["net_inflow_1d", "net_inflow_5d", "nb_net_flow_1d"]
for factor in fund_flow_factors:
    col = factor if factor in df.columns else None
    if col:
        non_zero = (df[col] != 0).sum()
        print(f"{factor}: non_zero={non_zero} (out of {len(df)})")

# 至少 3 个因子有非零值
factor_has_data = [
    factor for factor in fund_flow_factors 
    if factor in df.columns and (df[factor] != 0).sum() > 10
]
assert len(factor_has_data) >= 1, f"至少1个因子应有数据, 实际: {factor_has_data}"
print(f"\n✅ 有数据的资金流因子: {factor_has_data}")

# 底线：north bound 至少一个因子可计算
nb_factors = ["nb_net_flow_1d", "nb_net_flow_5d"]
nb_ok = [f for f in nb_factors if f in df.columns and (df[f] != 0).sum() > 0]
print(f"北向因子: {nb_ok if nb_ok else '暂不可用（数据源未接通）'}")
```
