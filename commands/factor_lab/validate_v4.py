#!/usr/bin/env python3
"""
V4.3 因子验证 V4 — 新增半导体同池等权基准校验

扩展 V3 验证体系:
  - 新增 beats_semiconductor_peer, beats_core_peer, beats_matched_control
  - 新增 excess_vs_semiconductor_ew, excess_vs_core_ew, excess_vs_etf_basket
  - 废弃 beats_peer (全A截面同池等权)
  - 对比 V3 的 CSI300 超额保留但不作为晋级依据

与 validate_factor.py 共享数据加载和 IC 计算逻辑, 但校验部分使用新基准。
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

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent.parent  # research-assistant/
sys.path.insert(0, str(BASE / "commands"))
OUTPUT_DIR = BASE / "research_outputs" / "factor_validation_v4"


# ═══════════════════════════════════════════════════════════════════════════
# V4 基准对比
# ═══════════════════════════════════════════════════════════════════════════


def check_semiconductor_peer(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
) -> dict:
    """比较因子 Top-quantile 组合 vs 半导体核心池等权

    Args:
        df: 因子数据 (含 date, symbol, factor_col, ret1)
        factor_col: 因子列名
        close_pivot: 收盘价 pivot (date × symbol)
        top_quantile: 多头分位数

    Returns:
        {
            "beats_semiconductor_peer": bool,
            "excess_vs_semiconductor_ew": float (累计超额%),
            "excess_sharpe": float,
            ...
        }
    """
    # 获取半导体等权基准
    ensure_universes()
    bench_rets = get_benchmark_returns("semiconductor_ew")
    if bench_rets.empty:
        return {
            "beats_semiconductor_peer": False,
            "excess_vs_semiconductor_ew": 0,
            "error": "半导体等权基准无数据",
        }

    # 计算因子策略收益
    strat_rets = _compute_strategy_returns(df, factor_col, close_pivot, top_quantile)
    if strat_rets.empty:
        return {
            "beats_semiconductor_peer": False,
            "excess_vs_semiconductor_ew": 0,
            "error": "因子策略收益为空",
        }

    # 对齐日期
    common = strat_rets.index.intersection(bench_rets.index)
    if len(common) < 5:
        return {
            "beats_semiconductor_peer": False,
            "excess_vs_semiconductor_ew": 0,
            "error": f"日期重叠不足5天 (共{len(common)}天)",
        }

    s_ret = strat_rets.loc[common]
    b_ret = bench_rets.loc[common]
    excess = s_ret - b_ret

    s_cum = (1 + s_ret).cumprod()
    b_cum = (1 + b_ret).cumprod()

    beats = bool(s_cum.iloc[-1] > b_cum.iloc[-1])
    excess_cum_pct = float((s_cum.iloc[-1] / b_cum.iloc[-1] - 1) * 100)

    # 计算超额 Sharpe
    excess_sharpe = _sharpe(excess)

    return {
        "beats_semiconductor_peer": beats,
        "excess_vs_semiconductor_ew": round(excess_cum_pct, 2),
        "excess_sharpe": round(excess_sharpe, 4),
        "strategy_cum_pct": round((s_cum.iloc[-1] - 1) * 100, 2),
        "benchmark_cum_pct": round((b_cum.iloc[-1] - 1) * 100, 2),
        "n_days": len(common),
        "date_range": f"{common[0].date()} ~ {common[-1].date()}",
    }


def check_core_peer(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
) -> dict:
    """比较因子 Top-quantile vs 半导体核心池等权 (与 check_semiconductor_peer 相同)

    提供别名确保语义明确。
    """
    return check_semiconductor_peer(df, factor_col, close_pivot, top_quantile)


def check_matched_control(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
) -> dict:
    """比较因子 Top-quantile vs 匹配对照池等权"""
    ensure_universes()
    bench_rets = get_benchmark_returns("matched_control_ew")
    if bench_rets.empty:
        return {
            "beats_matched_control": False,
            "excess_vs_matched_control": 0,
            "error": "匹配对照等权基准无数据",
        }

    strat_rets = _compute_strategy_returns(df, factor_col, close_pivot, top_quantile)
    if strat_rets.empty:
        return {
            "beats_matched_control": False,
            "excess_vs_matched_control": 0,
            "error": "因子策略收益为空",
        }

    common = strat_rets.index.intersection(bench_rets.index)
    if len(common) < 5:
        return {
            "beats_matched_control": False,
            "excess_vs_matched_control": 0,
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
        "beats_matched_control": beats,
        "excess_vs_matched_control": round(excess_cum_pct, 2),
        "excess_sharpe": round(_sharpe(excess), 4),
        "strategy_cum_pct": round((s_cum.iloc[-1] - 1) * 100, 2),
        "benchmark_cum_pct": round((b_cum.iloc[-1] - 1) * 100, 2),
        "n_days": len(common),
    }


def check_etf_basket(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
) -> dict:
    """比较因子 Top-quantile vs ETF替代池等权"""
    ensure_universes()
    bench_rets = get_benchmark_returns("etf_basket_ew")
    if bench_rets.empty:
        return {
            "excess_vs_etf_basket": 0,
            "error": "ETF替代池等权基准无数据",
        }

    strat_rets = _compute_strategy_returns(df, factor_col, close_pivot, top_quantile)
    if strat_rets.empty:
        return {
            "excess_vs_etf_basket": 0,
            "error": "因子策略收益为空",
        }

    common = strat_rets.index.intersection(bench_rets.index)
    if len(common) < 5:
        return {
            "excess_vs_etf_basket": 0,
            "error": f"日期重叠不足5天 (共{len(common)}天)",
        }

    s_ret = strat_rets.loc[common]
    b_ret = bench_rets.loc[common]
    excess = s_ret - b_ret

    s_cum = (1 + s_ret).cumprod()
    b_cum = (1 + b_ret).cumprod()

    excess_cum_pct = float((s_cum.iloc[-1] / b_cum.iloc[-1] - 1) * 100)

    return {
        "excess_vs_etf_basket": round(excess_cum_pct, 2),
        "excess_sharpe": round(_sharpe(excess), 4),
        "strategy_cum_pct": round((s_cum.iloc[-1] - 1) * 100, 2),
        "benchmark_cum_pct": round((b_cum.iloc[-1] - 1) * 100, 2),
        "n_days": len(common),
    }


def _compute_strategy_returns(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> pd.Series:
    """计算因子 Top-quantile 策略的日收益率序列"""
    # 再平衡日期
    if rebalance == "monthly":
        rebal_dates = _first_trading_days(close_pivot.index)
    else:
        rebal_dates = close_pivot.index[::20]

    rebal_set = set(rebal_dates)
    daily_ret = close_pivot.pct_change()
    dates = close_pivot.index

    strat_rets = pd.Series(0.0, index=dates)
    prev_port: list = []

    for d in dates:
        if d in rebal_set:
            fday = df[df["date"] == d].set_index("symbol")[factor_col].dropna()
            if len(fday) < 20:
                prev_port = []
                continue
            sorted_vals = fday.sort_values(ascending=False)
            n_stocks = max(1, int(len(sorted_vals) * top_quantile))
            port = list(sorted_vals.index[:n_stocks])
        else:
            port = prev_port

        if not port or d not in daily_ret.index:
            strat_rets.loc[d] = 0.0
        else:
            port_ret = daily_ret.loc[d, [s for s in port if s in daily_ret.columns]]
            strat_rets.loc[d] = port_ret.mean() if len(port_ret) > 0 else 0.0

        prev_port = port

    return strat_rets.dropna()


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日"""
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    return pd.DatetimeIndex(
        s.groupby(dates.to_period("M")).apply(lambda x: x.index[0]).values
    )


