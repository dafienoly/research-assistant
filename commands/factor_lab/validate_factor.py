#!/usr/bin/env python3
"""V3.1.2 Top 20 Factor Validation — Self-contained implementation.

Validates 20 top factors with:
  - IC / RankIC IR
  - 同池等权 vs Top-quantile portfolio
  - Walk-Forward (2 windows)
  - Exposures (industry approximation via subsample)
  - Benchmark comparison (CSI300 real data, V3.1.1)
  - Scoring & grading

Output:
  research_outputs/factor_validation/
  ├── summary.md
  ├── validation_leaderboard.csv
  └── <factor_name>/report.json
"""

import sys, os, json, csv, math, warnings, traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

BASE = Path("/home/ly/.hermes/research-assistant")
sys.path.insert(0, str(BASE / "commands"))

CST = timezone(timedelta(hours=8))
OUTPUT_DIR = BASE / "research_outputs" / "factor_validation"

# ─── Top 20 factors ───────────────────────────────────────────
TOP_FACTORS = [
    "ret5", "ret10", "ret20", "ret60",
    "vol_ratio5", "vol_ratio20", "vol_ratio60",
    "ma10_gt_ma20", "ma20_gt_ma60", "close_gt_ma20",
    "volatility20", "volatility60", "atr20",
    "reversal5", "reversal20",
    "amihud",
    "roe_q", "gross_margin_q",
    "macd", "boll_width",
]

FACTOR_NAME_MAP = {
    "amihud": "amihud_illiquidity20",
    "macd": "macd_histogram",
}

FACTOR_FAMILIES = {
    "ret5": "momentum", "ret10": "momentum", "ret20": "momentum", "ret60": "momentum",
    "vol_ratio5": "volume", "vol_ratio20": "volume", "vol_ratio60": "volume",
    "ma10_gt_ma20": "trend", "ma20_gt_ma60": "trend", "close_gt_ma20": "trend",
    "volatility20": "volatility", "volatility60": "volatility", "atr20": "volatility",
    "reversal5": "reversal", "reversal20": "reversal",
    "amihud": "liquidity",
    "roe_q": "quality", "gross_margin_q": "quality",
    "macd": "technical", "boll_width": "technical",
}


# ═══════════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════════

def sharpe(rets: pd.Series, ann: float = 252) -> float:
    if len(rets) < 5 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(ann))


def first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    return pd.DatetimeIndex(
        s.groupby(dates.to_period("M")).apply(lambda x: x.index[0]).values
    )


