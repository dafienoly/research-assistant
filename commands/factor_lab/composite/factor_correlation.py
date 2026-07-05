"""因子相关性分析 — 相关系数矩阵 / TopN 重合度

用法:
    from factor_lab.composite.factor_correlation import compute_correlation, compute_topn_overlap
"""
import numpy as np
import pandas as pd


def compute_correlation(factor_df: pd.DataFrame, factor_cols: list) -> dict:
    """计算因子间的 Pearson 和 Spearman 相关系数矩阵

    参数:
        factor_df: DataFrame 含 date, symbol 和 factor_cols
        factor_cols: 因子列名列表

    返回:
        {"pearson": matrix_dict, "spearman": matrix_dict, "avg_corr": float}
    """
    # 截面内去均值后合并
    all_vals = {}
    for col in factor_cols:
        if col not in factor_df.columns:
            continue
        # 每日 zscore 去截面效应，取全体值
        vals = factor_df[col].dropna().values
        all_vals[col] = vals

    if len(all_vals) < 2:
        return {"pearson": {}, "spearman": {}, "avg_corr": 0}

    merged = pd.DataFrame(dict(
        (k, pd.Series(v[:min(len(v) for v in all_vals.values())]))
        for k, v in all_vals.items()
    ))

    if merged.shape[1] < 2 or merged.shape[0] < 10:
        return {"pearson": {}, "spearman": {}, "avg_corr": 0}

    pearson = merged.corr(method="pearson")
    spearman = merged.corr(method="spearman")

    pearson_dict = _matrix_to_dict(pearson, factor_cols)
    spearman_dict = _matrix_to_dict(spearman, factor_cols)

    # 平均相关性 (Pearson 上三角)
    n = len(pearson.columns)
    triu = np.triu(np.ones((n, n)), k=1)
    corr_vals = pearson.values[triu == 1]
    avg_corr = float(np.mean(np.abs(corr_vals))) if len(corr_vals) > 0 else 0

    return {
        "pearson": pearson_dict,
        "spearman": spearman_dict,
        "avg_corr": round(avg_corr, 4),
    }


def _matrix_to_dict(mat: pd.DataFrame, all_cols: list) -> dict:
    """DataFrame 相关矩阵 → 嵌套 dict"""
    result = {}
    for c1 in mat.columns:
        row = {}
        for c2 in mat.columns:
            val = mat.loc[c1, c2]
            row[c2] = round(float(val), 4) if not pd.isna(val) else None
        result[c1] = row
    return result


def compute_topn_overlap(
    factor_df: pd.DataFrame,
    factor_cols: list,
    top_quantile: float = 0.2,
    n_dates: int = 10,
) -> dict:
    """计算因子间 Top N 股票集合的重合度

    对最近 n_dates 个交易日, 取每个因子 Top 组分位数对应的股票,
    计算两两之间的 Jaccard 相似度。

    返回:
        {"overlap_matrix": {f1: {f2: avg_overlap}}, "avg_overlap": float}
    """
    from datetime import datetime

    dates = sorted(factor_df["date"].unique())
    dates = dates[-n_dates:] if len(dates) > n_dates else dates

    if len(dates) < 2:
        return {"overlap_matrix": {}, "avg_overlap": 0}

    # 逐日计算重合
    overlap_sums = {}
    overlap_counts = {}

    for f1 in factor_cols:
        for f2 in factor_cols:
            if f1 == f2:
                continue
            key = tuple(sorted([f1, f2]))
            overlap_sums[key] = 0
            overlap_counts[key] = 0

    for d in dates:
        day = factor_df[factor_df["date"] == d]
        top_sets = {}
        for col in factor_cols:
            vals = day.dropna(subset=[col])
            if len(vals) < 10:
                continue
            n_top = max(1, int(len(vals) * top_quantile))
            top_sets[col] = set(vals.nlargest(n_top, col)["symbol"])

        for f1 in factor_cols:
            for f2 in factor_cols:
                if f1 == f2 or f1 not in top_sets or f2 not in top_sets:
                    continue
                s1, s2 = top_sets[f1], top_sets[f2]
                if len(s1) == 0 or len(s2) == 0:
                    continue
                jaccard = len(s1 & s2) / len(s1 | s2)
                key = tuple(sorted([f1, f2]))
                overlap_sums[key] += jaccard
                overlap_counts[key] += 1

    overlap_matrix = {}
    for f1 in factor_cols:
        overlap_matrix[f1] = {}
        for f2 in factor_cols:
            if f1 == f2:
                overlap_matrix[f1][f2] = 1.0
            else:
                key = tuple(sorted([f1, f2]))
                cnt = overlap_counts.get(key, 0)
                overlap_matrix[f1][f2] = round(
                    overlap_sums.get(key, 0) / max(cnt, 1), 4
                )

    avg_overlap_vals = []
    for f1 in factor_cols:
        for f2 in factor_cols:
            if f1 < f2:
                avg_overlap_vals.append(overlap_matrix[f1][f2])
    avg_overlap = float(np.mean(avg_overlap_vals)) if avg_overlap_vals else 0

    return {
        "overlap_matrix": overlap_matrix,
        "avg_overlap": round(avg_overlap, 4),
    }
