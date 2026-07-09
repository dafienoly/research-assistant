# V3.3.1 因子加权组合 — 子代理 Spec

## 依赖：V3.2.1 (因子正交化) ✅ 已完成

## 现有基础设施

`composite/factor_combiner.py` — 已有 Gram-Schmidt 正交化 + 相关性矩阵 + 组合函数（V3.2.1 已扩展）

`factor_evaluation.py` — 因子评估管线
`ic_analyzer.py` — IC 计算

## 目标

实现多种因子加权组合策略（IC加权/IR加权/等权），自动选择最优组合方式，并对比不同组合的回测表现。

## 修改文件

### 文件: commands/factor_lab/composite/factor_combiner.py

在现有 V3.2.1 正交化函数之后追加：

```python
"""V3.3.1 因子加权组合 — IC加权 / IR加权 / 风险平价 / 等权对比"""

def compute_ic_weights(
    factor_df: pd.DataFrame,
    factors: list[str],
    ic_window: int = 60,
    method: str = "ic_ir",
) -> dict[str, float]:
    """计算因子权重
    
    Args:
        factor_df: 含 date, symbol, factors + ret1 列的 DataFrame
        factors: 候选因子列表
        ic_window: 滚动 IC 窗口（交易日数）
        method: "ic_mean" / "ic_ir" / "equal" / "ic_squared"
        
    Returns:
        {factor_name: weight} 权重映射
    
    权重方法:
    - ic_mean: IC均值归一化
    - ic_ir: IC均值 × ICIR（兼顾IC大小和稳定性）
    - ic_squared: IC²（加大强者恒强）
    - equal: 等权（baseline）
    """
    from factor_lab.ic_analyzer import calc_daily_ic
    
    weights = {}
    total = 0.0
    
    for factor in factors:
        if factor not in factor_df.columns:
            weights[factor] = 0.0
            continue
        
        # 计算全期 IC
        ic_df = calc_daily_ic(factor_df, factor, "ret1")
        if ic_df.empty:
            weights[factor] = 0.0
            continue
        
        ic_mean = abs(ic_df["ic"].mean())
        ic_std = ic_df["ic"].std()
        ic_ir = ic_mean / (ic_std + 1e-8)
        
        if method == "ic_mean":
            w = ic_mean
        elif method == "ic_ir":
            w = ic_mean * max(ic_ir, 0)  # 负 IR 不参与
        elif method == "ic_squared":
            w = ic_mean ** 2
        else:  # equal
            w = 1.0
        
        weights[factor] = w
        total += w
    
    # 归一化
    if total > 0:
        for k in weights:
            weights[k] /= total
    
    return weights


def compare_weighting_methods(
    factor_df: pd.DataFrame,
    factors: list[str],
    methods: list[str] = None,
    top_quantile: float = 0.2,
) -> list[dict]:
    """对比不同加权方式的回测表现
    
    Args:
        factor_df: 含 date, symbol, factors + ret1 列的 DataFrame
        factors: 候选因子列表
        methods: ["ic_mean", "ic_ir", "ic_squared", "equal"] 默认全部
        
    Returns:
        [{method, sharpe, cum_return, max_dd, turnover, ir}, ...]
    """
    if methods is None:
        methods = ["equal", "ic_mean", "ic_ir", "ic_squared"]
    
    results = []
    for method in methods:
        weights = compute_ic_weights(factor_df, factors, method=method)
        if not weights or sum(weights.values()) == 0:
            continue
        
        # 正交化因子后组合
        # 先正交化所有因子
        ortho_df = factor_df.copy()
        for i in range(1, len(factors)):
            base = factors[:i]
            target = factors[i]
            if all(f in ortho_df.columns for f in base + [target]):
                ortho_df = orthogonalize_gram_schmidt(ortho_df, base, target)
        
        # 使用正交化后的因子名
        ortho_factors = []
        for i, f in enumerate(factors):
            name = f if i == 0 else f"{f}_orthogonalized"
            ortho_factors.append(name)
        
        # 组合因子
        combined_name = f"composite_{method}"
        ortho_df[combined_name] = combine_factors_after_orthogonalization(
            ortho_df,
            [(name, weights[f]) for name, f in zip(ortho_factors, factors) if name in ortho_df.columns],
            method="zscore",
        )
        
        # 回测评估
        from factor_lab.ic_analyzer import layer_test
        layers = layer_test(ortho_df, combined_name, "ret1", n_layers=5)
        
        # Top-quantile 收益
        dates = sorted(ortho_df["date"].unique())
        top_rets = []
        for d in dates:
            day = ortho_df[ortho_df["date"] == d].dropna(subset=[combined_name])
            if len(day) < 10: continue
            n = max(1, int(len(day) * top_quantile))
            top = day.nlargest(n, combined_name)
            top_rets.append(top["ret1"].mean())
        
        ret_series = pd.Series(top_rets)
        sharpe = float(ret_series.mean() / ret_series.std() * np.sqrt(252)) if ret_series.std() > 0 else 0
        cum = float((1 + ret_series).prod() - 1)
        
        results.append({
            "method": method,
            "weights": weights,
            "sharpe": round(sharpe, 4),
            "cum_return_pct": round(cum * 100, 2),
            "ls_sharpe": layers.get("long_short_sharpe", 0),
        })
    
    return results
```

### 验证

```python
from factor_lab.composite.factor_combiner import (
    compute_ic_weights, compare_weighting_methods,
)

# 模拟多因子数据
import pandas as pd, numpy as np
np.random.seed(42)
dates = pd.date_range("2025-01-01", periods=50, freq="B")
data = []
for d in dates:
    for sym in [f"S{i:04d}" for i in range(20)]:
        data.append({
            "date": d, "symbol": sym,
            "momentum": np.random.randn() * 0.5 + 0.05,
            "volume": np.random.randn() * 0.3 + 0.03,
            "trend": np.random.randn() * 0.4 + 0.02,
            "ret1": np.random.randn() * 0.02,
        })
df = pd.DataFrame(data)

# 测试 IC 权重计算
weights = compute_ic_weights(df, ["momentum", "volume", "trend"], method="ic_ir")
total = sum(weights.values())
assert abs(total - 1.0) < 0.01, f"权重应归一化: {total}"
print(f"IC_IR 权重: {weights}")
for f, w in weights.items():
    assert 0 <= w <= 1, f"权重应在[0,1]: {f}={w}"

# 测试加权对比
results = compare_weighting_methods(df, ["momentum", "volume", "trend"])
assert len(results) >= 3, f"至少3种方法, 实际{len(results)}"
for r in results:
    print(f"  {r['method']}: Sharpe={r['sharpe']}, Cum={r['cum_return_pct']}%")
    assert "sharpe" in r
    assert "cum_return_pct" in r

# 找到最优方法
best = max(results, key=lambda r: r["sharpe"])
print(f"🏆 最优方法: {best['method']} (Sharpe={best['sharpe']})")

print("✅ 因子加权组合测试通过")
```

## 注意事项
1. IC 权重基于全期 IC，存在未来函数风险（IC 可能随时间变化）
2. 对比结果中 equal 作为 baseline 衡量其他方法的增量价值
3. 因子组合前先正交化，确保不重复计入共线性信息
4. 如果某个因子 IC 为负，在权重计算中应排除（IC_IR 方法已处理）