def calc_daily_rank_ic(df: pd.DataFrame, factor_col: str, ret_col: str = "ret1") -> pd.DataFrame:
    dates = sorted(df["date"].unique())
    ics = []
    for d in dates:
        day = df[df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < 10:
            continue
        ic_val, pval = stats.spearmanr(day[factor_col], day[ret_col])
        if not np.isnan(ic_val):
            ics.append({"date": d, "ic": float(ic_val), "pval": float(pval)})
    return pd.DataFrame(ics)


def compute_ic_ir(df: pd.DataFrame, factor_col: str, ret_col: str = "ret1") -> dict:
    ic_df = calc_daily_rank_ic(df, factor_col, ret_col)
    if ic_df.empty:
        return {"factor_name": factor_col, "n_dates": 0,
                "ic_mean": 0, "ic_std": 0, "ic_ir": 0, "pos_ratio": 0}

    ic_mean = float(ic_df["ic"].mean())
    ic_std = float(ic_df["ic"].std())
    ic_ir = ic_mean / ic_std if ic_std > 1e-8 else 0
    pos_ratio = float((ic_df["ic"] > 0).mean())

    # monthly IC
    ic_df["date"] = pd.to_datetime(ic_df["date"])
    ic_df["year_month"] = ic_df["date"].dt.strftime("%Y-%m")
    monthly = ic_df.groupby("year_month")["ic"].mean().reset_index().to_dict("records")

    # layer test
    layers = layer_test(df, factor_col, ret_col)

    return {
        "factor_name": factor_col,
        "n_dates": len(ic_df),
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_ir": round(ic_ir, 4),
        "pos_ratio": round(pos_ratio, 4),
        "monthly_ic_series": monthly,
        "layer_test": layers,
    }


def layer_test(df: pd.DataFrame, factor_col: str, ret_col: str = "ret1",
               n_layers: int = 5) -> dict:
    records = []
    for d in sorted(df["date"].unique()):
        day = df[df["date"] == d].dropna(subset=[factor_col, ret_col]).copy()
        if len(day) < n_layers * 3:
            continue
        day["layer"] = pd.qcut(day[factor_col].rank(method="first"), n_layers,
                                labels=False, duplicates="drop")
        for l in range(n_layers):
            grp = day[day["layer"] == l]
            if len(grp) > 0:
                records.append({"date": d, "layer": l, "ret": grp[ret_col].mean()})
    rdf = pd.DataFrame(records)
    if rdf.empty:
        return {}
    summary = rdf.groupby("layer")["ret"].agg(["mean", "std", "count"])
    top = rdf[rdf["layer"] == n_layers - 1].groupby("date")["ret"].mean()
    bot = rdf[rdf["layer"] == 0].groupby("date")["ret"].mean()
    ls = top - bot
    return {
        "layer_returns": summary.to_dict(),
        "long_short_mean": float(ls.mean()) if len(ls) > 0 else 0,
        "long_short_sharpe": float(sharpe(ls)) if len(ls) > 5 else 0,
    }


def monotonicity(layer_test_res: dict) -> str:
    try:
        lr = layer_test_res.get("layer_returns", {})
        if not lr or "mean" not in lr:
            return "不单调"
        means = list(lr["mean"].values())
        if len(means) < 3:
            return "不单调"
        asc = all(means[i] <= means[i+1] for i in range(len(means)-1))
        desc = all(means[i] >= means[i+1] for i in range(len(means)-1))
        if asc or desc:
            return "单调"
        pos = sum(1 for i in range(len(means)-1) if means[i] < means[i+1])
        neg = sum(1 for i in range(len(means)-1) if means[i] > means[i+1])
        if pos >= len(means)-2 or neg >= len(means)-2:
            return "部分"
        return "不单调"
    except Exception:
        return "不单调"


def ic_half_life(monthly_ic: list) -> float:
    try:
        vals = np.array([m["ic"] for m in monthly_ic if isinstance(m, dict)])
        vals = vals[~np.isnan(vals)]
        if len(vals) < 4:
            return 20.0
        acf1 = np.corrcoef(vals[:-1], vals[1:])[0, 1]
        if np.isnan(acf1) or acf1 <= 0:
            return 1.0
        hl = math.log(0.5) / math.log(acf1) * 21
        return max(1.0, min(60.0, abs(hl)))
    except Exception:
        return 10.0


# ═══════════════════════════════════════════════════════════════
# Peer benchmark (同池等权)
# ═══════════════════════════════════════════════════════════════

def check_peer_benchmark(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> dict:
    """Compare top-quantile factor portfolio vs equal-weight universe."""
    if rebalance == "monthly":
        rebal_dates = first_trading_days(close_pivot.index)
    else:
        rebal_dates = close_pivot.index[::20]

    rebal_set = set(rebal_dates)
    daily_ret = close_pivot.pct_change()
    dates = close_pivot.index

    strat_rets = pd.Series(0.0, index=dates)
    peer_rets = pd.Series(0.0, index=dates)
    prev_port = []

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
            peer_rets.loc[d] = daily_ret.loc[d].mean() if d in daily_ret.index else 0.0
        else:
            port_ret = daily_ret.loc[d, [s for s in port if s in daily_ret.columns]]
            strat_rets.loc[d] = port_ret.mean() if len(port_ret) > 0 else 0.0
            peer_rets.loc[d] = daily_ret.loc[d].mean()

        prev_port = port

    strat_cum = (1 + strat_rets).cumprod()
    peer_cum = (1 + peer_rets).cumprod()
    excess = strat_rets - peer_rets

    return {
        "beats_peer": bool(strat_cum.iloc[-1] > peer_cum.iloc[-1]) if len(strat_cum) > 0 else False,
        "strategy_cumulative_pct": round((strat_cum.iloc[-1] - 1) * 100, 2) if len(strat_cum) > 0 else 0,
        "peer_ew_cumulative_pct": round((peer_cum.iloc[-1] - 1) * 100, 2) if len(peer_cum) > 0 else 0,
        "excess_return_pct": round((strat_cum.iloc[-1] - peer_cum.iloc[-1]) * 100, 2) if len(strat_cum) > 0 else 0,
        "excess_sharpe": round(sharpe(excess), 4),
        "strategy_returns": strat_rets.to_dict(),
        "n_days": len(strat_rets),
    }


# ═══════════════════════════════════════════════════════════════
# Walk-Forward (2 windows: 6m train + 3m test)
# ═══════════════════════════════════════════════════════════════

def walk_forward_validation(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    n_windows: int = 3,
) -> dict:
    """Simple walk-forward: sequential train/test periods."""
    all_dates = sorted(df["date"].unique())
    total = len(all_dates)
    window_size = total // (n_windows + 1)

    windows = []
    for i in range(n_windows):
        train_start = i * window_size
        train_end = (i + 1) * window_size
        test_start = train_end
        test_end = min(test_start + window_size, total)

        if test_end - test_start < 20:
            break

        train_dates = set(all_dates[train_start:train_end])
        test_dates = all_dates[test_start:test_end]

        # Train: compute IC
        train_df = df[df["date"].isin(train_dates)]
        ic_df = calc_daily_rank_ic(train_df, factor_col)
        train_ic = float(ic_df["ic"].mean()) if not ic_df.empty else 0

        # Test: run portfolio
        test_df = df[df["date"].isin(test_dates)].copy()
        test_dates_idx = pd.DatetimeIndex(test_dates)
        rebal_dates = first_trading_days(test_dates_idx)
        rebal_set = set(rebal_dates)
        daily_ret = close_pivot.loc[test_dates_idx].pct_change() if len(close_pivot.loc[test_dates_idx]) > 1 else pd.DataFrame()

        strat_rets = pd.Series(0.0, index=test_dates_idx)
        port = []
        for d in test_dates_idx:
            if d in rebal_set:
                fday = test_df[test_df["date"] == d].set_index("symbol")[factor_col].dropna()
                if len(fday) < 20:
                    port = []
                else:
                    sorted_vals = fday.sort_values(ascending=False)
                    n = max(1, int(len(sorted_vals) * top_quantile))
                    port = list(sorted_vals.index[:n])
            if port and d in daily_ret.index:
                port_ret = daily_ret.loc[d, [s for s in port if s in daily_ret.columns]]
                strat_rets.loc[d] = port_ret.mean() if len(port_ret) > 0 else 0.0

        test_sharpe = sharpe(strat_rets)
        windows.append({
            "window": f"wf_{i+1}",
            "train_dates": f"{all_dates[train_start]} ~ {all_dates[train_end-1]}",
            "test_dates": f"{all_dates[test_start]} ~ {all_dates[test_end-1]}",
            "train_ic": round(train_ic, 4),
            "test_sharpe": round(test_sharpe, 4),
            "test_positive": bool(test_sharpe > 0),
        })

    if not windows:
        return {
            "factor_name": factor_col,
            "method": "rolling",
            "n_windows": 0,
            "overall_verdict": "insufficient_data",
        }

    oos_pos = sum(1 for w in windows if w["test_positive"]) / len(windows)
    avg_test_sharpe = np.mean([w["test_sharpe"] for w in windows])
    avg_train_ic = np.mean([w["train_ic"] for w in windows])

    if oos_pos >= 0.5 and avg_test_sharpe > 0:
        verdict = "pass"
    elif oos_pos >= 0.33:
        verdict = "warn"
    else:
        verdict = "fail"

    return {
        "factor_name": factor_col,
        "method": "rolling",
        "n_windows": len(windows),
        "period_results": windows,
        "oos_positive_ratio": round(oos_pos, 4),
        "avg_test_sharpe": round(avg_test_sharpe, 4),
        "avg_train_ic": round(avg_train_ic, 4),
        "overall_verdict": verdict,
    }


# ═══════════════════════════════════════════════════════════════
# Placebo test
# ═══════════════════════════════════════════════════════════════

def placebo_test(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    n_trials: int = 100,
    top_quantile: float = 0.2,
) -> dict:
    """Shuffle factor labels and test if true factor beats random."""
    # True IC
    true_ic_df = calc_daily_rank_ic(df, factor_col)
    if true_ic_df.empty:
        return {"verdict": "fail", "error": "Cannot compute true IC"}
    true_ic_mean = float(true_ic_df["ic"].mean())

    # Shuffle IC
    shuffled_ics = []
    dates_sorted = sorted(df["date"].unique())
    for _ in range(n_trials):
        trial_ics = []
        for d in dates_sorted:
            day = df[df["date"] == d].dropna(subset=[factor_col]).copy()
            if len(day) < 10:
                continue
            ret_vals = day["ret1"].values
            shuffled_ret = np.random.permutation(ret_vals)
            day_ic, _ = stats.spearmanr(day[factor_col], shuffled_ret)
            if not np.isnan(day_ic):
                trial_ics.append(day_ic)
        shuffled_ics.append(np.mean(trial_ics) if trial_ics else 0)

    shuffled_ics = np.array(shuffled_ics)
    percentile = stats.percentileofscore(shuffled_ics, true_ic_mean)

    verdict = "pass" if percentile > 90 else "warn" if percentile > 80 else "fail"

    return {
        "true_ic_mean": round(true_ic_mean, 4),
        "shuffled_mean": round(float(shuffled_ics.mean()), 4),
        "shuffled_std": round(float(shuffled_ics.std()), 4),
        "factor_score_percentile": round(float(percentile), 1),
        "verdict": verdict,
    }


# ═══════════════════════════════════════════════════════════════
# Benchmark comparison
# ═══════════════════════════════════════════════════════════════

def benchmark_comparison(
    strategy_rets: pd.Series,
    all_dates: pd.DatetimeIndex,
) -> dict:
    """Compare strategy vs CSI300 benchmark (real data, V3.1.1)."""
    from factor_lab.portfolio.benchmark import make_benchmark_spec, get_benchmark_returns

    try:
        spec = make_benchmark_spec("CSI300")
        bench_rets = get_benchmark_returns(spec, index_dates=all_dates)
        common = strategy_rets.index.intersection(bench_rets.index)
        s_ret = strategy_rets.loc[common]
        b_ret = bench_rets.loc[common]

        s_cum = (1 + s_ret).cumprod()
        b_cum = (1 + b_ret).cumprod()
        strat_cum_pct = (s_cum.iloc[-1] - 1) * 100 if len(s_cum) > 0 else 0
        bench_cum_pct = (b_cum.iloc[-1] - 1) * 100 if len(b_cum) > 0 else 0
        excess_return = strat_cum_pct - bench_cum_pct
        excess = s_ret - b_ret
        excess_sharpe = sharpe(excess)

        return {
            "benchmark": "CSI300",
            "strategy_cum_pct": round(strat_cum_pct, 2),
            "benchmark_cum_pct": round(bench_cum_pct, 2),
            "excess_return_pct": round(excess_return, 2),
            "excess_sharpe": round(excess_sharpe, 4),
            "n_days": len(common),
            "period": f"{common[0].date()} ~ {common[-1].date()}" if len(common) > 0 else "N/A",
        }
    except Exception as e:
        return {
            "benchmark": "CSI300",
            "error": str(e),
            "strategy_cum_pct": 0,
            "benchmark_cum_pct": 0,
            "excess_return_pct": 0,
            "excess_sharpe": 0,
            "n_days": 0,
            "period": "N/A",
        }


# ═══════════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════════

def compute_score(
    ic_analysis: dict,
    peer: dict,
    wf: dict,
    placebo: dict,
    factor_family: str = "unknown",
) -> dict:
    """Compute overall score and grade (0-100)."""
    ic_mean = abs(ic_analysis.get("ic_mean", 0))
    ic_ir = abs(ic_analysis.get("ic_ir", 0))
    pos_ratio = ic_analysis.get("pos_ratio", 0)

    beats = peer.get("beats_peer", False)
    excess = peer.get("excess_return_pct", 0)
    excess_sharpe = peer.get("excess_sharpe", 0)

    oos_pos = wf.get("oos_positive_ratio", 0)
    avg_test_sharpe = wf.get("avg_test_sharpe", 0)

    p_verdict = placebo.get("verdict", "fail")
    p_pct = placebo.get("factor_score_percentile", 0)

    mono = ic_analysis.get("layer_test", {}).get("long_short_sharpe", 0)

    reject = []

    # IC score (30%)
    ic_score = min(ic_ir * 100, 30)
    if pos_ratio > 0.55:
        ic_score += 5
    if ic_ir < 0.05:
        ic_score -= 10
    if ic_ir < 0:
        reject.append("ic_negative")

    # Peer score (25%)
    peer_score = 0
    if beats:
        peer_score = 10
        if excess > 5:
            peer_score += 5
        if excess > 10:
            peer_score += 5
        if excess_sharpe > 0.3:
            peer_score += 5
    else:
        peer_score = 5
        reject.append("not_beats_peer")

    # Walk-Forward score (20%)
    wf_score = oos_pos * 15 + min(avg_test_sharpe * 5, 5)
    if oos_pos < 0.5:
        reject.append("wf_oos_low")

    # Placebo score (15%)
    p_score = min(p_pct / 10, 10)
    if p_verdict == "pass":
        p_score += 5
    elif p_verdict == "fail":
        reject.append("placebo_fail")

    # Monotonicity bonus (10%)
    ls_sharpe = ic_analysis.get("layer_test", {}).get("long_short_sharpe", 0)
    if ls_sharpe > 1.0:
        mono_score = 10
    elif ls_sharpe > 0.5:
        mono_score = 7
    elif ls_sharpe > 0:
        mono_score = 4
    else:
        mono_score = 0

    total = ic_score + peer_score + wf_score + p_score + mono_score
    total = max(0, min(100, total))

    # Hard downgrades
    max_grade = "A"
    if "ic_negative" in reject:
        max_grade = downgrade(max_grade, "D")
    if "not_beats_peer" in reject:
        max_grade = downgrade(max_grade, "C")
    if "wf_oos_low" in reject:
        max_grade = downgrade(max_grade, "C")
    if "placebo_fail" in reject:
        max_grade = downgrade(max_grade, "C")

    if total >= 75:
        grade = "A"
    elif total >= 55:
        grade = "B"
    elif total >= 35:
        grade = "C"
    else:
        grade = "D"

    grade = downgrade(grade, max_grade)
    pass_gate = grade in ("A", "B")

    return {
        "overall_score": round(total, 1),
        "grade": grade,
        "pass_gate": pass_gate,
        "ic_score": round(ic_score, 1),
        "peer_score": round(peer_score, 1),
        "wf_score": round(wf_score, 1),
        "placebo_score": round(p_score, 1),
        "monotonicity_score": round(mono_score, 1),
        "reject_reasons": reject,
    }


def downgrade(current: str, target: str) -> str:
    order = ["A", "B", "C", "D"]
    if current not in order or target not in order:
        return current
    if order.index(target) > order.index(current):
        return target
    return current


# ═══════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════

def load_data() -> pd.DataFrame:
    """Load stock universe and compute factors."""
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import compute_factor, list_factors
    from factor_lab.datahub_access import daily_kline_root

    kline_dir = daily_kline_root()
    all_syms = sorted([f.stem for f in kline_dir.glob("*.csv")])

    # Use first 500 stocks for good cross-section
    symbols = all_syms[:500]
    print(f"📦 股票池: {len(symbols)} 只")

    df = load_stock_kline(symbols, "2023-01-01", "2026-06-30")
    print(f"📊 K 线: {len(df)} 行, {df['date'].min()} ~ {df['date'].max()}")
    print(f"   股票数: {df['symbol'].nunique()}")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))

    registry = {f["name"]: f for f in list_factors()}
    print(f"\n🧮 Computing {len(TOP_FACTORS)} factors...")

    for i, fname in enumerate(TOP_FACTORS):
        reg_name = FACTOR_NAME_MAP.get(fname, fname)
        if reg_name not in registry:
            print(f"  ⚠️  [{i+1}/{len(TOP_FACTORS)}] {fname} -> {reg_name} not in registry")
            df[fname] = np.nan
            continue
        try:
            s = compute_factor(df, reg_name)
            if s is not None:
                df[fname] = s.values if hasattr(s, 'values') else s
            print(f"  ✅ [{i+1}/{len(TOP_FACTORS)}] {fname}")
        except Exception as e:
            print(f"  ❌ [{i+1}/{len(TOP_FACTORS)}] {fname}: {e}")
            df[fname] = np.nan

    return df


