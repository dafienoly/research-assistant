"""ret5 过滤策略验证引擎 — 6 种过滤类型 vs ret5 基线

支持过滤类型:
  - gate:          只有当 secondary 因子 > 阈值时, primary 才有效
  - vol_filter:    排除 volatility20 最高的 20%
  - turn_filter:   排除 turnover 最高 20% 和 amount 最低 20%
  - crowding_filter: 排除 vol_ratio 最高的 20%
  - pullback_filter: MA20>MA60 时偏好 pullback 信号
  - regime_filter:  市场趋势为负时降低仓位

用法:
    from factor_lab.orthogonality.ret5_filter_validator import (
        validate_filter_strategies,
        run_full_orthogonality_pipeline,
        mark_unavailable_missing_factors,
    )

    result = validate_filter_strategies(
        factor_df, close_pivot, ret5_name='ret5',
        filters=[
            {'name': 'ret5_close_gt_ma20_gate', 'desc': 'ret5 + close_gt_ma20 门控',
             'type': 'gate',
             'params': {'primary': 'ret5', 'secondary': 'close_gt_ma20', 'threshold': 0.0}},
        ],
    )
"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

CST = timezone(timedelta(hours=8))
BASE = Path("/home/ly/.hermes/research-assistant")
OUTPUT = Path("/mnt/d/HermesReports/factor_lab")

# ─── 共享工具 ─────────────────────────────────────────────────────────


def _quick_backtest(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    factor_col: str,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> dict:
    """Top-组等权收益快速回测 (与 orthogonality_analyzer 一致)"""
    from factor_lab.orthogonality.orthogonality_analyzer import _quick_backtest as _qbt

    return _qbt(factor_df, close_pivot, factor_col, top_quantile, rebalance)


def _delta_vs_base(base: dict, metrics: dict) -> dict:
    """计算 metrics 相对 base 的差值"""
    return {
        "return_delta": round(
            metrics.get("cumulative_return_pct", 0)
            - base.get("cumulative_return_pct", 0),
            2,
        ),
        "max_drawdown_delta": round(
            metrics.get("max_drawdown_pct", 0)
            - base.get("max_drawdown_pct", 0),
            2,
        ),
        "sharpe_delta": round(
            metrics.get("sharpe", 0) - base.get("sharpe", 0), 4
        ),
        "calmar_delta": round(
            metrics.get("calmar", 0) - base.get("calmar", 0), 4
        ),
    }


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日"""
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    first_per_month = s.groupby(dates.month).apply(lambda x: x.index[0])
    return pd.DatetimeIndex(first_per_month.values)


# ─── 1. mark_unavailable_missing_factors ─────────────────────────────


def mark_unavailable_missing_factors(
    factor_df: pd.DataFrame,
    requested_factors: list,
) -> list:
    """检查哪些因子不在 factor_df.columns 中, 返回 unavailable 列表

    参数:
        factor_df: 因子 DataFrame (含 date, symbol, 各因子列)
        requested_factors: 请求的因子名列表

    返回:
        [{"name": "close_gt_ma20", "available": False}, ...]
    """
    available_cols = set(factor_df.columns)
    results = []
    for fname in requested_factors:
        results.append({
            "name": fname,
            "available": fname in available_cols,
        })
    return results


# ─── 2. 各过滤策略的合成因子构造 ────────────────────────────────────


def _build_gate_factor(
    factor_df: pd.DataFrame,
    primary: str,
    secondary: str,
    threshold: float,
) -> pd.Series:
    """gate: 只有 secondary 因子 > 阈值时, primary 才有效"""
    if primary not in factor_df.columns or secondary not in factor_df.columns:
        raise ValueError(
            f"gate 过滤需要因子 '{primary}' 和 '{secondary}' 在 factor_df 中"
        )
    gate = factor_df[secondary] > threshold
    return factor_df[primary].where(gate, -999.0)


def _build_vol_filter_factor(
    factor_df: pd.DataFrame,
    ret5_col: str,
    vol_col: str = "volatility20",
    exclude_top: float = 0.2,
) -> pd.Series:
    """vol_filter: 排除 volatility20 最高的 20%"""
    if ret5_col not in factor_df.columns:
        raise ValueError(f"ret5 列 '{ret5_col}' 不在 factor_df 中")
    result = factor_df[ret5_col].copy()
    if vol_col in factor_df.columns:
        vol_rank = factor_df.groupby("date")[vol_col].rank(pct=True)
        bad = vol_rank >= (1 - exclude_top)
        result = result.where(~bad, -999.0)
    return result


