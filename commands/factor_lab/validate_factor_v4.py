#!/usr/bin/env python3
"""
V4.4 因子评价与风险归因增强

在 V4.3 基础上新增:
  1. 换手率估计 (单边/双边)
  2. 交易成本后收益 (手续费0.025% + 印花税0.1% + 滑点0.05%)
  3. 最大回撤
  4. 胜率
  5. CAGR
  6. Calmar ratio
  7. 与所有 6 个基准对比 (excess_vs_*)
  8. 风险暴露归因 (市值/Beta/波动率/流动性/行业/Jackknife)

依赖:
  - benchmarks_v4  (6 基准体系)
  - factor_lab.risk_exposure  (风险暴露归因)
  - factor_lab.core.gate     (门禁引擎)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from benchmarks_v4 import (
    get_benchmark_returns,
    list_benchmarks,
    VALID_BENCHMARK_NAMES,
    ensure_universes,
)
from factor_lab.risk_exposure import RiskExposureAnalyzer

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent.parent  # research-assistant/
sys.path.insert(0, str(BASE / "commands"))
OUTPUT_DIR = BASE / "research_outputs" / "factor_validation_v4"

# ─── 交易成本参数 ─────────────────────────────────────────────────────────
COMMISSION_RATE = 0.00025      # 手续费 0.025%
STAMP_TAX_RATE = 0.001         # 印花税 0.1% (仅卖出)
SLIPPAGE_BPS = 0.0005           # 滑点 0.05%
TWO_WAY_COST = COMMISSION_RATE + SLIPPAGE_BPS  # 买入成本
ONE_WAY_COST = COMMISSION_RATE + STAMP_TAX_RATE + SLIPPAGE_BPS  # 卖出成本
TOTAL_ROUND_TRIP = TWO_WAY_COST + ONE_WAY_COST  # 单次完整双边交易成本


# ═══════════════════════════════════════════════════════════════════════════
# 增强指标计算
# ═══════════════════════════════════════════════════════════════════════════


def compute_turnover(
    portfolio_history: list[list[str]],
) -> tuple[float, float]:
    """计算策略换手率

    Args:
        portfolio_history: 每个再平衡日的持仓列表 [ [sym1, sym2, ...], ... ]

    Returns:
        (one_way_turnover_mean, two_way_turnover_mean) 日均换手率
    """
    if len(portfolio_history) < 2:
        return 0.0, 0.0

    turnovers = []
    for i in range(1, len(portfolio_history)):
        prev_set = set(portfolio_history[i - 1])
        curr_set = set(portfolio_history[i])
        if len(prev_set) == 0:
            continue
        # 换手: 不在上一期但出现在本期的 + 在上一期但不在本期的
        one_way = len(curr_set - prev_set) / len(prev_set)
        two_way = (len(curr_set - prev_set) + len(prev_set - curr_set)) / len(prev_set)
        turnovers.append((one_way, two_way))

    if not turnovers:
        return 0.0, 0.0

    one_way_mean = float(np.mean([t[0] for t in turnovers]))
    two_way_mean = float(np.mean([t[1] for t in turnovers]))
    return one_way_mean, two_way_mean


def compute_cost_adjusted_returns(
    daily_rets: pd.Series,
    rebal_dates: list,
    one_way_turnover: float,
    two_way_turnover: float,
) -> pd.Series:
    """计算交易成本后的日收益率序列

    Args:
        daily_rets: 原始策略日收益率 (已含 rebalance 调仓)
        rebal_dates: 再平衡日期列表
        one_way_turnover: 单边换手率
        two_way_turnover: 双边换手率

    Returns:
        成本调整后的日收益率序列 (与 daily_rets 同长度的 pd.Series)
    """
    cost_adjusted = daily_rets.copy()

    rebal_set = set(pd.DatetimeIndex(rebal_dates).normalize())
    for d in cost_adjusted.index:
        d_norm = d.normalize() if hasattr(d, "normalize") else pd.Timestamp(d).normalize()
        if d_norm in rebal_set:
            # 再平衡日扣除调仓成本
            # 买入部分: commission + slippage
            # 卖出部分: commission + stamp_tax + slippage
            # 近似: 用双边换手率 * 平均成本
            trade_cost = two_way_turnover * (
                (COMMISSION_RATE + SLIPPAGE_BPS) * 0.5
                + (COMMISSION_RATE + STAMP_TAX_RATE + SLIPPAGE_BPS) * 0.5
            )
            cost_adjusted.loc[d] = cost_adjusted.loc[d] - trade_cost

    return cost_adjusted


def compute_max_drawdown(rets: pd.Series) -> float:
    """计算最大回撤 (百分比, 正值表示回撤幅度)"""
    if len(rets) < 2:
        return 0.0
    cum = (1 + rets).cumprod()
    peak = cum.expanding().max()
    dd = (peak - cum) / peak
    return float(dd.max())


def compute_win_rate(rets: pd.Series) -> float:
    """计算胜率: 正收益率天数 / 总交易天数"""
    if len(rets) == 0:
        return 0.0
    return float((rets > 0).sum() / len(rets))


def compute_cagr(rets: pd.Series, ann_periods: int = 252) -> float:
    """计算年化收益率 (CAGR)"""
    if len(rets) < 2:
        return 0.0
    total_ret = (1 + rets).prod() - 1
    years = len(rets) / ann_periods
    if years <= 0:
        return 0.0
    return float((1 + total_ret) ** (1 / years) - 1)


def compute_calmar(cagr: float, max_dd: float) -> float:
    """计算 Calmar Ratio = CAGR / Max Drawdown"""
    if max_dd == 0:
        return 0.0
    return cagr / max_dd


def compute_enhanced_metrics(
    strategy_rets: pd.Series,
    portfolio_history: Optional[list[list[str]]] = None,
    rebal_dates: Optional[list] = None,
    ann_periods: int = 252,
) -> dict:
    """计算增强绩效指标

    Args:
        strategy_rets: 策略日收益率序列
        portfolio_history: 每个再平衡日的持仓列表 (用于换手率)
        rebal_dates: 再平衡日期列表 (用于成本计算)
        ann_periods: 年化周期数 (日频=252)

    Returns:
        {
            "one_way_turnover": float,
            "two_way_turnover": float,
            "cost_adjusted_return_pct": float,
            "max_drawdown_pct": float,
            "win_rate": float,
            "cagr_pct": float,
            "calmar_ratio": float,
        }
    """
    if len(strategy_rets) == 0:
        return {
            "one_way_turnover": 0,
            "two_way_turnover": 0,
            "cost_adjusted_return_pct": 0,
            "max_drawdown_pct": 0,
            "win_rate": 0,
            "cagr_pct": 0,
            "calmar_ratio": 0,
        }

    # 1. 换手率
    one_way_turn, two_way_turn = 0.0, 0.0
    if portfolio_history and len(portfolio_history) > 1:
        one_way_turn, two_way_turn = compute_turnover(portfolio_history)

    # 2. 成本后收益
    if rebal_dates and two_way_turn > 0:
        cost_adj_rets = compute_cost_adjusted_returns(
            strategy_rets, rebal_dates, one_way_turn, two_way_turn
        )
        cost_adj_cum = float(((1 + cost_adj_rets).prod() - 1) * 100)
    else:
        cost_adj_cum = 0.0

    # 3. 最大回撤
    max_dd = compute_max_drawdown(strategy_rets)

    # 4. 胜率
    win_rate = compute_win_rate(strategy_rets)

    # 5. CAGR
    cagr = compute_cagr(strategy_rets, ann_periods)

    # 6. Calmar
    calmar = compute_calmar(cagr, max_dd)

    return {
        "one_way_turnover": round(one_way_turn, 4),
        "two_way_turnover": round(two_way_turn, 4),
        "cost_adjusted_return_pct": round(cost_adj_cum, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate": round(win_rate, 4),
        "cagr_pct": round(cagr * 100, 2),
        "calmar_ratio": round(calmar, 4),
    }


# ═══════════════════════════════════════════════════════════════════════════
# V4.4 多基准对比 (全部 6 个基准)
# ═══════════════════════════════════════════════════════════════════════════


def check_benchmark(
    name: str,
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
) -> dict:
    """比较因子 Top-quantile vs 指定基准等权

    Args:
        name: 基准名称 (来自 VALID_BENCHMARK_NAMES)
        df: 因子数据
        factor_col: 因子列名
        close_pivot: 收盘价 pivot
        top_quantile: 多头分位数

    Returns:
        {
            f"beats_{name}": bool,
            f"excess_vs_{name}": float (累计超额%),
            "excess_sharpe": float,
            "strategy_cum_pct": float,
            "benchmark_cum_pct": float,
            "n_days": int,
        }
    """
    ensure_universes()
    bench_rets = get_benchmark_returns(name)
    if bench_rets.empty:
        return {
            f"beats_{name}": False,
            f"excess_vs_{name}": 0,
            "error": f"{name} 基准无数据",
        }

    strat_rets = _compute_strategy_returns(df, factor_col, close_pivot, top_quantile)
    if strat_rets.empty:
        return {
            f"beats_{name}": False,
            f"excess_vs_{name}": 0,
            "error": "因子策略收益为空",
        }

    common = strat_rets.index.intersection(bench_rets.index)
    if len(common) < 5:
        return {
            f"beats_{name}": False,
            f"excess_vs_{name}": 0,
            "error": f"日期重叠不足5天 (共{len(common)}天)",
        }

    s_ret = strat_rets.loc[common]
    b_ret = bench_rets.loc[common]
    excess = s_ret - b_ret

    s_cum = (1 + s_ret).cumprod()
    b_cum = (1 + b_ret).cumprod()

    beats = bool(s_cum.iloc[-1] > b_cum.iloc[-1])
    excess_cum_pct = float((s_cum.iloc[-1] / b_cum.iloc[-1] - 1) * 100)

    return {
        f"beats_{name}": beats,
        f"excess_vs_{name}": round(excess_cum_pct, 2),
        "excess_sharpe": round(_sharpe(excess), 4),
        "strategy_cum_pct": round((s_cum.iloc[-1] - 1) * 100, 2),
        "benchmark_cum_pct": round((b_cum.iloc[-1] - 1) * 100, 2),
        "n_days": len(common),
        "date_range": f"{common[0].date()} ~ {common[-1].date()}",
    }


# ═══════════════════════════════════════════════════════════════════════════
# V4.4 全量验证入口
# ═══════════════════════════════════════════════════════════════════════════


def validate_factor_v44(
    fname: str,
    df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    v3_result: Optional[dict] = None,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    extra_data: Optional[dict] = None,
) -> dict:
    """V4.4 因子验证 — 增强评价 + 多基准对比 + 风险归因

    Args:
        fname: 因子名称
        df: 因子数据 DataFrame (含 date, symbol, fname 因子列, close)
        close_pivot: 收盘价 pivot (date × symbol)
        v3_result: 可选, V3 验证结果
        top_quantile: 多头分组分位数 (默认 0.2)
        rebalance: 再平衡频率 (默认 monthly)
        extra_data: 可选额外数据, 包含:
            - "market_cap": DataFrame 市值数据
            - "beta": Series/DataFrame Beta 数据
            - "industry": Series 行业分类
            - "amount": DataFrame 成交额数据

    Returns:
        完整验证结果 dict
    """
    result = dict(v3_result) if v3_result else {}

    ensure_universes()

    print(f"\n{'=' * 56}")
    print(f"📊 V4.4 因子增强评价: {fname}")
    print(f"{'=' * 56}")

    # ─── 1. 策略收益 + 持仓历史 ────────────────────────────────────────
    strat_rets, portfolio_history, rebals = _compute_strategy_returns_detailed(
        df, fname, close_pivot, top_quantile, rebalance
    )
    result["n_returns"] = len(strat_rets)

    # ─── 2. 增强指标 ────────────────────────────────────────────────────
    print(f"\n  📈 增强绩效指标...")
    enhanced = compute_enhanced_metrics(
        strat_rets,
        portfolio_history=portfolio_history,
        rebal_dates=rebals,
    )
    result["enhanced_metrics"] = enhanced

    print(f"     换手率(单边): {enhanced['one_way_turnover']:.2%}")
    print(f"     换手率(双边): {enhanced['two_way_turnover']:.2%}")
    print(f"     成本后累计收益: {enhanced['cost_adjusted_return_pct']:+.2f}%")
    print(f"     最大回撤: {enhanced['max_drawdown_pct']:.2f}%")
    print(f"     胜率: {enhanced['win_rate']:.2%}")
    print(f"     CAGR: {enhanced['cagr_pct']:+.2f}%")
    print(f"     Calmar Ratio: {enhanced['calmar_ratio']:.4f}")

    # ─── 3. 所有基准对比 (6 个) ─────────────────────────────────────────
    print(f"\n  🔬 多基准对比 (6 个基准)...")
    benchmark_results = {}
    promotion_counts = 0

    for bname in sorted(VALID_BENCHMARK_NAMES):
        bc = check_benchmark(bname, df, fname, close_pivot, top_quantile)
        benchmark_results[bname] = bc

        # 存储 beats_* 和 excess_vs_* 到顶层 result
        beats_key = f"beats_{bname}"
        excess_key = f"excess_vs_{bname}"
        if beats_key in bc:
            result[beats_key] = bc[beats_key]
            if bc[beats_key]:
                promotion_counts += 1
        if excess_key in bc:
            result[excess_key] = bc[excess_key]

        excess_val = bc.get(excess_key, 0)
        beats_val = bc.get(beats_key, False)
        print(f"     {bname:30s}  excess={excess_val:+.2f}%  beats={beats_val}")

    result["benchmark_comparisons"] = benchmark_results
    result["n_beaten_benchmarks"] = promotion_counts

    # ─── 4. V4.3 向后兼容字段 ───────────────────────────────────────────
    # 确保 V4.3 消费者也能用
    semi = benchmark_results.get("semiconductor_ew", {})
    core = benchmark_results.get("semiconductor_core_ew", {})
    mc = benchmark_results.get("matched_control_ew", {})
    etf = benchmark_results.get("etf_basket_ew", {})

    result["beats_semiconductor_peer"] = semi.get("beats_semiconductor_ew", False)
    result["excess_vs_semiconductor_ew"] = semi.get("excess_vs_semiconductor_ew", 0)
    result["beats_core_peer"] = core.get("beats_semiconductor_core_ew", False)
    result["excess_vs_core_ew"] = core.get("excess_vs_semiconductor_core_ew", 0)
    result["beats_matched_control"] = mc.get("beats_matched_control_ew", False)
    result["excess_vs_matched_control"] = mc.get("excess_vs_matched_control_ew", 0)
    result["excess_vs_etf_basket"] = etf.get("excess_vs_etf_basket_ew", 0)

    # V4.3 兼容的 benchmark_v4 区块
    result["benchmark_v4"] = {
        "semiconductor": semi,
        "core": {
            "beats_core_peer": core.get("beats_semiconductor_core_ew", False),
            "excess_vs_core_ew": core.get("excess_vs_semiconductor_core_ew", 0),
        },
        "matched_control": mc,
        "etf_basket": etf,
    }

    # 晋级条件 (与 V4.3 保持一致)
    promotion_eligible = (
        result.get("beats_semiconductor_peer", False)
        or result.get("beats_core_peer", False)
    )
    result["promotion_eligible"] = promotion_eligible
    print(f"\n  🏆 晋级资格: {'✅' if promotion_eligible else '❌'} "
          f"(beats_semiconductor_peer OR beats_core_peer)")

    # ─── 5. 风险暴露归因 ──────────────────────────────────────────────
    print(f"\n  ⚠️  风险暴露归因...")
    try:
        analyzer = RiskExposureAnalyzer(close_pivot=close_pivot)
        risk_result = analyzer.analyze(
            df=df,
            factor_col=fname,
            top_quantile=top_quantile,
            extra_data=extra_data,
        )
        result["risk_exposure"] = risk_result
        print(f"     市值暴露 R²: {risk_result.get('market_cap_r2', 'N/A')}")
        print(f"     Beta 暴露 R²: {risk_result.get('beta_r2', 'N/A')}")
        print(f"     波动率暴露 R²: {risk_result.get('volatility_r2', 'N/A')}")
        print(f"     流动性暴露 R²: {risk_result.get('liquidity_r2', 'N/A')}")
        print(f"     行业暴露 R²: {risk_result.get('industry_r2', 'N/A')}")
        print(f"     Jackknife max impact: {risk_result.get('jackknife_max_impact', 'N/A')}")
        print(f"     暴露类型: {risk_result.get('exposure_type', 'unknown')}")
    except Exception as e:
        logger.warning(f"风险归因失败: {e}")
        result["risk_exposure"] = {"error": str(e)}

    # ─── 6. 最终评分 ─────────────────────────────────────────────────────
    scoring = _compute_v44_score(result)
    result["v44_score"] = scoring
    print(f"\n  📊 V4.4 综合评分: {scoring['total']:.1f}/100")
    print(f"     IC 质量: {scoring['ic_quality']:.1f}/30 | "
          f"基准: {scoring['benchmark_score']:.1f}/25 | "
          f"风控: {scoring['risk_score']:.1f}/20 | "
          f"稳定性: {scoring['stability_score']:.1f}/15 | "
          f"成本效率: {scoring['cost_efficiency']:.1f}/10")

    return result


def _compute_v44_score(result: dict) -> dict:
    """计算 V4.4 综合评分 (满分 100)"""
    score = {}
    enhanced = result.get("enhanced_metrics", {})

    # IC 质量 (30分)
    ic_quality = 15.0  # 基础分
    cagr = enhanced.get("cagr_pct", 0)
    sharpe = result.get("sharpe", 0)
    if cagr > 10:
        ic_quality += 10
    elif cagr > 5:
        ic_quality += 5
    if sharpe > 1.5:
        ic_quality += 5
    elif sharpe > 1.0:
        ic_quality += 3
    ic_quality = min(ic_quality, 30)
    score["ic_quality"] = ic_quality

    # 基准评分 (25分)
    n_beaten = result.get("n_beaten_benchmarks", 0)
    benchmark_score = min(n_beaten * 4, 25)
    score["benchmark_score"] = benchmark_score

    # 风控评分 (20分)
    risk_score = 10.0  # 基础分
    max_dd = enhanced.get("max_drawdown_pct", 100)
    if max_dd < 5:
        risk_score += 5
    elif max_dd < 10:
        risk_score += 3
    if enhanced.get("calmar_ratio", 0) > 1.0:
        risk_score += 5
    elif enhanced.get("calmar_ratio", 0) > 0.5:
        risk_score += 3
    risk_score = min(risk_score, 20)
    score["risk_score"] = risk_score

    # 稳定性 (15分)
    win_rate = enhanced.get("win_rate", 0)
    stability = 5.0
    if win_rate > 0.55:
        stability += 5
    elif win_rate > 0.50:
        stability += 3
    if enhanced.get("cost_adjusted_return_pct", 0) > 0:
        stability += 5
    stability = min(stability, 15)
    score["stability_score"] = stability

    # 成本效率 (10分)
    turnover = enhanced.get("two_way_turnover", 1)
    cost_efficiency = 10.0
    if turnover < 0.1:
        cost_efficiency = 10
    elif turnover < 0.3:
        cost_efficiency = 8
    elif turnover < 0.5:
        cost_efficiency = 5
    elif turnover < 1.0:
        cost_efficiency = 3
    else:
        cost_efficiency = 1
    score["cost_efficiency"] = cost_efficiency

    score["total"] = round(ic_quality + benchmark_score + risk_score + stability + cost_efficiency, 1)
    return score


# ═══════════════════════════════════════════════════════════════════════════
# 内部辅助函数 (从 validate_v4.py 复制并增强)
# ═══════════════════════════════════════════════════════════════════════════


def _compute_strategy_returns_detailed(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> tuple[pd.Series, list[list[str]], list]:
    """计算因子 Top-quantile 策略的日收益率 + 持仓历史 + 再平衡日期

    Returns:
        (strat_rets, portfolio_history, rebal_dates)
    """
    if rebalance == "monthly":
        rebal_dates = list(_first_trading_days(close_pivot.index))
    elif rebalance == "weekly":
        rebal_dates = list(close_pivot.index[::5])
    else:
        rebal_dates = list(close_pivot.index[::20])

    rebal_set = set(rebal_dates)
    daily_ret = close_pivot.pct_change()
    dates = close_pivot.index

    strat_rets = pd.Series(0.0, index=dates)
    portfolio_history: list[list[str]] = []
    prev_port: list = []

    for d in dates:
        if d in rebal_set:
            fday = df[df["date"] == d].set_index("symbol")[factor_col].dropna()
            if len(fday) < 20:
                prev_port = []
                portfolio_history.append([])
                continue
            sorted_vals = fday.sort_values(ascending=False)
            n_stocks = max(1, int(len(sorted_vals) * top_quantile))
            port = list(sorted_vals.index[:n_stocks])
            portfolio_history.append(port)
        else:
            port = prev_port

        if not port or d not in daily_ret.index:
            strat_rets.loc[d] = 0.0
        else:
            port_symbols = [s for s in port if s in daily_ret.columns]
            port_ret = daily_ret.loc[d, port_symbols]
            strat_rets.loc[d] = port_ret.mean() if len(port_ret) > 0 else 0.0

        prev_port = port

    return strat_rets.dropna(), portfolio_history, rebal_dates


def _compute_strategy_returns(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> pd.Series:
    """计算因子 Top-quantile 策略的日收益率序列 (简化版)"""
    rets, _, _ = _compute_strategy_returns_detailed(
        df, factor_col, close_pivot, top_quantile, rebalance
    )
    return rets


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日"""
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    return pd.DatetimeIndex(
        s.groupby(dates.to_period("M")).apply(lambda x: x.index[0]).values
    )


