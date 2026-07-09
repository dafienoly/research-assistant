# V3.2.1 因子正交化 — 子代理 Spec

## 依赖：已完成

## 修改文件

### 文件1: commands/factor_lab/composite/factor_combiner.py

当前已有 `__init__.py` 和 `factor_combiner.py`。需要添加正交化功能。

```python
"""V3.2.1 因子正交化 — Gram-Schmidt 正交化 + 相关性分析

正交化的目的：
1. 消除因子间的共线性，使组合因子包含更丰富的信息
2. 确保新增因子对已有因子提供增量价值
3. 避免多重共线性导致的组合权重不稳定
"""

import numpy as np
import pandas as pd
from typing import Optional


def orthogonalize_gram_schmidt(
    factor_df: pd.DataFrame,
    base_factors: list[str],
    target_factor: str,
) -> pd.DataFrame:
    """Gram-Schmidt 正交化：将 target_factor 对 base_factors 做正交化
    
    原理：从 target_factor 中剔除与 base_factors 线性相关的部分
    
    Args:
        factor_df: DataFrame，列包含所有 factor 名称（按 date 和 symbol）
        base_factors: 基准因子列表（要正交化掉的因子）
        target_factor: 要正交化的目标因子名
        
    Returns:
        DataFrame，新增列 "{target_factor}_orthogonalized"
        
    Example:
        # 将 ret5 正交化掉 vol_ratio20 和 ma20_gt_ma60 的影响
        result = orthogonalize_gram_schmidt(
            df, ["vol_ratio20", "ma20_gt_ma60"], "ret5"
        )
        # result["ret5_orthogonalized"] 是正交化后的因子值
    """
    result = factor_df.copy()
    
    # 按日期分组做截面正交化（避免未来信息泄漏）
    def _orthogonalize_group(group):
        mask = group[base_factors + [target_factor]].notna().all(axis=1)
        if mask.sum() < len(base_factors) + 5:
            group[target_factor + "_orthogonalized"] = np.nan
            return group
        
        X = group.loc[mask, base_factors].values  # (n, k)
        y = group.loc[mask, target_factor].values  # (n,)
        
        # Gram-Schmidt 正交化
        # y_residual = y - X @ (X^T X)^{-1} X^T y
        try:
            coef = np.linalg.lstsq(X, y, rcond=None)[0]
            residual = y - X @ coef
            group.loc[mask, target_factor + "_orthogonalized"] = residual
        except np.linalg.LinAlgError:
            group[target_factor + "_orthogonalized"] = np.nan
        
        return group
    
    result = result.groupby("date", group_keys=False).apply(_orthogonalize_group)
    return result


def compute_spearman_correlation(
    factor_df: pd.DataFrame,
    factors: list[str],
) -> pd.DataFrame:
    """计算因子截面 Rank 相关性矩阵（逐日平均）
    
    Args:
        factor_df: DataFrame，含 date + factor 列
        factors: 因子列表
        
    Returns:
        相关性矩阵 (len(factors) × len(factors))
    """
    from scipy.stats import spearmanr
    
    dates = factor_df["date"].unique()
    corr_matrices = []
    
    for d in dates:
        day = factor_df[factor_df["date"] == d][factors].dropna()
        if len(day) < 10:
            continue
        corr, _ = spearmanr(day, axis=0)
        corr_matrices.append(pd.DataFrame(
            corr, index=factors, columns=factors
        ))
    
    # 平均相关性
    avg_corr = sum(corr_matrices) / len(corr_matrices) if corr_matrices else pd.DataFrame(
        np.eye(len(factors)), index=factors, columns=factors
    )
    return avg_corr


def compute_incremental_ic(
    factor_df: pd.DataFrame,
    base_combination: str,
    new_factor: str,
    ret_col: str = "ret1",
) -> dict:
    """计算新因子在已有组合基础上的增量 IC"""
    # 需要确保因子值已计算好
    from factor_lab.ic_analyzer import calc_ic
    
    # 等权组合 base 因子
    combo_col = f"{base_combination}_combo"
    
    daily_base_ics = []
    daily_incremental_ics = []
    
    for d in sorted(factor_df["date"].unique()):
        day = factor_df[factor_df["date"] == d].dropna(
            subset=[combo_col, new_factor, ret_col]
        )
        if len(day) < 10:
            continue
        
        # 组合因子的 IC
        base_ic = calc_ic(day[combo_col], day[ret_col])
        # 新因子的增量 IC
        inc_ic = calc_ic(day[new_factor], day[ret_col])
        
        daily_base_ics.append(base_ic)
        daily_incremental_ics.append(inc_ic)
    
    return {
        "base_mean_ic": float(np.mean(daily_base_ics)) if daily_base_ics else 0,
        "incremental_mean_ic": float(np.mean(daily_incremental_ics)) if daily_incremental_ics else 0,
        "ic_improvement": float(np.mean(daily_incremental_ics) - np.mean(daily_base_ics)) if daily_base_ics and daily_incremental_ics else 0,
        "n_days": len(daily_base_ics),
    }


def combine_factors_after_orthogonalization(
    factor_df: pd.DataFrame,
    factor_weights: list[tuple[str, float]],
    method: str = "zscore",
) -> pd.Series:
    """正交化后组合多个因子
    
    Args:
        factor_df: DataFrame，含正交化后的因子列
        factor_weights: [(factor_name, weight), ...]
        method: "zscore" / "rank" / "equal"
        
    Returns:
        组合得分 Series
        
    Example:
        score = combine_factors_after_orthogonalization(
            df,
            [("ret5_orthogonalized", 0.4), 
             ("vol_ratio20_orthogonalized", 0.3),
             ("close_gt_ma20", 0.3)],
            method="zscore"
        )
    """
    if method == "zscore":
        # Z-score 标准化后加权
        combined = pd.Series(0.0, index=factor_df.index)
        total_weight = sum(w for _, w in factor_weights)
        
        for factor, weight in factor_weights:
            if factor not in factor_df.columns:
                continue
            f = factor_df[factor]
            # 截面 Z-score（按日期）
            z = f.groupby(factor_df["date"]).transform(
                lambda x: (x - x.mean()) / (x.std() + 1e-8)
            )
            combined += z * (weight / total_weight)
        
        return combined
    
    elif method == "rank":
        # 等权排名平均
        ranks = []
        for factor, _ in factor_weights:
            if factor not in factor_df.columns:
                continue
            r = factor_df.groupby("date")[factor].rank(pct=True)
            ranks.append(r)
        if ranks:
            return pd.concat(ranks, axis=1).mean(axis=1)
        return pd.Series(0.5, index=factor_df.index)
    
    else:  # equal
        # 直接等权平均标准化值
        values = []
        for factor, _ in factor_weights:
            if factor not in factor_df.columns:
                continue
            v = (factor_df[factor] - factor_df[factor].mean()) / factor_df[factor].std()
            values.append(v)
        if values:
            return pd.concat(values, axis=1).mean(axis=1)
        return pd.Series(0.0, index=factor_df.index)
```

