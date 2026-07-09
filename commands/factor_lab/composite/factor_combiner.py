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


# ─── V3.2.1 因子正交化 — Gram-Schmidt + 相关性分析 + 组合 ─────


def orthogonalize_gram_schmidt(
    factor_df: pd.DataFrame,
    base_factors: list[str],
    target_factor: str,
) -> pd.DataFrame:
    """Gram-Schmidt 正交化

    从 target_factor 中剔除与 base_factors 线性相关的部分。
    按日期分组做截面正交化（防未来数据泄漏）。

    Args:
        factor_df: 含 date, symbol, base_factors, target_factor 列的 DataFrame
        base_factors: 基准因子列表
        target_factor: 要正交化的目标因子

    Returns:
        DataFrame，新增 "{target_factor}_orthogonalized" 列
    """
    result = factor_df.copy()
    col_name = target_factor + "_orthogonalized"
    result[col_name] = np.nan

    for date_val, group in result.groupby("date"):
        mask = group[base_factors + [target_factor]].notna().all(axis=1)
        if mask.sum() < len(base_factors) + 5:
            continue
        idx = group.index[mask]
        X = group.loc[mask, base_factors].values
        y = group.loc[mask, target_factor].values
        try:
            coef = np.linalg.lstsq(X, y, rcond=None)[0]
            residual = y - X @ coef
            result.loc[idx, col_name] = residual
        except np.linalg.LinAlgError:
            pass

    result[col_name] = result[col_name].fillna(0)
    return result


def compute_spearman_correlation(
    factor_df: pd.DataFrame,
    factors: list[str],
) -> pd.DataFrame:
    """计算因子截面 Rank 相关性矩阵（逐日平均）

    Args:
        factor_df: 含 date + factor 列的 DataFrame
        factors: 因子列表

    Returns:
        平均相关性矩阵 (len(factors) × len(factors))
    """
    from scipy.stats import spearmanr

    dates = factor_df["date"].unique()
    corr_matrices = []

    for d in dates:
        day = factor_df[factor_df["date"] == d][factors].dropna()
        if len(day) < 10:
            continue
        corr, _ = spearmanr(day, axis=0)
        corr_matrices.append(pd.DataFrame(corr, index=factors, columns=factors))

    if not corr_matrices:
        return pd.DataFrame(np.eye(len(factors)), index=factors, columns=factors)

    return sum(corr_matrices) / len(corr_matrices)


def combine_factors_after_orthogonalization(
    factor_df: pd.DataFrame,
    factor_weights: list[tuple[str, float]],
    method: str = "zscore",
) -> pd.Series:
    """正交化后组合多个因子

    Args:
        factor_df: DataFrame，含正交化后的因子列
        factor_weights: [(factor_name, weight), ...]
        method: "zscore"(Z-score加权) / "rank"(排名平均) / "equal"(等权)

    Returns:
        组合得分 Series
    """
    result_df = factor_df.copy()
    total_weight = sum(w for _, w in factor_weights)

    if method == "zscore":
        combined = pd.Series(0.0, index=result_df.index)
        for factor, weight in factor_weights:
            if factor not in result_df.columns:
                continue
            f = result_df[factor]
            z = f.groupby(result_df["date"]).transform(
                lambda x: (x - x.mean()) / (x.std() + 1e-8)
            )
            combined += z * (weight / total_weight)
        return combined

    elif method == "rank":
        ranks = []
        for factor, _ in factor_weights:
            if factor not in result_df.columns:
                continue
            r = result_df.groupby("date")[factor].rank(pct=True)
            ranks.append(r)
        if ranks:
            return pd.concat(ranks, axis=1).mean(axis=1)
        return pd.Series(0.5, index=result_df.index)

    else:  # equal
        values = []
        for factor, _ in factor_weights:
            if factor not in result_df.columns:
                continue
            v = (result_df[factor] - result_df[factor].mean()) / (result_df[factor].std() + 1e-8)
            values.append(v)
        if values:
            return pd.concat(values, axis=1).mean(axis=1)
        return pd.Series(0.0, index=result_df.index)


