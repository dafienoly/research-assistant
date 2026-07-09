# V3.2.2 基本面因子接入 — 子代理 Spec

## 依赖：已完成

## 现有基础设施

`factor_engine.py` 已有：
- `load_fundamentals()` — 从本地 CSV 加载基本面数据，含 pub_date 防未来函数
- `merge_fundamentals()` — 使用 `pd.merge_asof(direction="backward")` 确保回测时不使用未来数据
- `FUND_FIELDS` — 现有字段列表（包含 roe, gross_margin, net_margin, debt_ratio 等）

`factor_base.py` 已有质量因子：
- `roe_q` — 检查 "roe" 列是否存在，fillna(0)
- `gross_margin_q` — 检查 "gross_margin" 列
- `net_margin_q` — 检查 "net_margin" 列  
- `debt_ratio_q` — 检查 "debt_ratio" 列

## 修改文件

### 文件1: commands/factor_lab/factor_engine.py — 扩展 FUND_FIELDS

在文件顶部找到 `FUND_FIELDS` 定义，追加以下字段：

```python
FUND_FIELDS = [
    # 原有字段（保留）
    "roe", "gross_margin", "net_margin", "debt_ratio",
    # V3.2.2 新增 — 估值
    "pe_ttm",           # 滚动市盈率（越小越低估）
    "pb_lf",            # 市净率（越小越低估）
    "ps_ttm",           # 市销率
    "pcf_ttm",          # 市现率
    # V3.2.2 新增 — 质量
    "roe_ttm",          # 年化ROE（= 最近4季净利润之和 / 净资产）
    "roa_ttm",          # 年化ROA
    # V3.2.2 新增 — 成长
    "revenue_growth_q",  # 单季营收同比增速
    "profit_growth_q",   # 单季净利润同比增速
    "profit_surprise",   # 净利润超预期比例（实际/预期-1）
    # V3.2.2 新增 — 财务健康
    "current_ratio",    # 流动比率
    "asset_turnover",   # 总资产周转率
    # V3.2.2 新增 — 比率
    "dividend_yield",   # 股息率
    "free_cash_flow_yield",  # 自由现金流收益率
]
```

注意：fund_fields 的 CSV 路径在 `factor_engine.py` 中定义为 `FUND_CSV = PATHS["data"] / "fundamentals" / "financial_snapshot.csv"`。需要同步确保 `market_fetcher.py` 或 `baostock_data.py` 中的财务数据拉取也包含这些字段。

### 文件2: commands/factor_lab/factor_base.py — 注册新因子

在 quality 分类下新增因子（在 roe_factor / gross_margin 函数之后）：

```python
# ═══════════════════════════════════════════════
# 七(续). 估值因子 (Valuation)
# ═══════════════════════════════════════════════

@register("pe_ttm_inv", "valuation", {}, "PE_TTM倒数 — 越高越低估")
def pe_ttm_inv_factor(df):
    """PE_TTM 倒数：pe_ttm 越低 → 值越大 → 越值得买入"""
    if "pe_ttm" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    pe = df["pe_ttm"].replace(0, np.nan).abs()
    inv = 1 / pe
    return inv.fillna(0)

@register("pb_lf_inv", "valuation", {}, "PB倒数 — 越高越低估")
def pb_lf_inv_factor(df):
    if "pb_lf" not in df.columns or "pb_lf" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    pb = df["pb_lf"].replace(0, np.nan)
    inv = 1 / pb
    return inv.fillna(0)

@register("ep", "valuation", {}, "E/P 比率 — 收益/价格")
def ep_factor(df):
    """E/P = PE_TTM 的倒数，与 pe_ttm_inv 相同但确保方向为正"""
    return pe_ttm_inv_factor(df)

# ═══════════════════════════════════════════════
# 七(续). 成长因子 (Growth)
# ═══════════════════════════════════════════════

@register("revenue_growth_q", "growth", {}, "单季营收同比增速")
def revenue_growth_factor(df):
    if "revenue_growth_q" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["revenue_growth_q"].fillna(0)

@register("profit_growth_q", "growth", {}, "单季净利润同比增速")
def profit_growth_factor(df):
    if "profit_growth_q" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["profit_growth_q"].fillna(0)

@register("profit_surprise", "growth", {}, "净利润超预期")
def profit_surprise_factor(df):
    if "profit_surprise" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["profit_surprise"].fillna(0)

# ═══════════════════════════════════════════════
# 七(续). 财务健康因子 (Financial Health)
# ═══════════════════════════════════════════════

@register("current_ratio", "financial_health", {}, "流动比率")
def current_ratio_factor(df):
    if "current_ratio" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    # 过高不好（资金闲置），过低不好（偿债风险），适中为好
    dev = (df["current_ratio"] - 2.0).abs()  # 偏离2为异常
    return (-dev).fillna(0)

@register("free_cash_flow_yield", "financial_health", {}, "自由现金流收益率")
def fcf_yield_factor(df):
    if "free_cash_flow_yield" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["free_cash_flow_yield"].fillna(0)

# ═══════════════════════════════════════════════
# 七(续). 综合质量因子 (Composite Quality)
# ═══════════════════════════════════════════════

@register("quality_composite", "composite", {}, "综合质量评分: ROE+毛利率+净利率+资产负债率倒数")
def quality_composite(df):
    """综合质量：高ROE+高毛利+高净利+低负债"""
    score = pd.Series(0.0, index=df.index)
    n = 0
    if "roe" in df.columns:
        score += df["roe"].rank(pct=True)
        n += 1
    if "gross_margin" in df.columns:
        score += df["gross_margin"].rank(pct=True)
        n += 1
    if "net_margin" in df.columns:
        score += df["net_margin"].rank(pct=True)
        n += 1
    if "debt_ratio" in df.columns:
        # 负债率越低越好
        score += (1 - df["debt_ratio"].rank(pct=True))
        n += 1
    return score / n if n > 0 else pd.Series(0.0, index=df.index)
```