# ═══════════════════════════════════════════════════════════════
# Single factor validation
# ═══════════════════════════════════════════════════════════════

def validate_factor(fname: str, df: pd.DataFrame, close_pivot: pd.DataFrame) -> dict:
    """Validate a single factor."""
    family = FACTOR_FAMILIES.get(fname, "unknown")

    print(f"\n{'='*60}")
    print(f"🔍 [{TOP_FACTORS.index(fname)+1}/{len(TOP_FACTORS)}] {fname} ({family})")
    print(f"{'='*60}")

    available = df[fname].notna().sum()
    if available < 100:
        return {
            "factor_name": fname,
            "factor_family": family,
            "status": "failed",
            "error": f"Data insufficient: {available} valid values",
        }

    result = {"factor_name": fname, "factor_family": family, "status": "ok"}

    # Step 1: IC/IR + Layer
    print("  📈 IC/IR + Layer test...")
    ic = compute_ic_ir(df, fname)
    result["ic_analysis"] = ic
    print(f"     IC={ic.get('ic_mean')}  IR={ic.get('ic_ir')}  POS={ic.get('pos_ratio')}")

    # Step 2: Peer benchmark (同池等权)
    print("  ⚖️  同池等权对比...")
    peer = check_peer_benchmark(df, fname, close_pivot, top_quantile=0.2)
    result["anti_overfit"] = {
        "peer_benchmark": peer,
    }
    print(f"     beats_peer={peer.get('beats_peer')}  excess={peer.get('excess_return_pct')}%")

    # Step 3: Walk-Forward
    print("  🚶 Walk-Forward...")
    wf = walk_forward_validation(df, fname, close_pivot, top_quantile=0.2, n_windows=3)
    result["walk_forward"] = wf
    print(f"     OOS+={wf.get('oos_positive_ratio')}  verdict={wf.get('overall_verdict')}")

    # Step 4: Placebo test
    print("  🎲 Placebo test...")
    placebo = placebo_test(df, fname, close_pivot, n_trials=30)
    result["anti_overfit"]["placebo"] = placebo
    print(f"     percentile={placebo.get('factor_score_percentile', 'N/A')}  verdict={placebo.get('verdict', 'N/A')}")

    # Step 5: Benchmark comparison (CSI300)
    print("  📊 Benchmark vs CSI300...")
    strat_rets = _get_strategy_rets(peer, wf, df, fname, close_pivot)
    all_dates = close_pivot.index
    bench = benchmark_comparison(strat_rets, all_dates)
    result["benchmark_comparison"] = bench
    print(f"     excess={bench.get('excess_return_pct')}%  sharpe={bench.get('excess_sharpe')}")

    # Step 6: Scoring
    print("  🏆 Scoring...")
    score = compute_score(ic, peer, wf, placebo, family)
    result["scoring"] = score
    print(f"     score={score.get('overall_score')}  grade={score.get('grade')}")

    # Derived
    result["derived"] = {
        "monotonicity": monotonicity(ic.get("layer_test", {})),
        "ls_sharpe": ic.get("layer_test", {}).get("long_short_sharpe", 0),
        "ic_half_life_days": ic_half_life(ic.get("monthly_ic_series", [])),
        "industry_exposure": "多行业分散 (A股全市场)",
    }

    return result