def _sharpe(rets: pd.Series, ann: float = 252) -> float:
    if len(rets) < 5 or rets.std(ddof=0) == 0:
        return 0.0
    return float(rets.mean() / rets.std(ddof=0) * np.sqrt(ann))


# ═══════════════════════════════════════════════════════════════════════════
# V4.3 向后兼容函数
# ═══════════════════════════════════════════════════════════════════════════


def validate_factor_v4(
    fname: str,
    df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    v3_result: Optional[dict] = None,
) -> dict:
    """V4.3 向后兼容入口 — 委托给 V4.4"""
    result = validate_factor_v44(
        fname, df, close_pivot, v3_result=v3_result,
    )
    # 移除 V4.4 新增字段以保持兼容
    result.pop("enhanced_metrics", None)
    result.pop("benchmark_comparisons", None)
    result.pop("n_beaten_benchmarks", None)
    result.pop("risk_exposure", None)
    result.pop("v44_score", None)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Serialization
# ═══════════════════════════════════════════════════════════════════════════


def clean(obj):
    """JSON 安全的序列化"""
    if isinstance(obj, dict):
        return {
            str(k) if not isinstance(k, (str, int, float, bool, type(None))) else k: clean(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [clean(v) for v in obj[:200]]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)


def save_v44_report(fname: str, result: dict):
    """保存 V4.4 验证报告"""
    d = OUTPUT_DIR / fname
    d.mkdir(parents=True, exist_ok=True)

    clean_result = clean(result)

    with open(d / "v44_report.json", "w", encoding="utf-8") as f:
        json.dump(clean_result, f, ensure_ascii=False, indent=2)
    print(f"  💾 V4.4 报告: {d / 'v44_report.json'}")

    # 简短的 Markdown 摘要
    _save_v44_markdown(d, fname, clean_result)


def _save_v44_markdown(output_dir: Path, fname: str, result: dict):
    """生成 Markdown 摘要报告"""
    enhanced = result.get("enhanced_metrics", {})
    benchmark_comps = result.get("benchmark_comparisons", {})
    risk_exp = result.get("risk_exposure", {})
    scoring = result.get("v44_score", {})

    lines = [
        f"# V4.4 因子评价报告: {fname}",
        f"",
        f"## 增强绩效指标",
        f"| 指标 | 值 |",
        f"|---|---|",
        f"| CAGR | {enhanced.get('cagr_pct', 'N/A')}% |",
        f"| 最大回撤 | {enhanced.get('max_drawdown_pct', 'N/A')}% |",
        f"| Calmar Ratio | {enhanced.get('calmar_ratio', 'N/A')} |",
        f"| 胜率 | {enhanced.get('win_rate', 'N/A'):.2%} |" if enhanced.get('win_rate') else "",
        f"| 换手率(单边) | {enhanced.get('one_way_turnover', 'N/A'):.2%} |" if enhanced.get('one_way_turnover') else "",
        f"| 换手率(双边) | {enhanced.get('two_way_turnover', 'N/A'):.2%} |" if enhanced.get('two_way_turnover') else "",
        f"| 成本后收益 | {enhanced.get('cost_adjusted_return_pct', 'N/A')}% |",
        f"",
    ]
    # Filter empty lines (None from format)
    lines = [l for l in lines if l is not None]

    lines.append(f"## 多基准对比")
    lines.append(f"| 基准 | 累计超额 | Beats |")
    lines.append(f"|---|---|---|")
    for bname, bc in sorted(benchmark_comps.items()):
        excess_key = f"excess_vs_{bname}"
        beats_key = f"beats_{bname}"
        excess_val = bc.get(excess_key, bc.get("excess_vs_semiconductor_ew", "N/A"))
        beats_val = bc.get(beats_key, bc.get("beats_semiconductor_peer", "N/A"))
        lines.append(f"| {bname} | {excess_val}% | {beats_val} |")

    lines.append(f"")
    lines.append(f"## 风险暴露归因")
    lines.append(f"| 暴露类型 | R² |")
    lines.append(f"|---|---|")
    for key in ["market_cap_r2", "beta_r2", "volatility_r2", "liquidity_r2", "industry_r2"]:
        val = risk_exp.get(key, "N/A")
        lines.append(f"| {key} | {val} |")
    if risk_exp.get("exposure_type"):
        lines.append(f"| 暴露类型 | {risk_exp['exposure_type']} |")

    lines.append(f"")
    lines.append(f"## V4.4 综合评分")
    lines.append(f"| 维度 | 得分 |")
    lines.append(f"|---|---|")
    if scoring:
        lines.append(f"| IC 质量 | {scoring.get('ic_quality', 'N/A')}/30 |")
        lines.append(f"| 基准 | {scoring.get('benchmark_score', 'N/A')}/25 |")
        lines.append(f"| 风控 | {scoring.get('risk_score', 'N/A')}/20 |")
        lines.append(f"| 稳定性 | {scoring.get('stability_score', 'N/A')}/15 |")
        lines.append(f"| 成本效率 | {scoring.get('cost_efficiency', 'N/A')}/10 |")
        lines.append(f"| **总分** | **{scoring.get('total', 'N/A')}/100** |")

    md_path = output_dir / "v44_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  💾 Markdown 摘要: {md_path}")


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════