def _sharpe(rets: pd.Series, ann: float = 252) -> float:
    if len(rets) < 5 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(ann))


# ═══════════════════════════════════════════════════════════════════════════
# V4 全量验证 (单因子)
# ═══════════════════════════════════════════════════════════════════════════


def validate_factor_v4(
    fname: str,
    df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    v3_result: Optional[dict] = None,
) -> dict:
    """V4 因子验证 — 新增半导体同池基准校验

    Args:
        fname: 因子名称
        df: 因子数据 DataFrame
        close_pivot: 收盘价 pivot
        v3_result: 可选, V3 验证结果 (避免重复计算 IC/WF/Placebo)

    Returns:
        result dict 包含:
          - 保留 V3 的 ic_analysis, anti_overfit, walk_forward, scoring 等
          - 新增 benchmark_v4 区块: beats_semiconductor_peer, excess_vs_* 等
    """
    result = dict(v3_result) if v3_result else {}

    # 确保 universes 已构建
    ensure_universes()

    print(f"\n📊 V4.3 同池基准校验: {fname}")

    # 1) 半导体核心等权
    print("  🔬 对比半导体核心池等权...")
    semi = check_semiconductor_peer(df, fname, close_pivot)
    result["beats_semiconductor_peer"] = semi.get("beats_semiconductor_peer", False)
    result["excess_vs_semiconductor_ew"] = semi.get("excess_vs_semiconductor_ew", 0)
    print(f"     beats={semi.get('beats_semiconductor_peer')}  "
          f"excess={semi.get('excess_vs_semiconductor_ew', 0):+.2f}%")

    # 2) 半导体核心等权 (core, 同 alias)
    core = check_core_peer(df, fname, close_pivot)
    result["beats_core_peer"] = core.get("beats_semiconductor_peer", False)
    result["excess_vs_core_ew"] = core.get("excess_vs_semiconductor_ew", 0)

    # 3) 匹配对照等权
    print("  🔬 对比匹配对照池等权...")
    mc = check_matched_control(df, fname, close_pivot)
    result["beats_matched_control"] = mc.get("beats_matched_control", False)
    result["excess_vs_matched_control"] = mc.get("excess_vs_matched_control", 0)
    print(f"     beats={mc.get('beats_matched_control')}  "
          f"excess={mc.get('excess_vs_matched_control', 0):+.2f}%")

    # 4) ETF 替代池
    print("  🔬 对比ETF替代池等权...")
    etf = check_etf_basket(df, fname, close_pivot)
    result["excess_vs_etf_basket"] = etf.get("excess_vs_etf_basket", 0)
    print(f"     excess={etf.get('excess_vs_etf_basket', 0):+.2f}%")

    # 5) V4 评分 — 同池门禁
    result["benchmark_v4"] = {
        "semiconductor": semi,
        "core": {
            "beats_core_peer": core.get("beats_semiconductor_peer", False),
            "excess_vs_core_ew": core.get("excess_vs_semiconductor_ew", 0),
        },
        "matched_control": mc,
        "etf_basket": etf,
    }

    # 晋级条件: 跑赢半导体核心等权 OR 跑赢核心等权
    promotion_eligible = (
        result.get("beats_semiconductor_peer", False)
        or result.get("beats_core_peer", False)
    )
    result["promotion_eligible"] = promotion_eligible
    print(f"  🏆 晋级资格: {'✅' if promotion_eligible else '❌'} "
          f"(需要 beats_semiconductor_peer OR beats_core_peer)")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Batch & output
# ═══════════════════════════════════════════════════════════════════════════


def clean(obj):
    """JSON 安全的序列化"""
    if isinstance(obj, dict):
        return {
            str(k) if not isinstance(k, (str, int, float, bool, type(None))) else k: clean(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [clean(v) for v in obj[:100]]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)


def save_v4_report(fname: str, result: dict):
    """保存 V4 验证报告"""
    d = OUTPUT_DIR / fname
    d.mkdir(parents=True, exist_ok=True)

    clean_result = clean(result)

    with open(d / "v4_report.json", "w", encoding="utf-8") as f:
        json.dump(clean_result, f, ensure_ascii=False, indent=2)
    print(f"  💾 V4 报告: {d / 'v4_report.json'}")