### 文件2: 验证脚本

```python
# 测试正交化效果
# 预期：高相关因子对正交化后相关性显著下降

from factor_lab.composite.factor_combiner import (
    orthogonalize_gram_schmidt,
    compute_spearman_correlation,
    combine_factors_after_orthogonalization,
)
from factor_lab.factor_engine import load_stock_kline, compute_factors

# 加载数据
df = load_stock_kline(symbols, "2023-01-01", "2026-06-30")
df = compute_factors(df, factors=["ret5", "vol_ratio20", "ma20_gt_ma60", "close_gt_ma20"])

# 正交化前相关性
before_corr = compute_spearman_correlation(
    df, ["ret5", "vol_ratio20", "ma20_gt_ma60", "close_gt_ma20"]
)
print("正交化前相关性:")
print(before_corr.round(3))

# 正交化 ret5 → vol_ratio20 和 ma20_gt_ma60
df = orthogonalize_gram_schmidt(
    df, ["vol_ratio20", "ma20_gt_ma60"], "ret5"
)
df = orthogonalize_gram_schmidt(
    df, ["vol_ratio20", "ret5_orthogonalized"], "close_gt_ma20"
)

after = ["ret5_orthogonalized", "close_gt_ma20_orthogonalized", "vol_ratio20"]
after_corr = compute_spearman_correlation(df, after)
print("正交化后相关性:")
print(after_corr.round(3))

# 验证正交化后相关性降低
before_max = before_corr.values[np.triu_indices_from(before_corr.values, k=1)].max()
after_max = after_corr.values[np.triu_indices_from(after_corr.values, k=1)].max()
print(f"正交化前最大非对角相关性: {before_max:.3f}")
print(f"正交化后最大非对角相关性: {after_max:.3f}")
assert after_max < before_max, "正交化后相关性应降低"
assert after_max < 0.3, "正交化后最大相关性应 < 0.3"
```

## 注意事项

1. **按日期分组做截面正交化** — 不是全样本正交化，避免未来数据泄漏
2. **Gram-Schmidt 顺序无关** — 正交化结果取决于 base_factors 的顺序，但增量价值分析会评估
3. **不修改原始因子列** — 正交化结果用 `{factor}_orthogonalized` 后缀
4. 正交化后的因子可能失去原始因子的方向性（如动量变负），使用前需要检查方向
5. 组合因子时先正交化再加权，比等权组合更有信息增量