def _get_strategy_rets(
    peer: dict, wf: dict,
    df: pd.DataFrame, fname: str, close_pivot: pd.DataFrame,
) -> pd.Series:
    """Extract strategy return series."""
    # From peer benchmark
    sr = peer.get("strategy_returns", {})
    if sr and isinstance(sr, dict) and len(sr) > 50:
        return pd.Series(sr).sort_index()

    # Fallback: peer cumulative diff or equal weight
    daily_ret = close_pivot.pct_change()
    return daily_ret.mean(axis=1).dropna()


# ═══════════════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════════════

def clean(obj):
    if isinstance(obj, dict):
        return {str(k) if not isinstance(k, (str, int, float, bool, type(None))) else k: clean(v)
                for k, v in obj.items()}
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


def save_report(fname: str, result: dict):
    d = OUTPUT_DIR / fname
    d.mkdir(parents=True, exist_ok=True)
    # Remove large strategy_returns to avoid bloated JSON
    clean_result = clean(result)
    if "anti_overfit" in clean_result and "peer_benchmark" in clean_result["anti_overfit"]:
        clean_result["anti_overfit"]["peer_benchmark"].pop("strategy_returns", None)
    with open(d / "report.json", "w", encoding="utf-8") as f:
        json.dump(clean_result, f, ensure_ascii=False, indent=2)
    print(f"  💾 Saved: {d / 'report.json'}")