def _build_turn_filter_factor(
    factor_df: pd.DataFrame,
    ret5_col: str,
    turn_col: str = "turnover20",
    amount_col: str = "amount",
    exclude_top_turn: float = 0.2,
    exclude_bottom_amount: float = 0.2,
) -> pd.Series:
    """turn_filter: 排除 turnover 最高 20% 和 amount 最低 20%"""
    if ret5_col not in factor_df.columns:
        raise ValueError(f"ret5 列 '{ret5_col}' 不在 factor_df 中")
    result = factor_df[ret5_col].copy()
    # High turnover penalty
    if turn_col in factor_df.columns:
        turn_rank = factor_df.groupby("date")[turn_col].rank(pct=True)
        high_turn = turn_rank >= (1 - exclude_top_turn)
        result = result.where(~high_turn, -999.0)
    # Low amount penalty
    if amount_col in factor_df.columns:
        temp = factor_df.copy()
        temp["amt_ma"] = temp.groupby("symbol")[amount_col].transform(
            lambda x: x.rolling(20).mean()
        )
        amt_rank = temp.groupby("date")["amt_ma"].rank(pct=True)
        low_amt = amt_rank <= exclude_bottom_amount
        result = result.where(~low_amt, -999.0)
    return result


def _build_crowding_filter_factor(
    factor_df: pd.DataFrame,
    ret5_col: str,
    vr_col: str = "vol_ratio20",
    exclude_top: float = 0.2,
) -> pd.Series:
    """crowding_filter: 排除 vol_ratio 最高的 20%"""
    if ret5_col not in factor_df.columns:
        raise ValueError(f"ret5 列 '{ret5_col}' 不在 factor_df 中")
    result = factor_df[ret5_col].copy()
    if vr_col in factor_df.columns:
        vr_rank = factor_df.groupby("date")[vr_col].rank(pct=True)
        crowded = vr_rank >= (1 - exclude_top)
        result = result.where(~crowded, -999.0)
    return result


def _build_pullback_filter_factor(
    factor_df: pd.DataFrame,
    ret5_col: str,
    uptrend_col: str = "ma20_gt_ma60",
    pullback_cols: Optional[list] = None,
    boost_factor: float = 0.5,
) -> pd.Series:
    """pullback_filter: 在 MA20 > MA60 时, 偏好 pullback 信号

    构造: ret5 * (1 + boost * pullback_score) 当 uptrend,
          否则 ret5 * (1 - boost * 0.5)
    """
    if ret5_col not in factor_df.columns:
        raise ValueError(f"ret5 列 '{ret5_col}' 不在 factor_df 中")
    if pullback_cols is None:
        pullback_cols = [
            "pullback_5_in_ma20_uptrend",
            "low_volume_pullback",
            "ma20_uptrend_pullback",
        ]

    result = factor_df[ret5_col].copy()

    # 判断上升趋势
    if uptrend_col in factor_df.columns:
        uptrend = factor_df[uptrend_col] > 0
    else:
        # fallback: 用 close_gt_ma20 近似
        uptrend = pd.Series(True, index=factor_df.index)

    # 计算 pullback score (截面 rank 后平均)
    pb_scores = []
    for pb in pullback_cols:
        if pb in factor_df.columns:
            pb_rank = factor_df.groupby("date")[pb].rank(pct=True)
            pb_scores.append(pb_rank)
    if pb_scores:
        pb_combined = sum(pb_scores) / len(pb_scores)
    else:
        pb_combined = pd.Series(0.0, index=factor_df.index)

    # 趋势中偏好 pullback, 否则略降
    modifier = np.where(uptrend, 1 + boost_factor * pb_combined, 1 - boost_factor * 0.5)
    result = result * modifier
    return result


