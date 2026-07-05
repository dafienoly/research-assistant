"""正交性分析器 — 计算候选因子与 ret5 的正交性和增量价值

指标:
  - pearson_corr_with_ret5
  - spearman_corr_with_ret5
  - top20_overlap_with_ret5
  - top50_overlap_with_ret5
  - orthogonality_score
  - incremental_value_score (通过 filter 测试)
"""
import sys, os
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent.parent))


def compute_orthogonality(
    factor_df: pd.DataFrame,
    candidate_factors: list,
    reference_factor: str = "ret5",
    top_n_list: Optional[list] = None,
) -> dict:
    """计算候选因子与参考因子的正交性指标

    返回:
        {"candidates": [{name, pearson, spearman, top20_overlap, top50_overlap, orthogonality_score}, ...]}
    """
    if top_n_list is None:
        top_n_list = [20, 50]

    results = []
    for cf in candidate_factors:
        if cf not in factor_df.columns:
            results.append({"name": cf, "error": "factor not found"})
            continue
        if reference_factor not in factor_df.columns:
            results.append({"name": cf, "error": f"reference {reference_factor} not found"})
            continue

        # 全样本 Pearson / Spearman
        valid = factor_df[[reference_factor, cf]].dropna()
        if len(valid) < 30:
            results.append({"name": cf, "error": "insufficient data"})
            continue

        p, _ = stats.pearsonr(valid[reference_factor], valid[cf])
        s, _ = stats.spearmanr(valid[reference_factor], valid[cf])

        # TopN overlap
        overlaps = {}
        for n in top_n_list:
            ov = _compute_topn_overlap(factor_df, reference_factor, cf, n)
            overlaps[f"top{n}_overlap"] = ov

        # 正交性评分: TopN overlap 越低越好, Pearson 绝对值越低越好
        top20 = overlaps.get("top20_overlap", 1.0) or 1.0
        top50 = overlaps.get("top50_overlap", 1.0) or 1.0
        pearson_abs = abs(p)

        # 评分: 0-100, 越高越正交
        # Top20 overlap 占比 60%, Top50 占比 20%, Pearson 占 20%
        orth_score = (
            (1 - top20) * 60
            + (1 - top50) * 20
            + (1 - min(pearson_abs, 1)) * 20
        )
        orth_score = max(0, min(orth_score, 100))

        # 判定
        if top20 < 0.3:
            verdict = "high"
        elif top20 < 0.5:
            verdict = "medium"
        else:
            verdict = "low"

        results.append({
            "name": cf,
            "pearson_corr": round(p, 4),
            "spearman_corr": round(s, 4),
            **overlaps,
            "orthogonality_score": round(orth_score, 1),
            "orthogonality_verdict": verdict,
        })

    return {"candidates": results, "reference_factor": reference_factor}


def _compute_topn_overlap(
    factor_df: pd.DataFrame,
    f1: str,
    f2: str,
    n: int = 20,
    n_dates: int = 20,
) -> float:
    """计算两个因子的 TopN 选股重合度 (Jaccard)"""
    dates = sorted(factor_df["date"].unique())
    dates = dates[-n_dates:] if len(dates) > n_dates else dates

    overlaps = []
    for d in dates:
        day = factor_df[factor_df["date"] == d]
        s1 = set(day.nlargest(n, f1)["symbol"]) if f1 in day.columns else set()
        s2 = set(day.nlargest(n, f2)["symbol"]) if f2 in day.columns else set()
        if len(s1) == 0 or len(s2) == 0:
            continue
        j = len(s1 & s2) / len(s1 | s2)
        overlaps.append(j)

    return float(np.mean(overlaps)) if overlaps else 0.0


