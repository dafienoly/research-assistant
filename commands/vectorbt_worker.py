#!/usr/bin/env python3
"""Isolated vectorbt worker that only reads a Hermes snapshot input bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import vectorbt as vbt


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metrics(returns: pd.Series) -> dict[str, float | None]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return {"total_return": None, "annualized_return": None, "sharpe": None, "max_drawdown": None}
    equity = (1 + clean).cumprod()
    total = float(equity.iloc[-1] - 1)
    years = max(len(clean) / 252, 1 / 252)
    annualized = float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0
    volatility = float(clean.std(ddof=1)) if len(clean) > 1 else 0.0
    sharpe = float(clean.mean() / volatility * np.sqrt(252)) if volatility > 1e-12 else None
    drawdown = equity / equity.cummax() - 1
    return {
        "total_return": total,
        "annualized_return": annualized,
        "sharpe": sharpe,
        "max_drawdown": abs(float(drawdown.min())),
    }


def _load_prices(bundle: dict[str, Any], project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    required = {str(symbol) for symbol in bundle["target_weights"]["risk_adjusted_weights"]}
    for entry in bundle["snapshot_entries"]:
        symbol = str(entry.get("instrument_id"))
        if symbol not in required or entry.get("dataset") != "fund_daily":
            continue
        path = Path(str(entry["data_file"])).resolve()
        if project_root not in path.parents:
            raise ValueError(f"snapshot data path outside project: {path}")
        records = json.loads(path.read_text(encoding="utf-8"))
        if _canonical_hash(records) != entry.get("content_hash"):
            raise ValueError(f"snapshot content hash mismatch: {symbol}")
        frame = pd.DataFrame(records)
        required_columns = {"trade_date", "open", "close"}
        if not required_columns.issubset(frame.columns):
            raise ValueError(f"snapshot fields missing for {symbol}: {sorted(required_columns - set(frame.columns))}")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        frame = frame.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last").set_index("trade_date")
        frames[symbol] = frame
    missing = sorted(required - set(frames))
    if missing:
        raise ValueError(f"required target instruments missing from immutable snapshot: {missing}")
    close = pd.concat({symbol: pd.to_numeric(frame["close"], errors="coerce") for symbol, frame in frames.items()}, axis=1)
    opening = pd.concat({symbol: pd.to_numeric(frame["open"], errors="coerce") for symbol, frame in frames.items()}, axis=1)
    common = close.dropna(how="any").index.intersection(opening.dropna(how="any").index).sort_values()
    close = close.loc[common].sort_index()
    opening = opening.loc[common].sort_index()
    if len(close) < 80:
        raise ValueError(f"insufficient aligned sessions: {len(close)}")
    return close, opening


def _portfolio(
    close: pd.DataFrame,
    opening: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    initial_cash: float,
    fees: float,
    slippage: float,
) -> Any:
    return vbt.Portfolio.from_orders(
        close,
        size=targets,
        size_type="targetpercent",
        price=opening,
        fees=fees,
        slippage=slippage,
        cash_sharing=True,
        group_by=True,
        init_cash=initial_cash,
        freq="1D",
    )


def _static_targets(close: pd.DataFrame, weights: dict[str, float], rebalance_days: int) -> pd.DataFrame:
    targets = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    vector = pd.Series(weights, dtype=float).reindex(close.columns).fillna(0.0)
    for index in range(0, len(targets), rebalance_days):
        targets.iloc[index] = vector
    return targets


def _momentum_targets(
    close: pd.DataFrame,
    *,
    lookback: int,
    top_k: int,
    rebalance_days: int,
    invested_weight: float,
) -> pd.DataFrame:
    targets = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    scores = close.pct_change(lookback).shift(1)
    market_trend = close.pct_change(20).mean(axis=1).rolling(5).mean().shift(1)
    for index in range(lookback + 1, len(targets), rebalance_days):
        row = scores.iloc[index].dropna()
        row = row[row > 0].sort_values(ascending=False)
        target = pd.Series(0.0, index=close.columns)
        selected = [] if pd.isna(market_trend.iloc[index]) or market_trend.iloc[index] <= 0 else list(row.head(min(top_k, len(row))).index)
        if selected:
            target.loc[selected] = invested_weight / len(selected)
        targets.iloc[index] = target
    return targets


def _walk_forward(
    scenarios: list[dict[str, Any]],
    returns_by_id: dict[str, pd.Series],
    sessions: int,
) -> list[dict[str, Any]]:
    folds = []
    boundaries = [(0.6, 0.8), (0.8, 1.0)]
    for fold_index, (train_end_fraction, test_end_fraction) in enumerate(boundaries, start=1):
        train_end = max(20, int(sessions * train_end_fraction))
        previous_end = 0
        test_start = train_end
        test_end = max(test_start + 1, int(sessions * test_end_fraction))
        ranked = []
        for scenario in scenarios:
            series = returns_by_id[scenario["scenario_id"]]
            train = series.iloc[previous_end:train_end]
            split_points = np.linspace(0, len(train), 4, dtype=int)
            segments = [
                train.iloc[split_points[index]:split_points[index + 1]]
                for index in range(3)
                if split_points[index + 1] - split_points[index] >= 20
            ]
            segment_sharpes = [float(_metrics(segment).get("sharpe") or -999.0) for segment in segments]
            full_metrics = _metrics(train)
            if not segment_sharpes:
                robust_score = -999.0
            else:
                robust_score = (
                    float(np.median(segment_sharpes))
                    - 0.5 * float(np.std(segment_sharpes))
                    - float(full_metrics.get("max_drawdown") or 0)
                )
            ranked.append((robust_score, scenario, segment_sharpes, full_metrics))
        selected_row = max(ranked, key=lambda item: item[0])
        selected = selected_row[1]
        test = returns_by_id[selected["scenario_id"]].iloc[test_start:test_end]
        folds.append(
            {
                "fold": fold_index,
                "train_start": str(returns_by_id[selected["scenario_id"]].index[previous_end].date()),
                "train_end": str(returns_by_id[selected["scenario_id"]].index[train_end - 1].date()),
                "test_start": str(returns_by_id[selected["scenario_id"]].index[test_start].date()),
                "test_end": str(returns_by_id[selected["scenario_id"]].index[test_end - 1].date()),
                "selected_scenario_id": selected["scenario_id"],
                "selected_parameters": selected["parameters"],
                "train_sharpe": selected_row[3].get("sharpe"),
                "robust_selection_score": selected_row[0],
                "train_segment_sharpes": selected_row[2],
                "selection_method": "expanding_train_median_sharpe_minus_instability_and_drawdown",
                "test_metrics": _metrics(test),
                "purged_signal_lag_days": 1,
            }
        )
    return folds


def run(bundle: dict[str, Any], project_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    close, opening = _load_prices(bundle, project_root)
    config = bundle["research_config"]
    weights = {str(key): float(value) for key, value in bundle["target_weights"]["risk_adjusted_weights"].items()}
    static_targets = _static_targets(close, weights, int(config["static_rebalance_days"]))
    static_pf = _portfolio(
        close,
        opening,
        static_targets,
        initial_cash=float(config["initial_cash"]),
        fees=float(config["fees"]),
        slippage=float(config["slippage_bps"]) / 10_000,
    )
    static_returns = static_pf.returns()
    static_result = {
        "metrics": _metrics(static_returns),
        "orders": int(static_pf.orders.count()),
        "ending_value": _finite(static_pf.value().iloc[-1]),
        "rebalance_days": int(config["static_rebalance_days"]),
        "hindsight_scenario_warning": "current target book replayed historically; not an unbiased strategy estimate",
    }

    scenarios: list[dict[str, Any]] = []
    returns_by_id: dict[str, pd.Series] = {}
    invested = float(sum(weights.values()))
    for lookback in config["momentum_lookbacks"]:
        for top_k in config["top_k"]:
            for frequency in config["rebalance_frequencies_days"]:
                parameters = {
                    "lookback": int(lookback),
                    "top_k": int(top_k),
                    "rebalance_days": int(frequency),
                    "market_trend_filter": "20d_mean_return_5d_smooth_lag1_gt_0",
                }
                scenario_id = f"momentum-{_canonical_hash(parameters)[:12]}"
                targets = _momentum_targets(
                    close,
                    lookback=int(lookback),
                    top_k=int(top_k),
                    rebalance_days=int(frequency),
                    invested_weight=invested,
                )
                portfolio = _portfolio(
                    close,
                    opening,
                    targets,
                    initial_cash=float(config["initial_cash"]),
                    fees=float(config["fees"]),
                    slippage=float(config["slippage_bps"]) / 10_000,
                )
                returns = portfolio.returns()
                returns_by_id[scenario_id] = returns
                scenarios.append(
                    {
                        "scenario_id": scenario_id,
                        "parameters": parameters,
                        "metrics": _metrics(returns),
                        "orders": int(portfolio.orders.count()),
                    }
                )

    cost_stress = []
    for fees_bps, slippage_bps in ((3, 3), (8, 10), (18, 20)):
        portfolio = _portfolio(
            close,
            opening,
            static_targets,
            initial_cash=float(config["initial_cash"]),
            fees=fees_bps / 10_000,
            slippage=slippage_bps / 10_000,
        )
        cost_stress.append(
            {
                "fees_bps": fees_bps,
                "slippage_bps": slippage_bps,
                "metrics": _metrics(portfolio.returns()),
            }
        )

    equal_return = close.pct_change().mean(axis=1).fillna(0.0)
    drawdown_5 = close.mean(axis=1).pct_change(5)
    event_study = []
    for threshold in (-0.02, -0.05):
        events = drawdown_5 <= threshold
        forward = equal_return.shift(-1).rolling(5).sum().shift(-4)
        sample = forward.loc[events].dropna()
        event_study.append(
            {
                "event": "five_day_multi_asset_drawdown",
                "threshold": threshold,
                "horizon_days": 5,
                "events": int(len(sample)),
                "mean_forward_return": _finite(sample.mean()) if len(sample) else None,
                "positive_rate": _finite((sample > 0).mean()) if len(sample) else None,
            }
        )

    walk_forward = _walk_forward(scenarios, returns_by_id, len(close))
    all_oos_positive = len(walk_forward) >= 2 and all(
        float(fold.get("test_metrics", {}).get("total_return") or 0) > 0
        and float(fold.get("test_metrics", {}).get("sharpe") or 0) > 0
        for fold in walk_forward
    )
    return {
        "schema_version": "1.0",
        "status": "OK",
        "quality_status": "BACKTEST_ONLY",
        "run_id": bundle["run_id"],
        "as_of": bundle["as_of"],
        "data_snapshot_id": bundle["data_snapshot_id"],
        "target_weights_hash": bundle["target_weights_hash"],
        "input_bundle_hash": bundle["input_bundle_hash"],
        "engine": {"name": "vectorbt", "version": vbt.__version__, "python": platform.python_version()},
        "sessions": len(close),
        "start_date": str(close.index.min().date()),
        "end_date": str(close.index.max().date()),
        "symbols": list(close.columns),
        "static_target_scenario": static_result,
        "parameter_scan": scenarios,
        "walk_forward": walk_forward,
        "multi_interval_oos_passed": all_oos_positive,
        "strategy_promotion_status": "ELIGIBLE_FOR_REVIEW" if all_oos_positive else "BLOCKED",
        "strategy_promotion_blockers": [] if all_oos_positive else ["one_or_more_oos_folds_non_positive"],
        "cost_slippage_stress": cost_stress,
        "event_study": event_study,
        "execution_truth": False,
        "matrix_fills_are_real_execution": False,
        "data_download_used": False,
        "external_network_used": False,
        "real_broker_called": False,
        "paper_or_live_promotion_allowed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project_root = Path(os.environ.get("HERMES_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if project_root not in input_path.parents or project_root not in output_path.parents:
        raise SystemExit("input/output must remain under HERMES_PROJECT_ROOT")
    bundle = json.loads(input_path.read_text(encoding="utf-8"))
    expected_hash = bundle.pop("input_bundle_hash")
    actual_hash = _canonical_hash(bundle)
    if expected_hash != actual_hash:
        raise SystemExit("input bundle hash mismatch")
    bundle["input_bundle_hash"] = expected_hash
    _atomic_json(output_path, run(bundle, project_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
