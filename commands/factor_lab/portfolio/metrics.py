"""Portfolio Metrics V6.4 — 组合层面指标计算

提供组合层面的风险收益指标:
  - 组合绝对指标: 累计收益、年化收益/波动、Sharpe、最大回撤、Calmar、胜率
  - 基准对比: 主动收益、跟踪误差、信息比率、Alpha、Beta、R²
  - 策略间: 交叉相关性矩阵、平均相关性
  - 归因: 各策略贡献分解

所有 canonical 指标计算统一使用 factor_lab.metrics 作为基础。
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.metrics import (
    calc_sharpe,
    calc_max_drawdown,
    calc_calmar,
    calc_cagr,
)


# ═══════════════════════════════════════════════════════════════
# 组合绝对指标
# ═══════════════════════════════════════════════════════════════


def compute_portfolio_absolute_metrics(
    portfolio_returns: pd.Series,
    rf_annual: float = 0.03,
) -> dict:
    """计算组合绝对收益指标

    Args:
        portfolio_returns: 组合日收益率序列
        rf_annual: 年化无风险利率

    Returns:
        {
            cumulative_return_pct, annualized_return_pct,
            annualized_volatility_pct, sharpe, max_drawdown_pct,
            calmar, win_rate_pct, n_trading_days
        }
    """
    returns = portfolio_returns.fillna(0)
    n = len(returns)
    if n < 2:
        return {
            "cumulative_return_pct": 0.0,
            "annualized_return_pct": 0.0,
            "annualized_volatility_pct": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar": 0.0,
            "win_rate_pct": 0.0,
            "n_trading_days": n,
        }

    # 净值曲线
    equity = (1 + returns).cumprod()
    cum_ret = float(equity.iloc[-1]) - 1

    # 年化收益率
    years = n / 252
    ann_ret = (1 + cum_ret) ** (1 / years) - 1 if years > 0.02 else 0.0

    # 年化波动率
    ann_vol = float(returns.std() * np.sqrt(252))

    # Sharpe
    sharpe = calc_sharpe(returns, rf_annual)

    # 最大回撤
    max_dd = calc_max_drawdown(equity)

    # Calmar
    calmar = calc_calmar(ann_ret, max_dd)

    # 胜率
    win_rate = float((returns > 0).mean())

    return {
        "cumulative_return_pct": round(cum_ret * 100, 2),
        "annualized_return_pct": round(ann_ret * 100, 2),
        "annualized_volatility_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100, 2),
        "n_trading_days": n,
    }


# ═══════════════════════════════════════════════════════════════
# 基准对比指标
# ═══════════════════════════════════════════════════════════════


def compute_benchmark_relative_metrics(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    rf_annual: float = 0.03,
) -> dict:
    """计算基准相对指标

    Args:
        portfolio_returns: 组合日收益率 (会与 benchmark 对齐)
        benchmark_returns: 基准日收益率
        rf_annual: 年化无风险利率

    Returns:
        {
            benchmark_cumulative_return_pct, benchmark_annualized_return_pct,
            benchmark_volatility_pct, benchmark_sharpe, benchmark_max_drawdown_pct,
            active_return_pct, tracking_error_pct, information_ratio,
            alpha, beta, r_squared
        }
    """
    # 日期对齐
    common = portfolio_returns.index.intersection(benchmark_returns.index)
    if len(common) < 5:
        return {
            "benchmark_cumulative_return_pct": 0.0,
            "benchmark_annualized_return_pct": 0.0,
            "benchmark_volatility_pct": 0.0,
            "benchmark_sharpe": 0.0,
            "benchmark_max_drawdown_pct": 0.0,
            "active_return_pct": 0.0,
            "tracking_error_pct": 0.0,
            "information_ratio": 0.0,
            "alpha": 0.0,
            "beta": 0.0,
            "r_squared": 0.0,
        }

    p_ret = portfolio_returns.loc[common].fillna(0)
    b_ret = benchmark_returns.loc[common].fillna(0)

    n = len(p_ret)
    years = n / 252

    # 基准指标
    b_equity = (1 + b_ret).cumprod()
    b_cum = float(b_equity.iloc[-1]) - 1
    b_ann = (1 + b_cum) ** (1 / years) - 1 if years > 0.02 else 0.0
    b_vol = float(b_ret.std() * np.sqrt(252))
    b_sharpe = calc_sharpe(b_ret, rf_annual)
    b_max_dd = calc_max_drawdown(b_equity)

    # 主动收益 (超额)
    active = p_ret - b_ret
    active_cum = float((1 + active).prod() - 1)

    # 跟踪误差 (年化)
    te = float(active.std() * np.sqrt(252))

    # 信息比率
    ir = (
        float(active.mean() / active.std() * np.sqrt(252))
        if active.std() > 1e-10
        else 0.0
    )

    # Alpha / Beta (OLS: portfolio_ret = alpha + beta * benchmark_ret + eps)
    beta_val, alpha_val = _ols_beta_alpha(p_ret, b_ret, rf_annual)

    # R²
    if b_ret.std() > 1e-10:
        corr = p_ret.corr(b_ret)
        r_sq = corr ** 2 if not pd.isna(corr) else 0.0
    else:
        r_sq = 0.0

    return {
        "benchmark_cumulative_return_pct": round(b_cum * 100, 2),
        "benchmark_annualized_return_pct": round(b_ann * 100, 2),
        "benchmark_volatility_pct": round(b_vol * 100, 2),
        "benchmark_sharpe": round(b_sharpe, 4),
        "benchmark_max_drawdown_pct": round(b_max_dd * 100, 2),
        "active_return_pct": round(active_cum * 100, 2),
        "tracking_error_pct": round(te * 100, 2),
        "information_ratio": round(ir, 4),
        "alpha": round(alpha_val * 100, 4),  # 以百分比表示
        "beta": round(beta_val, 4),
        "r_squared": round(r_sq, 4),
    }


def _ols_beta_alpha(
    portfolio_ret: pd.Series,
    benchmark_ret: pd.Series,
    rf_annual: float = 0.03,
) -> tuple[float, float]:
    """OLS 回归计算 Beta 和 Alpha

    使用超额收益率: (Rp - Rf) = alpha + beta * (Rm - Rf) + eps

    Returns:
        (beta, alpha_annualized) — alpha 为年化值
    """
    rf_daily = rf_annual / 252

    p_excess = portfolio_ret - rf_daily
    b_excess = benchmark_ret - rf_daily

    if b_excess.std() < 1e-10:
        return 0.0, float(p_excess.mean() * 252)

    # OLS
    cov = np.cov(p_excess, b_excess, ddof=1)
    beta_val = cov[0, 1] / cov[1, 1]

    # Alpha (日频) → 年化
    alpha_daily = float(p_excess.mean() - beta_val * b_excess.mean())
    alpha_ann = alpha_daily * 252

    return beta_val, alpha_ann


# ═══════════════════════════════════════════════════════════════
# 策略间相关性
# ═══════════════════════════════════════════════════════════════


def compute_cross_correlation(
    strategy_returns: dict[str, pd.Series],
) -> pd.DataFrame:
    """计算策略间收益率交叉相关性矩阵

    Args:
        strategy_returns: 策略名称 → 收益率 Series

    Returns:
        相关性矩阵 DataFrame (n_strategies × n_strategies)
    """
    if not strategy_returns:
        return pd.DataFrame()

    # 对齐日期
    combined = pd.DataFrame(strategy_returns).fillna(0)
    if combined.empty or combined.shape[1] < 2:
        return pd.DataFrame(index=combined.columns, columns=combined.columns, dtype=float)

    return combined.corr()


def compute_avg_correlation(corr_matrix: pd.DataFrame) -> float:
    """计算平均交叉相关性 (不包含对角线的上三角均值)

    Args:
        corr_matrix: 策略相关性矩阵

    Returns:
        平均相关性
    """
    if corr_matrix.empty or corr_matrix.shape[0] < 2:
        return 0.0

    # 取上三角 (不含对角线)
    n = corr_matrix.shape[0]
    upper_tri = []
    for i in range(n):
        for j in range(i + 1, n):
            val = corr_matrix.iloc[i, j]
            if not pd.isna(val):
                upper_tri.append(val)

    return float(np.mean(upper_tri)) if upper_tri else 0.0


# ═══════════════════════════════════════════════════════════════
# 归因分析
# ═══════════════════════════════════════════════════════════════


def compute_attribution(
    strategy_returns: dict[str, pd.Series],
    weights: dict[str, float],
    portfolio_returns: pd.Series,
) -> list[dict]:
    """策略归因分析

    计算每个策略对组合的贡献:
      - 边际贡献 = 权重 × 策略累计收益
      - 贡献百分比 = 边际贡献 / 总边际贡献
      - 与组合的相关性

    Args:
        strategy_returns: 策略名称 → 收益率
        weights: 策略名称 → 权重
        portfolio_returns: 组合收益率

    Returns:
        [{
            strategy_name, weight, contribution_pct,
            marginal_contribution, sharpe,
            standalone_return_pct, correlation_to_portfolio
        }, ...]
    """
    if not strategy_returns or not weights:
        return []

    # 对齐日期
    common_idx = portfolio_returns.index
    total_mc = 0.0
    items_raw = []

    for sname, s_ret in strategy_returns.items():
        w = weights.get(sname, 0.0)
        if w <= 0 or s_ret.empty:
            continue

        # 对齐到组合日期
        aligned = s_ret.reindex(common_idx).fillna(0)

        # 累计收益
        cum_ret = float((1 + aligned).prod() - 1)

        # 边际贡献 = 权重 × 累计收益
        mc = w * cum_ret

        # 策略 Sharpe
        sr = calc_sharpe(aligned) if aligned.std() > 1e-10 else 0.0

        # 与组合的相关性
        corr_val = aligned.corr(portfolio_returns)
        if pd.isna(corr_val):
            corr_val = 0.0

        items_raw.append({
            "strategy_name": sname,
            "weight": w,
            "marginal_contribution": mc,
            "standalone_return_pct": round(cum_ret * 100, 2),
            "sharpe": sr,
            "correlation_to_portfolio": round(corr_val, 4),
        })
        total_mc += abs(mc)

    # 计算贡献百分比
    for item in items_raw:
        item["contribution_pct"] = (
            round(
                (item["marginal_contribution"] / total_mc) * 100, 2
            )
            if total_mc > 0
            else 0.0
        )

    return items_raw


# ═══════════════════════════════════════════════════════════════
# 综合指标计算 (整合入口)
# ═══════════════════════════════════════════════════════════════


def compute_portfolio_metrics(
    portfolio_returns: pd.Series,
    strategy_returns: dict[str, pd.Series],
    weights: dict[str, float],
    benchmark_returns: Optional[pd.Series] = None,
    rf_annual: float = 0.03,
) -> dict:
    """一站式计算所有组合指标

    Args:
        portfolio_returns: 组合日收益率
        strategy_returns: 各策略日收益率
        weights: 各策略权重
        benchmark_returns: 基准日收益率 (可选)
        rf_annual: 年化无风险利率

    Returns:
        {
            # 绝对指标
            "cumulative_return_pct", ...
            # 基准对比 (如有基准)
            "active_return_pct", ...
            # 相关性
            "avg_cross_correlation", ...
            # 策略明细
            "strategy_metrics": {name: {...}, ...}
        }
    """
    # 1. 组合绝对指标
    abs_metrics = compute_portfolio_absolute_metrics(portfolio_returns, rf_annual)

    # 2. 策略明细指标
    strategy_metrics = {}
    for sname, s_ret in strategy_returns.items():
        aligned = s_ret.reindex(portfolio_returns.index).fillna(0)
        strategy_metrics[sname] = compute_portfolio_absolute_metrics(
            aligned, rf_annual
        )

    # 3. 基准对比
    benchmark_metrics = {}
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        benchmark_metrics = compute_benchmark_relative_metrics(
            portfolio_returns, benchmark_returns, rf_annual
        )

    # 4. 交叉相关性
    corr_matrix = compute_cross_correlation(strategy_returns)
    avg_corr = compute_avg_correlation(corr_matrix)

    # 5. 归因
    attribution = compute_attribution(
        strategy_returns, weights, portfolio_returns
    )

    result = {**abs_metrics}
    result.update(benchmark_metrics)
    result["avg_cross_correlation"] = avg_corr
    result["n_strategies"] = len(strategy_returns)
    result["strategy_metrics"] = strategy_metrics

    return result