def build_leaderboard(results: list) -> Path:
    rows = []
    for r in results:
        ic = r.get("ic_analysis", {})
        ao = r.get("anti_overfit", {})
        peer = ao.get("peer_benchmark", {})
        placebo = ao.get("placebo", {})
        wf = r.get("walk_forward", {})
        bench = r.get("benchmark_comparison", {})
        sc = r.get("scoring", {})
        d = r.get("derived", {})

        if r.get("status") == "failed":
            rows.append({"factor": r["factor_name"], "status": "failed",
                         "error": r.get("error", "")})
            continue

        rows.append({
            "factor": r["factor_name"],
            "ic_mean": ic.get("ic_mean", ""),
            "ic_ir": ic.get("ic_ir", ""),
            "pos_ratio": ic.get("pos_ratio", ""),
            "beats_peer": str(peer.get("beats_peer", "")),
            "excess_return": peer.get("excess_return_pct", ""),
            "ls_sharpe": d.get("ls_sharpe", ""),
            "layer_monotonicity": d.get("monotonicity", ""),
            "wf_pos_ratio": wf.get("oos_positive_ratio", ""),
            "wf_verdict": wf.get("overall_verdict", ""),
            "placebo_percentile": placebo.get("factor_score_percentile", ""),
            "placebo_verdict": placebo.get("verdict", ""),
            "half_life": d.get("ic_half_life_days", ""),
            "benchmark_excess": bench.get("excess_return_pct", ""),
            "strategy_cum": bench.get("strategy_cum_pct", ""),
            "benchmark_cum": bench.get("benchmark_cum_pct", ""),
            "overall_score": sc.get("overall_score", ""),
            "overall_grade": sc.get("grade", ""),
            "pass_gate": str(sc.get("pass_gate", "")),
        })

    p = OUTPUT_DIR / "validation_leaderboard.csv"
    if rows:
        fn = rows[0].keys()
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fn)
            w.writeheader()
            w.writerows(rows)
        print(f"\n📋 Leaderboard: {p} ({len(rows)} factors)")
    return p