def _build_regime_filter_factor(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    ret5_col: str,
    lookback: int = 20,
    reduction_factor: float = 0.5,
) -> pd.Series:
    """regime_filter: 市场趋势为负时降低仓位

    用全市场等权收益的 lookback 日移动均值判断趋势方向。
    趋势为负时, ret5 乘以 reduction_factor。
    """
    if ret5_col not in factor_df.columns:
        raise ValueError(f"ret5 列 '{ret5_col}' 不在 factor_df 中")

    # 计算全市场等权日收益
    daily_ret = close_pivot.pct_change().mean(axis=1)
    market_trend = daily_ret.rolling(lookback, min_periods=5).mean()

    result = factor_df[ret5_col].copy()

    # 为每个日期分配市场状态调节因子
    dates_in_df = sorted(factor_df["date"].unique())
    date_regime = {}
    for d in dates_in_df:
        if d in market_trend.index:
            trend_val = market_trend.loc[d]
            if isinstance(trend_val, pd.Series):
                trend_val = trend_val.iloc[-1]
            if pd.notna(trend_val) and trend_val < 0:
                date_regime[d] = reduction_factor
            else:
                date_regime[d] = 1.0
        else:
            date_regime[d] = 1.0

    # 应用市场状态调节
    regime_map = factor_df["date"].map(date_regime)
    result = result * regime_map.fillna(1.0)
    return result


# ─── 过滤类型 → 构造函数的映射 ──────────────────────────────────────

_FILTER_BUILDERS = {
    "gate": _build_gate_factor,
    "vol_filter": _build_vol_filter_factor,
    "turn_filter": _build_turn_filter_factor,
    "crowding_filter": _build_crowding_filter_factor,
    "pullback_filter": _build_pullback_filter_factor,
    "regime_filter": _build_regime_filter_factor,
}


# ─── 3. validate_filter_strategies ───────────────────────────────────


