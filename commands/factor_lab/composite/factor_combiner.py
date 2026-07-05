"""组合因子方法与合成器 — 5 种组合方式

支持:
  1. equal_weight_score — 多因子 rank 后等权平均
  2. weighted_score — 根据 score 加权
  3. gated_score — ret5>阈值 AND close_gt_ma20=True
  4. zscore_blend — zscore 标准化后加权
  5. rank_blend — 截面 rank 后加权
"""
import numpy as np
import pandas as pd
from typing import Optional


def compute_composite(
    factor_df: pd.DataFrame,
    factor_names: list,
    method: str = "equal_weight_score",
    weights: Optional[dict] = None,
) -> pd.Series:
    """计算组合因子值

    参数:
        factor_df: 含 date, symbol 和各因子列的 DataFrame
        factor_names: 要组合的因子列表
        method: 组合方法
        weights: {factor_name: weight} — 仅用于 weighted / zscore / rank 模式

    返回:
        pd.Series (index 同 factor_df), 组合因子值
    """
    if weights is None:
        weights = {f: 1.0 / len(factor_names) for f in factor_names}

    if method == "equal_weight_score":
        return _equal_weight_score(factor_df, factor_names)
    elif method == "weighted_score":
        return _weighted_score(factor_df, factor_names, weights)
    elif method == "gated_score":
        return _gated_score(factor_df, factor_names)
    elif method == "zscore_blend":
        return _zscore_blend(factor_df, factor_names, weights)
    elif method == "rank_blend":
        return _rank_blend(factor_df, factor_names, weights)
    else:
        raise ValueError(f"未知组合方法: {method}")


# ─── 5 种组合方法 ─────────────────────────────────────────────


def _equal_weight_score(factor_df: pd.DataFrame, names: list) -> pd.Series:
    """等权: 每个因子截面 rank 归一化后平均"""
    ranks = []
    for f in names:
        if f not in factor_df.columns:
            continue
        r = factor_df.groupby("date")[f].rank(pct=True)
        ranks.append(r)
    if not ranks:
        return pd.Series(0.0, index=factor_df.index)
    combined = sum(ranks) / len(ranks)
    return combined.fillna(0)


def _weighted_score(factor_df: pd.DataFrame, names: list, weights: dict) -> pd.Series:
    """加权: 每个因子截面 rank 后按权重求和"""
    total_weight = sum(weights.get(f, 0) for f in names)
    if total_weight == 0:
        total_weight = 1
    combined = pd.Series(0.0, index=factor_df.index)
    for f in names:
        if f not in factor_df.columns:
            continue
        r = factor_df.groupby("date")[f].rank(pct=True)
        combined += r * weights.get(f, 0) / total_weight
    return combined.fillna(0)


def _gated_score(factor_df: pd.DataFrame, names: list) -> pd.Series:
    """门控: 第一个因子 rank > 0.5 时取第二个因子 rank, 否则 0"""
    if len(names) < 2:
        return _equal_weight_score(factor_df, names)
    primary = names[0]
    secondary = names[1:]

    if primary not in factor_df.columns:
        return _equal_weight_score(factor_df, names)

    primary_rank = factor_df.groupby("date")[primary].rank(pct=True)
    gate = primary_rank >= 0.5

    if not secondary:
        return primary_rank

    secondary_combined = _equal_weight_score(factor_df, secondary)
    result = secondary_combined.where(gate, 0)
    return result.fillna(0)


def _zscore_blend(factor_df: pd.DataFrame, names: list, weights: dict) -> pd.Series:
    """zscore: 每日截面 zscore 标准化后加权"""
    total_w = sum(weights.get(f, 0) for f in names)
    if total_w == 0:
        total_w = 1
    combined = pd.Series(0.0, index=factor_df.index)
    for f in names:
        if f not in factor_df.columns:
            continue
        z = factor_df.groupby("date")[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-8))
        combined += z.fillna(0) * weights.get(f, 0) / total_w
    return combined


def _rank_blend(factor_df: pd.DataFrame, names: list, weights: dict) -> pd.Series:
    """rank blend: 每日截面 rank 归一化后加权"""
    return _weighted_score(factor_df, names, weights)