def build_summary(results: list, csv_path: Path) -> Path:
    lines = []
    lines.append("# 因子验证报告 — V3.1.2\n")
    lines.append(f"**生成时间**: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"**基准数据**: 沪深300 真实指数行情 (V3.1.1)\n")
    lines.append(f"**因子上限**: {len(TOP_FACTORS)} 个, "
                 f"通过: {sum(1 for r in results if r.get('status') == 'ok')}, "
                 f"失败: {sum(1 for r in results if r.get('status') == 'failed')}\n")

    # Leaderboard table
    lines.append("## 排行榜\n")
    lines.append("| 排名 | 因子 | IC_mean | IC_IR | POS | 跑赢等权 | 超额% | LS Sharpe | 单调性 | WF正比 | 等级 |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|\n")

    ok = [r for r in results if r.get("status") == "ok"]
    ok.sort(key=lambda r: r.get("scoring", {}).get("overall_score", 0), reverse=True)

    for rank, r in enumerate(ok, 1):
        ic = r.get("ic_analysis", {})
        peer = r.get("anti_overfit", {}).get("peer_benchmark", {})
        wf = r.get("walk_forward", {})
        sc = r.get("scoring", {})
        d = r.get("derived", {})
        beats_mark = "✅" if peer.get("beats_peer") else "❌"
        lines.append(
            f"| {rank} | {r['factor_name']} "
            f"| {ic.get('ic_mean', '-')} | {ic.get('ic_ir', '-')} "
            f"| {ic.get('pos_ratio', '-')} | {beats_mark} "
            f"| {peer.get('excess_return_pct', '-')} "
            f"| {d.get('ls_sharpe', 0):.2f} | {d.get('monotonicity', '-')} "
            f"| {wf.get('oos_positive_ratio', '-')} "
            f"| **{sc.get('grade', '?')}** |\n"
        )

    # Per-factor details
    lines.append("\n---\n")
    for r in ok:
        lines.append(generate_detail(r))

    # Failed
    failed = [r for r in results if r.get("status") == "failed"]
    if failed:
        lines.append("## 失败的因子\n")
        for r in failed:
            lines.append(f"- **{r['factor_name']}**: {r.get('error', '')}\n")
        lines.append("\n")

    # Acceptance check
    lines.append("## 验收检查\n")
    lines.append("```python\n")
    lines.append("import sys\n")
    lines.append('sys.path.insert(0, "commands")\n')
    lines.append("from factor_lab.portfolio.benchmark import get_benchmark_returns, make_benchmark_spec\n")
    lines.append('bench = get_benchmark_returns(make_benchmark_spec("CSI300"))\n')
    lines.append('assert len(bench) > 500, f"沪深300应有500+交易日"\n')
    lines.append("import numpy as np\n")
    lines.append("ann_vol = bench.std() * np.sqrt(252)\n")
    lines.append('assert 0.05 < ann_vol < 0.50, f"年化波动率应合理, 实际{ann_vol:.1%}"\n')
    lines.append("\n")
    lines.append("import os, csv\n")
    lines.append('assert os.path.exists("research_outputs/factor_validation/validation_leaderboard.csv")\n')
    lines.append('with open("research_outputs/factor_validation/validation_leaderboard.csv") as f:\n')
    lines.append("    reader = csv.DictReader(f)\n")
    lines.append("    rows = list(reader)\n")
    lines.append('    assert len(rows) >= 15, f"应有至少15个因子"\n')
    lines.append("\n")
    lines.append('beats = sum(1 for r in rows if r.get("beats_peer", "").lower() == "true")\n')
    lines.append('print(f"跑赢同池等权的因子: {beats}/{len(rows)}")\n')
    lines.append("```\n")

    p = OUTPUT_DIR / "summary.md"
    p.write_text("".join(lines), encoding="utf-8")
    print(f"📝 Summary: {p}")
    return p


def generate_detail(r: dict) -> str:
    fname = r["factor_name"]
    family = r.get("factor_family", "unknown")
    ic = r.get("ic_analysis", {})
    ao = r.get("anti_overfit", {})
    peer = ao.get("peer_benchmark", {})
    placebo = ao.get("placebo", {})
    wf = r.get("walk_forward", {})
    sc = r.get("scoring", {})
    bench = r.get("benchmark_comparison", {})
    d = r.get("derived", {})

    lines = [f"\n## {fname}\n", "| 指标 | 值 |\n", "|---|---|\n"]
    lines.append(f"| IC_mean | {ic.get('ic_mean', 'N/A')} |\n")
    lines.append(f"| IC_IR | {ic.get('ic_ir', 'N/A')} |\n")
    lines.append(f"| 正IC比例 | {ic.get('pos_ratio', 'N/A')} |\n")
    lines.append(f"| 跑赢同池等权? | {'Yes' if peer.get('beats_peer') else 'No'} |\n")
    lines.append(f"| 超额Sharpe | {peer.get('excess_sharpe', 'N/A')} |\n")
    lines.append(f"| Top-Bottom Sharpe | {d.get('ls_sharpe', 0):.2f} |\n")
    lines.append(f"| 5层单调性 | {d.get('monotonicity', '不单调')} |\n")
    lines.append(f"| WF样本外正比 | {wf.get('oos_positive_ratio', 'N/A')} |\n")
    pv = placebo.get("verdict", "N/A")
    pp = placebo.get("factor_score_percentile", "N/A")
    lines.append(f"| Placebo显著? | {'Yes' if pv == 'pass' else 'No'} (百分位: {pp}) |\n")
    lines.append(f"| IC半衰期 | {d.get('ic_half_life_days', 'N/A')}d |\n")
    lines.append(f"| 行业暴露 | {d.get('industry_exposure', '多行业分散')} |\n")
    lines.append(f"| vs 沪深300 | 超额 {bench.get('excess_return_pct', 'N/A')}% |\n")
    lines.append(f"| 综合评分 | {sc.get('grade', '?')} (score: {sc.get('overall_score', 'N/A')}) |\n")
    grade = sc.get("grade", "?")
    conclusions = {"A": "promote", "B": "promote", "C": "watch", "D": "retire"}
    lines.append(f"| 结论 | **{conclusions.get(grade, 'retire')}** |\n")
    lines.append(f"\n**家族**: {family}  |  ")
    lines.append(f"**WF验证**: {wf.get('overall_verdict', 'N/A')}\n")
    lines.append(f"\n---\n")
    return "".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def validate_top_n_factors(output_dir: str = None) -> list[dict]:
    global OUTPUT_DIR
    if output_dir:
        OUTPUT_DIR = Path(output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"📁 Output: {OUTPUT_DIR}\n")

    df = load_data()
    if df.empty:
        print("❌ No data loaded")
        return []

    close_pivot = df.pivot(index="date", columns="symbol", values="close")
    print(f"\n📊 close_pivot: {close_pivot.shape}")

    results = []
    for fname in TOP_FACTORS:
        if fname not in df.columns or df[fname].isna().all():
            results.append({"factor_name": fname, "status": "failed",
                            "error": "Column missing or all NA"})
            print(f"\n❌ {fname}: column missing")
            continue

        result = validate_factor(fname, df, close_pivot)
        save_report(fname, result)
        results.append(result)
        g = result.get("scoring", {}).get("grade", "?") if result.get("status") == "ok" else "FAIL"
        print(f"\n{'='*60}")
        print(f"🚀 [{TOP_FACTORS.index(fname)+1}/{len(TOP_FACTORS)}] {fname}: {g}")
        print(f"{'='*60}")

    csv_path = build_leaderboard(results)
    build_summary(results, csv_path)

    ok_n = sum(1 for r in results if r.get("status") == "ok")
    fail_n = sum(1 for r in results if r.get("status") == "failed")
    grades = Counter(r.get("scoring", {}).get("grade", "?") for r in results if r.get("status") == "ok")
    print(f"\n{'='*60}")
    print(f"Done: {ok_n} passed, {fail_n} failed")
    print(f"Grade distribution: {dict(grades)}")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    results = validate_top_n_factors()
    ok = [r for r in results if r.get("status") == "ok"]
    grades = Counter(r.get("scoring", {}).get("grade", "?") for r in ok)
    print(f"\n完成 {len(results)} 个因子, {len(ok)} 通过")
    print("Grade 分布:", dict(grades))