def validate_filter_strategies(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    ret5_name: str = "ret5",
    filters: Optional[list] = None,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    start_date: str = "2025-01-02",
    end_date: str = "2026-06-30",
) -> dict:
    """过滤策略验证主入口

    参数:
        factor_df: 因子 DataFrame (含 date, symbol, 各因子列)
        close_pivot: 收盘价 pivot (date × symbol)
        ret5_name: 基准因子名 (默认 ret5)
        filters: list[dict], 每个 dict 格式:
            {
                'name': 'ret5_close_gt_ma20_gate',
                'desc': 'ret5 + close_gt_ma20 门控',
                'type': 'gate',          # 见 _FILTER_BUILDERS
                'params': {'primary': 'ret5', 'secondary': 'close_gt_ma20', 'threshold': 0.0},
            }
        top_quantile: 选股分位数
        rebalance: 调仓频率 ('monthly'/'weekly')
        start_date: 开始日期
        end_date: 结束日期

    返回:
        {
            'baseline': {ret5 回测指标},
            'filters': [{name, desc, type, metrics, vs_baseline, verdict}, ...],
            'best_filter': str or None,
            'beats_baseline': bool,
        }
    """
    if filters is None:
        filters = _default_filters()

    # 切片数据
    mask = (factor_df["date"] >= start_date) & (factor_df["date"] <= end_date)
    df_slice = factor_df[mask].copy()
    cp_slice = close_pivot.loc[start_date:end_date].copy()

    # 基线: ret5 单因子回测
    base_metrics = _quick_backtest(
        df_slice, cp_slice, ret5_name, top_quantile, rebalance
    )

    filter_results = []
    for cfg in filters:
        fname = cfg.get("name", "unnamed_filter")
        fdesc = cfg.get("desc", "")
        ftype = cfg.get("type", "gate")
        fparams = cfg.get("params", {})

        # 构造临时列名
        temp_col = f"_filter_{fname}"

        try:
            builder = _FILTER_BUILDERS.get(ftype)
            if builder is None:
                # 未知过滤类型, 跳过
                filter_results.append({
                    "name": fname,
                    "desc": fdesc,
                    "type": ftype,
                    "error": f"未知过滤类型: {ftype}",
                })
                continue

            # 构建合成因子
            if ftype == "gate":
                df_slice[temp_col] = _build_gate_factor(
                    df_slice,
                    fparams.get("primary", ret5_name),
                    fparams.get("secondary", "close_gt_ma20"),
                    fparams.get("threshold", 0.0),
                )
            elif ftype == "vol_filter":
                df_slice[temp_col] = _build_vol_filter_factor(
                    df_slice,
                    ret5_name,
                    fparams.get("vol_col", "volatility20"),
                    fparams.get("exclude_top", 0.2),
                )
            elif ftype == "turn_filter":
                df_slice[temp_col] = _build_turn_filter_factor(
                    df_slice,
                    ret5_name,
                    fparams.get("turn_col", "turnover20"),
                    fparams.get("amount_col", "amount"),
                    fparams.get("exclude_top_turn", 0.2),
                    fparams.get("exclude_bottom_amount", 0.2),
                )
            elif ftype == "crowding_filter":
                df_slice[temp_col] = _build_crowding_filter_factor(
                    df_slice,
                    ret5_name,
                    fparams.get("vr_col", "vol_ratio20"),
                    fparams.get("exclude_top", 0.2),
                )
            elif ftype == "pullback_filter":
                df_slice[temp_col] = _build_pullback_filter_factor(
                    df_slice,
                    ret5_name,
                    fparams.get("uptrend_col", "ma20_gt_ma60"),
                    fparams.get("pullback_cols", None),
                    fparams.get("boost_factor", 0.5),
                )
            elif ftype == "regime_filter":
                df_slice[temp_col] = _build_regime_filter_factor(
                    df_slice,
                    cp_slice,
                    ret5_name,
                    fparams.get("lookback", 20),
                    fparams.get("reduction_factor", 0.5),
                )

            # 回测合成因子
            metrics = _quick_backtest(
                df_slice, cp_slice, temp_col, top_quantile, rebalance
            )
            delta = _delta_vs_base(base_metrics, metrics)

            # 判定: Sharpe 提升 > 0.05 或 回撤下降 > 0.5%
            #   max_drawdown_delta = new - base, 正数表示回撤改善 (变小)
            sharpe_improved = delta.get("sharpe_delta", 0) > 0.05
            dd_improved = delta.get("max_drawdown_delta", 0) > 0.5
            if sharpe_improved or dd_improved:
                verdict = "improvement"
            elif (delta.get("sharpe_delta", 0) > -0.02
                  and delta.get("max_drawdown_delta", 0) > -0.5):
                verdict = "neutral"
            else:
                verdict = "degradation"

            filter_results.append({
                "name": fname,
                "desc": fdesc,
                "type": ftype,
                "params": fparams,
                "metrics": metrics,
                "vs_baseline": delta,
                "verdict": verdict,
            })

        except (ValueError, KeyError) as e:
            filter_results.append({
                "name": fname,
                "desc": fdesc,
                "type": ftype,
                "error": str(e),
            })
        finally:
            if temp_col in df_slice.columns:
                del df_slice[temp_col]

    # 寻找最佳过滤
    valid_results = [r for r in filter_results if "metrics" in r]
    if valid_results:
        best = max(
            valid_results,
            key=lambda r: r.get("vs_baseline", {}).get("sharpe_delta", -999),
        )
        best_filter = best["name"]
        beats_baseline = best.get("vs_baseline", {}).get("sharpe_delta", 0) > 0
    else:
        best_filter = None
        beats_baseline = False

    return {
        "baseline": {
            "ret5_name": ret5_name,
            **base_metrics,
        },
        "filters": filter_results,
        "best_filter": best_filter,
        "beats_baseline": beats_baseline,
    }


# ─── 4. run_full_orthogonality_pipeline ──────────────────────────────


def load_universe() -> list:
    """从 universe 加载股票池 (与 pipeline.py 一致)"""
    from strategy_lab.universe import build

    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    return sorted(pool)


