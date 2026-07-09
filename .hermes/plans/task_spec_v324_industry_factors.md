# V3.2.4 行业因子 — 子代理 Spec

## 依赖：已完成

## 现有基础设施

`commands/factor_lab/industry_relative/factors.py` — 已有文件但功能未完全集成到 factor_base.py
`commands/factor_lab/alpha/industry_mapper.py` — 行业映射工具

factor_base.py 已有 `industry_relative` 分类（10个因子），但 `_industry_rank()` 辅助函数依赖行业分类数据列 `industry`。

## 目标

让行业因子能实际计算，新增 3 个行业因子，确保行业分类数据能自动合并到回测 DataFrame 中。

## 修改文件

### 文件1: commands/factor_lab/factor_engine.py

在 `compute_all()` 或 `load_data_and_compute()` 中增加行业分类数据合并：

```python
# 在 compute_all 或 load_data_and_compute 中：
# 自动合并行业分类
if "industry" not in df.columns:
    try:
        industry_map = _load_industry_map()  # 从缓存CSV加载
        df["industry"] = df["symbol"].map(industry_map)
    except Exception:
        df["industry"] = "unknown"

def _load_industry_map() -> dict:
    """加载股票→行业映射
    
    优先从缓存 CSV 加载，不存在时从 data_hub 生成
    """
    cache_path = Path("/mnt/d/HermesData/industry_map.csv")
    if cache_path.exists():
        import pandas as pd
        mapping = pd.read_csv(cache_path)
        return dict(zip(mapping["symbol"], mapping["industry"]))
    # fallback: 从行业标签文件生成
    ...
```

### 文件2: commands/factor_lab/factor_base.py

注册以下新因子到 `industry_relative` 分类：

```python
# ═══════════════════════════════════
# 行业因子 (Industry Relative)
# ═══════════════════════════════════

@register("industry_relative_ret5", "industry_relative", {},
          "5日动量行业中位数调整")
def industry_relative_ret5(df):
    """个股收益 - 行业中位数收益"""
    if "ret5" not in df.columns or "industry" not in df.columns:
        return pd.Series(0.0, index=df.index)
    ind_median = df.groupby("industry")["ret5"].transform("median")
    return (df["ret5"] - ind_median).fillna(0)

@register("industry_momentum", "industry_relative", {},
          "行业动量 — 行业中位数收益")
def industry_momentum(df):
    """行业本身的动量（作为行业配置因子）"""
    if "ret5" not in df.columns or "industry" not in df.columns:
        return pd.Series(0.0, index=df.index)
    ind_mean = df.groupby("industry")["ret5"].transform("mean")
    return ind_mean.fillna(0)

@register("industry_concentration", "industry_relative", {},
          "行业拥挤度 — 行业成交额占比变化")
def industry_concentration(df):
    """行业日成交额占全市场比例的变化"""
    if "amount" not in df.columns or "industry" not in df.columns:
        return pd.Series(0.0, index=df.index)
    # 行业成交额占比
    ind_amount = df.groupby("industry")["amount"].transform("sum")
    total_amount = df["amount"].sum()
    if total_amount > 0:
        ratio = ind_amount / total_amount
    else:
        ratio = pd.Series(0.0, index=df.index)
    return ratio.fillna(0)
```

### 验证

```python
from factor_lab.factor_base import list_factors

# 验证新因子注册
new_factors = ["industry_relative_ret5", "industry_momentum", "industry_concentration"]
registry = {f["name"]: f["category"] for f in list_factors()}
for name in new_factors:
    assert name in registry, f"{name} 未注册"
    assert registry[name] == "industry_relative", f"{name} 分类错误"
    print(f"✅ {name}: {registry[name]}")

# 验证计算（模拟数据）
import pandas as pd, numpy as np
df = pd.DataFrame({
    "symbol": ["A", "B", "C", "D"],
    "date": ["2026-07-08"]*4,
    "close": [10, 20, 30, 40],
    "volume": [1000, 2000, 3000, 4000],
    "amount": [10000, 20000, 30000, 40000],
    "industry": ["半导体", "半导体", "医药", "医药"],
})
# 先计算 ret5（用 close 模拟）
df["ret5"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5)).fillna(0.02)

from factor_lab.factor_engine import compute_all
result = compute_all(df, include_categories=["industry_relative"])
print(f"行业因子列: {[c for c in result.columns if 'industry' in c]}")
assert "industry_relative_ret5" in result.columns

# 行业中位数调整后同一行业内股票的值应对称
semi = result[result["industry"] == "半导体"]
print(f"半导体: ret5={semi['ret5'].values}, adj={semi['industry_relative_ret5'].values}")

print("✅ 行业因子接入完成")
```

## 注意事项
1. 行业分类使用申万一级行业（已有的标签文件格式）
2. 如果行业映射缺失，回退到 "unknown" 并记录 warning
3. industry_concentration 的成交额占比按日计算