def cmd_v44_validate(factor_name: str, **kwargs):
    """CLI 入口: 对单个因子执行 V4.4 验证

    用法:
        python3 hermes_cli.py factor:validate-v4 --factor ret5
            [--start 2025-01-02] [--end 2026-06-30] [--rebalance monthly]
    """
    from factor_lab.factor_engine import Engine

    e = Engine()
    e.load_all()

    f = e.get_factor(factor_name)
    if f is None:
        print(f"❌ 因子 {factor_name} 未找到")
        return {}

    df = f.get("df") if hasattr(f, "__getitem__") else getattr(f, "df", None)
    close_pivot = f.get("close_pivot") if hasattr(f, "__getitem__") else getattr(f, "close_pivot", None)

    if df is None or close_pivot is None:
        print(f"❌ 因子 {factor_name} 缺少数据 (df/close_pivot)")
        return {}

    result = validate_factor_v44(
        factor_name, df, close_pivot,
        top_quantile=float(kwargs.get("top_quantile", 0.2)),
        rebalance=kwargs.get("rebalance", "monthly"),
    )

    save_v44_report(factor_name, result)
    return result


if __name__ == "__main__":
    # 简单 CLI 测试
    import sys
    factor_name = sys.argv[1] if len(sys.argv) > 1 else "ret5"
    result = cmd_v44_validate(factor_name)
    print(json.dumps(clean(result), indent=2, ensure_ascii=False)[:5000])