def run_full_orthogonality_pipeline(
    factor_names: Optional[list] = None,
    start_date: str = "2025-01-02",
    end_date: str = "2026-06-30",
    rebalance: str = "monthly",
    top_quantile: float = 0.2,
    output_dir: Optional[str] = None,
    filters: Optional[list] = None,
) -> dict:
    """全流程: 加载数据 → 算因子 → 正交性 → 增量价值 → 过滤策略 → 报告

    参数:
        factor_names: 候选因子名列表, 默认用 factor_base 中除 ret5 外的所有因子
        start_date: 回测开始日期
        end_date: 回测结束日期
        rebalance: 调仓频率
        top_quantile: 选股分位数
        output_dir: 保存目录 (默认 OUTPUT / timestamp)
        filters: 过滤策略配置列表 (传给 validate_filter_strategies)

    返回:
        完整结果 dict (含 data_summary, orthogonality, incremental_value,
                      filter_validation, leaderboard, output_dir)
    """
    from factor_lab.orthogonality.orthogonality_analyzer import (
        compute_orthogonality,
        compute_incremental_value,
    )
    from factor_lab.factor_base import compute_all_factors, list_factors
    from factor_lab.factor_engine import load_stock_kline

    out_dir = Path(output_dir) if output_dir else (
        OUTPUT / datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  全流程正交性分析 & 过滤策略验证")
    print(f"  输出目录: {out_dir}")
    print(f"{'=' * 60}\n")

    # ── a. 加载数据 (共享 K 线) ──
    print("[1/7] 加载数据...")
    symbols = load_universe()
    print(f"  股票池: {len(symbols)} 只")

    df = load_stock_kline(symbols, start_date="2024-10-01", end_date="2026-06-30")
    print(f"  K 线: {len(df)} 行, {df['date'].min()} ~ {df['date'].max()}")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # 下期收益 (用于 IC)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))

    # ── b. 计算所有因子 ──
    print("[2/7] 计算所有因子...")
    factor_df = compute_all_factors(df)
    # 合并回原始数据
    factor_df["date"] = df["date"]
    factor_df["symbol"] = df["symbol"]
    factor_df["close"] = df["close"]
    factor_df["ret1"] = df["ret1"]
    factor_df["volume"] = df["volume"]
    factor_df["amount"] = df["amount"]
    factor_df["open"] = df["open"]
    factor_df["high"] = df["high"]
    factor_df["low"] = df["low"]

    print(f"  因子数: {len([c for c in factor_df.columns if c not in ('date','symbol','close','ret1','volume','amount','open','high','low')])}")

    # 切片到回测区间
    mask = (factor_df["date"] >= start_date) & (factor_df["date"] <= end_date)
    factor_df = factor_df[mask].reset_index(drop=True)

    # close_pivot
    close_pivot = df.pivot_table(
        index="date", columns="symbol", values="close"
    ).sort_index()
    close_pivot = close_pivot.loc[start_date:end_date]

    print(f"  回测区间: {factor_df['date'].min()} ~ {factor_df['date'].max()}")
    print(f"  交易日数: {len(close_pivot)}")

    # ── c. 计算正交性 ──
    print("[3/7] 计算正交性 (vs ret5)...")
    if factor_names is None:
        all_factors = list_factors()
        factor_names = [
            f["name"] for f in all_factors
            if f["name"] != "ret5" and f["name"] not in (
                "ret1", "ret10", "ret20", "ret60"
            )
        ]
        # 排除系统列
        system_cols = {"date", "symbol", "close", "ret1", "volume", "amount",
                       "open", "high", "low"}
        factor_names = [f for f in factor_names if f not in system_cols]

    # 检查可用因子
    avail_check = mark_unavailable_missing_factors(factor_df, factor_names)
    available_names = [a["name"] for a in avail_check if a["available"]]

    ortho_result = compute_orthogonality(
        factor_df, available_names, reference_factor="ret5"
    )
    print(f"  候选因子: {len(available_names)}, 正交性计算完成")

    # ── d. Top10 最正交因子增量价值 ──
    print("[4/7] 计算 Top10 最正交因子的增量价值...")
    candidates = ortho_result.get("candidates", [])
    # 排除有错误的结果
    valid_candidates = [c for c in candidates if "error" not in c]
    # 按正交性评分降序 (越高越正交)
    sorted_candidates = sorted(
        valid_candidates,
        key=lambda c: c.get("orthogonality_score", 0),
        reverse=True,
    )
    top10 = sorted_candidates[:10]

    iv_results = []
    for cand in top10:
        iv = compute_incremental_value(
            factor_df, close_pivot, cand["name"],
            reference="ret5",
            top_quantile=top_quantile,
            rebalance=rebalance,
        )
        iv_results.append(iv)
        print(f"    {cand['name']:30s} → IVS={iv.get('incremental_value_score', 0):.1f}, "
              f"best={iv.get('best_strategy', 'none')}")

    # ── e. 过滤策略验证 ──
    print("[5/7] 运行过滤策略验证...")
    if filters is None:
        filters = _default_filters()

    filter_result = validate_filter_strategies(
        factor_df, close_pivot,
        ret5_name="ret5",
        filters=filters,
        top_quantile=top_quantile,
        rebalance=rebalance,
        start_date=start_date,
        end_date=end_date,
    )
    n_valid = sum(1 for f in filter_result.get("filters", []) if "error" not in f)
    print(f"  过滤策略: {n_valid}/{len(filter_result.get('filters', []))} 有效, "
          f"best={filter_result.get('best_filter', 'N/A')}, "
          f"beats_baseline={filter_result.get('beats_baseline', False)}")

    # ── f. 生成排行榜 ──
    print("[6/7] 生成排行榜...")
    leaderboard = _build_leaderboard(
        ortho_result, iv_results, filter_result, sorted_candidates
    )

    # ── g. 保存报告 ──
    print("[7/7] 保存报告...")
    report = {
        "generated_at": datetime.now(CST).isoformat(),
        "config": {
            "start_date": start_date,
            "end_date": end_date,
            "rebalance": rebalance,
            "top_quantile": top_quantile,
            "n_candidates": len(available_names),
        },
        "data_summary": {
            "n_symbols": len(symbols),
            "n_kline_rows": len(df),
            "n_trading_days": len(close_pivot),
            "n_factors": len(available_names),
        },
        "orthogonality": ortho_result,
        "incremental_value": iv_results,
        "filter_validation": filter_result,
        "leaderboard": leaderboard,
    }

    report_path = out_dir / "orthogonality_pipeline_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(_make_serializable(report), f, ensure_ascii=False, indent=2)
    print(f"  报告已保存: {report_path}")

    # CSV 排行榜
    csv_path = out_dir / "factor_leaderboard.csv"
    if leaderboard:
        import csv as csv_mod
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv_mod.DictWriter(f, fieldnames=leaderboard[0].keys())
            writer.writeheader()
            writer.writerows(leaderboard)
        print(f"  排行榜 CSV: {csv_path}")

    print(f"\n{'=' * 60}")
    print(f"  全流程完成!")
    print(f"{'=' * 60}\n")

    return report


# ─── 5. 辅助功能 ─────────────────────────────────────────────────────


def _default_filters() -> list:
    """默认过滤策略集"""
    return [
        {
            "name": "ret5_close_gt_ma20_gate",
            "desc": "ret5 + close_gt_ma20 门控 (close_gt_ma20 > 0 时启用)",
            "type": "gate",
            "params": {
                "primary": "ret5",
                "secondary": "close_gt_ma20",
                "threshold": 0.0,
            },
        },
        {
            "name": "ret5_vol_filter",
            "desc": "排除 volatility20 最高的 20%",
            "type": "vol_filter",
            "params": {
                "vol_col": "volatility20",
                "exclude_top": 0.2,
            },
        },
        {
            "name": "ret5_turn_filter",
            "desc": "排除 turnover 最高 20% + amount 最低 20%",
            "type": "turn_filter",
            "params": {
                "turn_col": "turnover20",
                "amount_col": "amount",
                "exclude_top_turn": 0.2,
                "exclude_bottom_amount": 0.2,
            },
        },
        {
            "name": "ret5_crowding_filter",
            "desc": "排除 vol_ratio (量比) 最高的 20%",
            "type": "crowding_filter",
            "params": {
                "vr_col": "vol_ratio20",
                "exclude_top": 0.2,
            },
        },
        {
            "name": "ret5_pullback_filter",
            "desc": "MA20>MA60 趋势中偏好 pullback 信号",
            "type": "pullback_filter",
            "params": {
                "uptrend_col": "ma20_gt_ma60",
                "boost_factor": 0.5,
            },
        },
        {
            "name": "ret5_regime_filter",
            "desc": "市场趋势为负时 ret5 仓位减半",
            "type": "regime_filter",
            "params": {
                "lookback": 20,
                "reduction_factor": 0.5,
            },
        },
    ]


def _build_leaderboard(
    ortho_result: dict,
    iv_results: list,
    filter_result: dict,
    sorted_candidates: list,
) -> list:
    """生成综合排行榜

    合并正交性、增量价值、过滤策略指标到一个排行榜列表。
    """
    # 构建 iv_lookup: candidate_name → iv dict
    iv_lookup = {}
    for iv in iv_results:
        iv_lookup[iv.get("candidate_name", "")] = iv

    # 构建 filter lookup
    filter_lookup = {}
    for f in filter_result.get("filters", []):
        filter_lookup[f["name"]] = f

    rows = []
    for i, cand in enumerate(sorted_candidates):
        name = cand.get("name", "")
        iv_data = iv_lookup.get(name, {})
        row = {
            "rank": i + 1,
            "factor_name": name,
            "pearson_corr": cand.get("pearson_corr"),
            "top20_overlap": cand.get("top20_overlap"),
            "orthogonality_score": cand.get("orthogonality_score"),
            "orthogonality_verdict": cand.get("orthogonality_verdict"),
            "incremental_value_score": iv_data.get("incremental_value_score"),
            "any_improvement": iv_data.get("any_improvement", False),
            "best_strategy": iv_data.get("best_strategy", ""),
            # Filter-level metrics from best strategy, if available
        }
        rows.append(row)

    # 添加过滤策略行
    filter_rows = []
    for f in filter_result.get("filters", []):
        if "error" in f:
            continue
        vs = f.get("vs_baseline", {})
        filter_rows.append({
            "rank": len(rows) + len(filter_rows) + 1,
            "factor_name": f["name"],
            "desc": f.get("desc", ""),
            "type": f.get("type", ""),
            "verdict": f.get("verdict", ""),
            "sharpe_delta": vs.get("sharpe_delta"),
            "return_delta": vs.get("return_delta"),
            "max_drawdown_delta": vs.get("max_drawdown_delta"),
            "calmar_delta": vs.get("calmar_delta"),
        })
    rows.extend(filter_rows)

    return rows


def _make_serializable(obj):
    """递归将 Timestamp/Period 转为字符串 (与 rolling_validator 一致)"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (pd.Timestamp, pd.Period)):
        return str(obj)
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# ─── 6. CLI 入口 ─────────────────────────────────────────────────────


def _print_filter_summary(result: dict):
    """打印过滤策略验证摘要"""
    print(f"\n{'─' * 60}")
    print("  过滤策略验证摘要")
    print(f"{'─' * 60}")
    base = result.get("baseline", {})
    print(f"  基线 ({base.get('ret5_name', 'ret5')}):")
    print(f"    累计收益: {base.get('cumulative_return_pct', 0):.2f}%")
    print(f"    Sharpe:   {base.get('sharpe', 0):.4f}")
    print(f"    最大回撤: {base.get('max_drawdown_pct', 0):.2f}%")
    print()

    for f in result.get("filters", []):
        name = f.get("name", "?")
        ftype = f.get("type", "?")
        verdict = f.get("verdict", "error")
        if "error" in f:
            print(f"  ❌ {name} ({ftype}): {f['error']}")
            continue
        vs = f.get("vs_baseline", {})
        icon = "✅" if verdict == "improvement" else "➖" if verdict == "neutral" else "❌"
        print(f"  {icon} {name} ({ftype}):")
        print(f"      Sharpe: {f.get('metrics', {}).get('sharpe', 0):.4f} "
              f"(Δ={vs.get('sharpe_delta', 0):+.4f}), "
              f"Ret: {f.get('metrics', {}).get('cumulative_return_pct', 0):.2f}% "
              f"(Δ={vs.get('return_delta', 0):+.2f}%), "
              f"DD: {f.get('metrics', {}).get('max_drawdown_pct', 0):.2f}% "
              f"(Δ={vs.get('max_drawdown_delta', 0):+.2f}%)")

    print(f"\n  最佳过滤: {result.get('best_filter', 'N/A')}")
    print(f"  跑赢基线: {result.get('beats_baseline', False)}")
    print(f"{'─' * 60}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ret5 过滤策略验证")
    parser.add_argument("mode", nargs="?", default="filter",
                        choices=["filter", "pipeline"],
                        help="运行模式: filter=仅过滤验证, pipeline=全流程")
    parser.add_argument("--start-date", default="2025-01-02")
    parser.add_argument("--end-date", default="2026-06-30")
    parser.add_argument("--top-quantile", type=float, default=0.2)
    parser.add_argument("--rebalance", default="monthly", choices=["monthly", "weekly"])
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    if args.mode == "pipeline":
        result = run_full_orthogonality_pipeline(
            start_date=args.start_date,
            end_date=args.end_date,
            rebalance=args.rebalance,
            top_quantile=args.top_quantile,
            output_dir=args.output_dir,
        )
        print(f"完整报告: {result.get('output_dir', '')}")
    else:
        # 仅运行过滤验证需要已有数据, 这里只做占位
        print("请通过 Python API 调用 validate_filter_strategies(),")
        print("或在 pipeline 模式下运行全流程。")