def compute_incremental_value(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    candidate_name: str,
    reference: str = "ret5",
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> dict:
    """计算增量价值评分

    比较:
      1) ret5 单因子
      2) ret5 + candidate equal_weight
      3) ret5 + candidate gated_filter (candidate 确认后再启用 ret5)
      4) ret5 + candidate risk_penalty (扣减 candidate 风险得分)
      5) ret5 + candidate exclude_top_risk (排除 candidate 最差的 20%)

    输出每个组合的 vs ret5 基线差异
    """
    from factor_lab.composite.factor_combiner import compute_composite

    # ret5 基线指标
    base_metrics = _quick_backtest(factor_df, close_pivot, reference, top_quantile, rebalance)

    strategies = {
        "equal_weight": {
            "desc": "ret5 + candidate 等权",
            "composite": None,  # 延迟计算
        },
        "gated_filter": {
            "desc": "ret5 为主, candidate 门控确认",
            "composite": None,
        },
        "risk_penalty": {
            "desc": "ret5 扣减 candidate 风险",
            "composite": None,
        },
        "exclude_top_risk": {
            "desc": "排除 candidate 最差 20%",
            "composite": None,
        },
    }

    # 实际计算各策略
    # 1. equal_weight: ret5 + candidate
    f1 = compute_composite(factor_df, [reference, candidate_name], "equal_weight_score")
    strategies["equal_weight"]["composite"] = f1

    # 2. gated_filter: ret5 * (candidate_rank > 0.3)
    cand_rank = factor_df.groupby("date")[candidate_name].rank(pct=True)
    gate = (cand_rank > 0.3).astype(float)
    strategies["gated_filter"]["composite"] = factor_df[reference] * gate

    # 3. risk_penalty: ret5 - candidate_penalty
    cand_risk = factor_df.groupby("date")[candidate_name].rank(pct=True) * 0.3
    strategies["risk_penalty"]["composite"] = factor_df[reference] - cand_risk

    # 4. exclude_top_risk: ret5 中排除 candidate 最差 20%
    cand_bad = factor_df.groupby("date")[candidate_name].rank(pct=True) < 0.2
    f4 = factor_df[reference].copy()
    f4[cand_bad.values] = -999  # 用极端负值确保不会被选中
    strategies["exclude_top_risk"]["composite"] = f4

    # 评估每个策略
    inc_results = []
    for name, cfg in strategies.items():
        comp = cfg["composite"]
        temp_df = factor_df.copy()
        temp_df["_comp"] = comp
        metrics = _quick_backtest(temp_df, close_pivot, "_comp", top_quantile, rebalance)
        delta = _delta_vs_base(base_metrics, metrics)
        inc_results.append({
            "strategy": name,
            "description": cfg["desc"],
            **metrics,
            **delta,
        })
        # 清理临时列
        del temp_df["_comp"]

    # 增量价值判定
    any_improvement = any(
        r.get("sharpe_delta", 0) > 0.05
        or r.get("calmar_delta", 0) > 0.05
        or r.get("max_drawdown_delta", 0) < 0  # 回撤下降
        for r in inc_results
    )

    best_strategy = max(inc_results, key=lambda r: r.get("sharpe_delta", -999))

    return {
        "candidate_name": candidate_name,
        "reference": reference,
        "base_metrics": base_metrics,
        "strategies": inc_results,
        "any_improvement": any_improvement,
        "best_strategy": best_strategy["strategy"] if any_improvement else "none",
        "incremental_value_score": round(_compute_ivs(inc_results, base_metrics), 1),
    }


def _quick_backtest(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    factor_col: str,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> dict:
    """快速评估: Top组等权收益 + 回撤"""
    dates = close_pivot.index
    daily_ret = close_pivot.pct_change()

    _rebal = dates[dates.is_month_start] if rebalance == "monthly" else dates[dates.dayofweek == 0]
    rebal_set = set(_rebal)

    rets = pd.Series(0.0, index=dates)
    prev_port = []
    tc = 0.0003 + 0.0005 + 10 / 10000

    for d in dates:
        if d in rebal_set:
            if d in factor_df["date"].values:
                day = factor_df[factor_df["date"] == d]
                if factor_col in day.columns:
                    vals = day.dropna(subset=[factor_col])
                    if len(vals) > 0:
                        n = max(1, int(len(vals) * top_quantile))
                        port = list(vals.nlargest(n, factor_col)["symbol"])
                    else:
                        port = prev_port
                else:
                    port = prev_port
            else:
                port = prev_port
        else:
            port = prev_port

        if not port:
            rets[d] = 0
            prev_port = port
            continue

        avail = [s for s in port if s in daily_ret.columns]
        ret = daily_ret.loc[d, avail].mean() if avail else 0
        if d in rebal_set:
            ret -= tc
        rets[d] = ret
        prev_port = port

    rets = rets.fillna(0)
    eq = (1 + rets).cumprod()
    cum_ret = float(eq.iloc[-1]) - 1 if len(eq) > 0 else 0
    roll_max = eq.cummax()
    dd = float((eq - roll_max).min()) if len(eq) > 0 else 0
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 5 and rets.std() > 0 else 0
    calmar = ((1 + cum_ret) ** (252 / max(len(rets), 1)) - 1) / abs(dd) if abs(dd) > 0.01 else 0
    win_rate = float((rets > 0).mean()) if len(rets) > 0 else 0

    return {
        "cumulative_return_pct": round(cum_ret * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100, 2),
        "n_days": len(rets),
    }


def _delta_vs_base(base: dict, metrics: dict) -> dict:
    """计算 metrics 相对 base 的差值"""
    return {
        "return_delta": round(metrics.get("cumulative_return_pct", 0) - base.get("cumulative_return_pct", 0), 2),
        "max_drawdown_delta": round(metrics.get("max_drawdown_pct", 0) - base.get("max_drawdown_pct", 0), 2),
        "sharpe_delta": round(metrics.get("sharpe", 0) - base.get("sharpe", 0), 4),
        "calmar_delta": round(metrics.get("calmar", 0) - base.get("calmar", 0), 4),
    }


def _compute_ivs(strategies: list, base: dict) -> float:
    """增量价值评分 0-100

    权重: Sharpe提升 40%, 回撤下降 30%, Calmar提升 30%
    """
    if not strategies:
        return 0
    scores = []
    for s in strategies:
        sd = s.get("sharpe_delta", 0)
        dd = s.get("max_drawdown_delta", 0)
        cd = s.get("calmar_delta", 0)
        # 正 = 更好
        sharpe_score = max(0, min(sd * 50, 40))  # max 40
        dd_score = max(0, min(-dd * 30, 30))      # 回撤下降为正分
        calmar_score = max(0, min(cd * 30, 30))   # max 30
        scores.append(sharpe_score + dd_score + calmar_score)
    return float(np.mean(scores)) if scores else 0