### 文件3: commands/market_fetcher.py 或 commands/baostock_data.py — 数据源补全

需要确认现有财务数据拉取是否包含新增字段。

查看 `commands/market_fetcher.py` 中的 `update_financial_snapshot()` 函数：

如果当前只拉取了 roe/gross_margin/net_margin/debt_ratio，需要扩展 API 请求增加：
- pe_ttm, pb_lf, ps_ttm, pcf_ttm（从 baostock `query_stock_basic()` 或东方财富接口）
- revenue_growth_q, profit_growth_q（从 `query_growth_data()`）
- dividend_yield（从 `query_dividend_data()`）

### 文件4: commands/data_hub_rebuilder.py

`rebuild_fundamentals_timeseries()` 函数中，确保新增字段也写入到财务 CSV。

### 快速验证

```python
# 测试因子注册和计算
from factor_lab.factor_base import list_factors
from factor_lab.factor_engine import compute_all

# 验证新因子已注册
factors = list_factors()
new_names = ["pe_ttm_inv", "pb_lf_inv", "revenue_growth_q", 
             "profit_growth_q", "quality_composite", "ep"]
for name in new_names:
    found = any(f["name"] == name for f in factors)
    print(f"{'✅' if found else '❌'} {name}: {'已注册' if found else '未注册'}")

# 验证因子分类被正确设置
factor_cats = {f["name"]: f["category"] for f in factors}
expected_cats = {
    "pe_ttm_inv": "valuation", "pb_lf_inv": "valuation",
    "revenue_growth_q": "growth", "profit_growth_q": "growth",
    "quality_composite": "composite",
}
for name, expected_cat in expected_cats.items():
    actual = factor_cats.get(name, "")
    print(f"{'✅' if actual == expected_cat else '❌'} {name}: category={actual} (期望{expected_cat})")

# 验证因子计算（如果数据可用）
import pandas as pd
import numpy as np
df = pd.DataFrame({
    "symbol": ["000001", "000002", "000003"],
    "date": ["2026-07-08"] * 3,
    "close": [10, 20, 30],
    "pe_ttm": [5, 15, 50],
    "pb_lf": [0.5, 1.5, 3.0],
})
result = compute_all(df, include_categories=["valuation"])
print(f"计算估值因子列: {[c for c in result.columns if 'pe_ttm' in c or 'pb_lf' in c or 'ep' in c]}")

# 验证 pe_ttm_inv 方向：pe_ttm=5 → pe_ttm_inv=0.2, pe_ttm=50 → pe_ttm_inv=0.02
if "pe_ttm_inv" in result.columns:
    assert result["pe_ttm_inv"].iloc[0] > result["pe_ttm_inv"].iloc[2], "低PE应有更高pe_ttm_inv"
    print("✅ pe_ttm_inv 方向正确：低PE → 高因子值")

print("\n✅ 基本面因子接入完成")
```