# ─── V3.3.1 IC 权重计算 ────────────────────────────────────────


def compute_ic_weights(
    factor_df: pd.DataFrame,
    factors: list[str],
    method: str = "ic_ir",
) -> dict[str, float]:
    """计算因子权重（IC均值/ICIR/IC²/等权）

    Args:
        factor_df: 含 date, symbol, 各因子列, ret1 列的 DataFrame
        factors: 候选因子列表
        method: "ic_mean" / "ic_ir" / "ic_squared" / "equal"

    Returns:
        {factor_name: weight} 权重映射（归一化和=1）
    """
    from factor_lab.ic_analyzer import calc_daily_ic

    weights = {}
    total = 0.0

    for factor in factors:
        if factor not in factor_df.columns:
            weights[factor] = 0.0
            continue

        ic_df = calc_daily_ic(factor_df, factor, "ret1")
        if ic_df.empty:
            weights[factor] = 0.0
            continue

        ic_mean_val = abs(ic_df["ic"].mean())
        ic_std = ic_df["ic"].std()
        ic_ir_val = ic_mean_val / (ic_std + 1e-8)

        if method == "ic_mean":
            w = ic_mean_val
        elif method == "ic_ir":
            w = ic_mean_val * max(ic_ir_val, 0)
        elif method == "ic_squared":
            w = ic_mean_val ** 2
        else:
            w = 1.0

        weights[factor] = w
        total += w

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

    Returns:
        [{method, weights, sharpe, cum_return_pct, ls_sharpe}, ...]
    """
    if methods is None:
        methods = ["equal", "ic_mean", "ic_ir", "ic_squared"]

    # 预先正交化（所有因子对第一个因子做正交化）
    ortho_df = factor_df.copy()
    for i in range(1, len(factors)):
        base = factors[:i]
        target = factors[i]
        if all(f in ortho_df.columns for f in base + [target]):
            ortho_df = orthogonalize_gram_schmidt(ortho_df, base, target)

    # 正交化后的名称
    ortho_names = [factors[0]] + [f"{f}_orthogonalized" for f in factors[1:]]

    results = []
    for method in methods:
        weights = compute_ic_weights(factor_df, factors, method=method)
        if not weights or sum(weights.values()) == 0:
            continue

        combined_name = f"composite_{method}"
        ortho_df[combined_name] = combine_factors_after_orthogonalization(
            ortho_df,
            [(name, weights[f]) for name, f in zip(ortho_names, factors) if name in ortho_df.columns],
            method="zscore",
        )

        # Top-quantile 回测
        top_rets = []
        for d in sorted(ortho_df["date"].unique()):
            day = ortho_df[ortho_df["date"] == d].dropna(subset=[combined_name])
            if len(day) < 10:
                continue
            n = max(1, int(len(day) * top_quantile))
            top_rets.append(day.nlargest(n, combined_name)["ret1"].mean())

        ret = pd.Series(top_rets)
        sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0
        cum = float((1 + ret).prod() - 1)

        from factor_lab.ic_analyzer import layer_test
        layers = layer_test(ortho_df, combined_name, "ret1", n_layers=5)

        results.append({
            "method": method,
            "weights": weights,
            "sharpe": round(sharpe, 4),
            "cum_return_pct": round(cum * 100, 2),
            "ls_sharpe": layers.get("long_short_sharpe", 0),
        })

    return results


# ─── V3.3.2 组合风控约束 ────────────────────────────────────────


def apply_portfolio_constraints(
    candidate_scores: pd.Series,
    current_positions: dict = None,
    industry_map: dict = None,
    board_map: dict = None,
    constraints: dict = None,
) -> pd.Series:
    """对候选打分序列应用组合风控约束

    Args:
        candidate_scores: {symbol: score}
        current_positions: {symbol: {"weight": 0.05}}
        industry_map: {symbol: "industry_name"}
        board_map: {symbol: "main"/"gem"/"star"}
        constraints: {"max_industry": 0.30, "max_single": 0.25,
                     "max_turnover": 0.30, "top_n": 10,
                     "allowed_boards": ["main", "gem"]}

    Returns: 调整后的得分 Series
    """
    if constraints is None:
        constraints = {}

    scores = candidate_scores.copy()
    # 确保浮点类型（防 int Series 上 /= 引发 LossySetitemError）
    if scores.dtype.kind in ("i", "u"):
        scores = scores.astype("float64")
    top_n = constraints.get("top_n", 10)

    # 1. 板块过滤
    allowed = constraints.get("allowed_boards", ["main", "gem", "star"])
    if board_map:
        for sym in list(scores.index):
            if board_map.get(sym, "main") not in allowed:
                scores[sym] = -999

    # 2. 行业暴露
    max_ind = constraints.get("max_industry", 0.30)
    if industry_map and max_ind < 1.0:
        top_symbols = scores.nlargest(top_n * 2).index
        ind_weights = {}
        for sym in top_symbols:
            ind = industry_map.get(sym, "unknown")
            ind_weights[ind] = ind_weights.get(ind, 0) + 1.0 / min(top_n * 2, len(top_symbols))

        for ind, w in ind_weights.items():
            if w > max_ind and max_ind > 0:
                penalty = w / max_ind
                for sym in scores.index:
                    if industry_map.get(sym, "") == ind:
                        scores[sym] /= penalty

    # 3. 换手约束
    max_turn = constraints.get("max_turnover", 1.0)
    if current_positions and max_turn < 1.0:
        current = set(current_positions.keys())
        target = set(scores.nlargest(top_n).index)
        new_entries = target - current
        max_new = int(max_turn * top_n)
        if len(new_entries) > max_new:
            new_sym_scores = scores.loc[list(new_entries)].sort_values(ascending=False)
            keep = set(new_sym_scores.head(max_new).index)
            for sym in new_entries:
                if sym not in keep:
                    scores[sym] = -999

    # 4. 单票上限（留空 — 权重分配时处理）
    max_single = constraints.get("max_single", 0.25)

    return scores


# ─── __main__ 综合测试 ──────────────────────────────────────────


if __name__ == "__main__":
    import sys
    from pathlib import Path
    # 将 commands 目录加入 sys.path 以便 from factor_lab import ...
    _BASE = Path(__file__).resolve().parent.parent.parent
    if str(_BASE) not in sys.path:
        sys.path.insert(0, str(_BASE))

    print("=" * 60)
    print("V3.2.1 因子正交化测试")
    print("=" * 60)
    import numpy as np

    # 模拟数据
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    data = []
    for d in dates:
        for sym in [f"STOCK_{i:04d}" for i in range(5)]:
            data.append({"date": d, "symbol": sym,
                        "factor_a": np.random.randn() * 0.5 + 0.1,
                        "factor_b": np.random.randn() * 0.3 + 0.05,
                        "factor_c": np.random.randn() * 0.4})
    df = pd.DataFrame(data)

    # 测试相关性矩阵
    corr = compute_spearman_correlation(df, ["factor_a", "factor_b", "factor_c"])
    print("相关性矩阵:")
    print(corr.round(3))

    # 测试正交化
    df_ortho = orthogonalize_gram_schmidt(df, ["factor_a"], "factor_b")
    assert "factor_b_orthogonalized" in df_ortho.columns, "缺少正交化列"

    corr_after = compute_spearman_correlation(df_ortho, ["factor_a", "factor_b_orthogonalized"])
    max_corr = abs(corr_after.values[0, 1])
    print(f"正交化后最大相关性: {max_corr:.4f}")
    assert max_corr < 0.3, f"正交化后相关性应 < 0.3, 实际 {max_corr}"

    # 测试组合
    combined = combine_factors_after_orthogonalization(
        df_ortho, [("factor_a", 0.5), ("factor_b_orthogonalized", 0.5)])
    assert len(combined) == len(df), f"组合长度不匹配: {len(combined)} vs {len(df)}"
    print(f"组合得分: mean={combined.mean():.4f}, std={combined.std():.4f}")

    print("\n✅ 所有正交化测试通过")

    # ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("V3.3.1 IC 权重计算 + V3.3.2 组合风控约束 测试")
    print("=" * 60)

    # 生成回测用模拟数据
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=50, freq="B")
    data = []
    for d in dates:
        for sym in [f"S{i:04d}" for i in range(20)]:
            data.append({"date": d, "symbol": sym,
                         "mom": np.random.randn()*0.5+0.05,
                         "vol": np.random.randn()*0.3+0.03,
                         "ret1": np.random.randn()*0.02})
    df_test = pd.DataFrame(data)

    # 1. IC权重测试
    print("\n--- 1. IC 权重计算 ---")
    weights = compute_ic_weights(df_test, ["mom", "vol"], method="ic_ir")
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01, f"权重未归一: {total}"
    for f, w in weights.items():
        assert 0 <= w <= 1, f"权重越界: {f}={w}"
    print(f"✅ IC权重 (ic_ir): {weights} (sum={total:.3f})")

    # 等权测试
    weights_eq = compute_ic_weights(df_test, ["mom", "vol"], method="equal")
    print(f"✅ IC权重 (equal): {weights_eq} (sum={sum(weights_eq.values()):.3f})")

    # IC mean 测试
    weights_mean = compute_ic_weights(df_test, ["mom", "vol"], method="ic_mean")
    print(f"✅ IC权重 (ic_mean): {weights_mean} (sum={sum(weights_mean.values()):.3f})")

    # IC squared 测试
    weights_sq = compute_ic_weights(df_test, ["mom", "vol"], method="ic_squared")
    print(f"✅ IC权重 (ic_squared): {weights_sq} (sum={sum(weights_sq.values()):.3f})")

    # 2. 加权对比
    print("\n--- 2. 加权方法对比 ---")
    results = compare_weighting_methods(df_test, ["mom", "vol"])
    assert len(results) >= 3, f"结果过少: {len(results)}"
    for r in results:
        print(f"  {r['method']}: Sharpe={r['sharpe']}, Cum={r['cum_return_pct']}%, "
              f"LS_Sharpe={r['ls_sharpe']}")

    # 3. 约束测试
    print("\n--- 3. 组合风控约束 ---")
    scores = pd.Series({f"S{i:04d}": 100-i for i in range(1, 21)})
    industry = {f"S{i:04d}": ("半导体" if i <= 8 else "医药") for i in range(1, 21)}

    constrained = apply_portfolio_constraints(
        scores, industry_map=industry,
        constraints={"max_industry": 0.30, "top_n": 10},
    )
    assert isinstance(constrained, pd.Series)
    surviving = (constrained > -999).sum()
    print(f"✅ 行业约束后候选数: {surviving}")

    # 4. 换手约束
    positions = {f"S{i:04d}": {"weight": 0.1} for i in range(11, 21)}
    constrained2 = apply_portfolio_constraints(
        scores, current_positions=positions,
        constraints={"max_turnover": 0.30, "top_n": 10},
    )
    print(f"✅ 换手约束后候选数: {(constrained2 > -999).sum()}")

    # 5. 板块过滤
    board = {f"S{i:04d}": ("main" if i <= 12 else "gem") for i in range(1, 21)}
    constrained3 = apply_portfolio_constraints(
        scores, board_map=board,
        constraints={"allowed_boards": ["main"]},
    )
    print(f"✅ 板块过滤后候选数: {(constrained3 > -999).sum()}")

    print("\n" + "=" * 60)
    print("✅ V3.3.1 + V3.3.2 全部测试通过")
    print("=" * 60)
