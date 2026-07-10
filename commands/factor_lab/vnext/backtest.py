"""Policy-hypothesis and multi-regime robustness validation utilities."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .contracts import DataStatus, now_iso


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns.fillna(0)).cumprod()
    drawdown = equity / equity.cummax() - 1
    return abs(float(drawdown.min())) if not drawdown.empty else 0.0


def _metrics(returns: pd.Series) -> dict[str, float | None]:
    clean = returns.dropna()
    if clean.empty:
        return {"total_return": None, "annualized_return": None, "sharpe": None, "sortino": None, "max_drawdown": None, "calmar": None}
    total = float((1 + clean).prod() - 1)
    years = max(len(clean) / 252.0, 1 / 252.0)
    annualized = float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0
    volatility = float(clean.std(ddof=1)) if len(clean) > 1 else 0.0
    downside = float(clean[clean < 0].std(ddof=1)) if len(clean[clean < 0]) > 1 else 0.0
    sharpe = float(clean.mean() / volatility * np.sqrt(252)) if volatility > 1e-12 else None
    sortino = float(clean.mean() / downside * np.sqrt(252)) if downside > 1e-12 else None
    drawdown = _max_drawdown(clean)
    calmar = annualized / drawdown if drawdown > 1e-12 else None
    return {
        "total_return": total,
        "annualized_return": annualized,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": drawdown,
        "calmar": calmar,
    }


def _forward_compound(returns: pd.Series, horizon: int) -> pd.Series:
    return returns.shift(-1).rolling(horizon).apply(lambda values: float(np.prod(1 + values) - 1), raw=True).shift(-(horizon - 1))


class PolicyHypothesisBacktester:
    """Validate support, upper-box risk and breadth-divergence hypotheses."""

    def evaluate(
        self,
        frame: pd.DataFrame,
        *,
        signal_columns: Sequence[str],
        target_columns: Sequence[str],
        benchmark_columns: Sequence[str],
        horizons: Sequence[int] = (1, 3, 5),
        as_of: str = "",
        threshold_variant: str = "fixed",
    ) -> dict[str, Any]:
        missing_signals = sorted(set(signal_columns) - set(frame.columns))
        missing_targets = sorted(set(target_columns) - set(frame.columns))
        missing_benchmarks = sorted(set(benchmark_columns) - set(frame.columns))
        if missing_signals or missing_targets or len(set(benchmark_columns) & set(frame.columns)) == 0:
            return {
                "status": DataStatus.MISSING.value,
                "as_of": as_of,
                "missing_evidence": missing_signals + missing_targets + missing_benchmarks,
                "results": [],
                "threshold_variant": threshold_variant,
            }
        available_benchmarks = [column for column in benchmark_columns if column in frame.columns]
        results: list[dict[str, Any]] = []
        work = frame.sort_index().copy()
        for signal_name in signal_columns:
            events = work[signal_name].fillna(False).astype(bool)
            for target in target_columns:
                for benchmark in available_benchmarks:
                    for horizon in horizons:
                        target_forward = _forward_compound(work[target].astype(float), horizon)
                        benchmark_forward = _forward_compound(work[benchmark].astype(float), horizon)
                        sample = pd.DataFrame(
                            {"target": target_forward[events], "benchmark": benchmark_forward[events]}
                        ).dropna()
                        excess = sample["target"] - sample["benchmark"]
                        results.append(
                            {
                                "signal": signal_name,
                                "target": target,
                                "benchmark": benchmark,
                                "horizon_days": int(horizon),
                                "events": int(len(sample)),
                                "mean_target_return": float(sample["target"].mean()) if len(sample) else None,
                                "mean_benchmark_return": float(sample["benchmark"].mean()) if len(sample) else None,
                                "mean_excess_return": float(excess.mean()) if len(excess) else None,
                                "excess_hit_rate": float((excess > 0).mean()) if len(excess) else None,
                                "evidence_strength": "insufficient" if len(sample) < 20 else ("preliminary" if len(sample) < 60 else "material"),
                            }
                        )
        sample_sizes = [item["events"] for item in results]
        status = DataStatus.OK if sample_sizes and min(sample_sizes) >= 20 and not missing_benchmarks else DataStatus.PARTIAL
        return {
            "status": status.value,
            "as_of": as_of,
            "threshold_variant": threshold_variant,
            "hypothesis_results": results,
            "missing_evidence": missing_benchmarks,
            "fixed_vs_dynamic_comparison_required": True,
            "sample_bias_warning": "results must not be generalized when bull/bear/range/liquidity-shock coverage is incomplete",
            "updated_at": now_iso(),
        }

    @staticmethod
    def compare_threshold_variants(fixed: Mapping[str, Any], dynamic: Mapping[str, Any]) -> dict[str, Any]:
        def aggregate(result: Mapping[str, Any]) -> tuple[float | None, int]:
            rows = [row for row in result.get("hypothesis_results", []) if row.get("mean_excess_return") is not None]
            if not rows:
                return None, 0
            weighted = sum(float(row["mean_excess_return"]) * int(row["events"]) for row in rows)
            events = sum(int(row["events"]) for row in rows)
            return (weighted / events if events else None), events

        fixed_score, fixed_events = aggregate(fixed)
        dynamic_score, dynamic_events = aggregate(dynamic)
        if fixed_score is None or dynamic_score is None:
            verdict = "INSUFFICIENT_EVIDENCE"
        elif dynamic_score > fixed_score:
            verdict = "DYNAMIC_BETTER_IN_SAMPLE"
        elif fixed_score > dynamic_score:
            verdict = "FIXED_BETTER_IN_SAMPLE"
        else:
            verdict = "NO_MATERIAL_DIFFERENCE"
        return {
            "status": DataStatus.OK.value if verdict != "INSUFFICIENT_EVIDENCE" else DataStatus.MISSING.value,
            "fixed_weighted_excess": fixed_score,
            "dynamic_weighted_excess": dynamic_score,
            "fixed_events": fixed_events,
            "dynamic_events": dynamic_events,
            "verdict": verdict,
            "warning": "in-sample superiority is not proof of permanent thresholds",
        }


class RobustnessValidator:
    """Cost, slippage, frequency and regime sensitivity validation."""

    def evaluate(
        self,
        strategy_returns: pd.Series,
        benchmark_returns: Mapping[str, pd.Series],
        *,
        turnover: pd.Series | float,
        regimes: pd.Series | None = None,
        cost_bps: Sequence[float] = (5, 10, 20),
        slippage_bps: Sequence[float] = (3, 6, 12),
        impact_bps: Sequence[float] = (0, 5, 10),
        rebalance_frequencies: Sequence[int] = (1, 5, 20),
    ) -> dict[str, Any]:
        strategy = strategy_returns.astype(float).dropna()
        if strategy.empty:
            return {"status": DataStatus.MISSING.value, "reason": "strategy returns missing"}
        if isinstance(turnover, pd.Series):
            turn = turnover.reindex(strategy.index).fillna(0).astype(float)
        else:
            turn = pd.Series(float(turnover), index=strategy.index)
        baseline = _metrics(strategy)
        sensitivities: list[dict[str, Any]] = []
        for cost in cost_bps:
            for slippage in slippage_bps:
                for impact in impact_bps:
                    drag = turn * (cost + slippage + impact) / 10_000.0
                    net = strategy - drag
                    sensitivities.append(
                        {
                            "cost_bps": cost,
                            "slippage_bps": slippage,
                            "impact_bps": impact,
                            "metrics": _metrics(net),
                            "cost_drag": float(drag.sum()),
                            "invalidated": (_metrics(net).get("sharpe") or -999) <= 0,
                        }
                    )
        frequency_results = []
        for frequency in rebalance_frequencies:
            sampled = strategy.copy()
            if frequency > 1:
                mask = np.arange(len(sampled)) % frequency == 0
                sampled.loc[~mask] = 0.0
            frequency_results.append({"rebalance_every_days": int(frequency), "metrics": _metrics(sampled)})
        regime_results: dict[str, Any] = {}
        if regimes is not None:
            aligned_regime = regimes.reindex(strategy.index)
            for name in sorted(str(value) for value in aligned_regime.dropna().unique()):
                regime_results[name] = _metrics(strategy[aligned_regime.astype(str) == name])
        benchmark_metrics = {}
        benchmark_excess = {}
        benchmark_coverage = {}
        missing_benchmark_evidence = []
        for name, returns in benchmark_returns.items():
            pair = pd.concat(
                [strategy.rename("strategy"), returns.astype(float).rename("benchmark")],
                axis=1,
            ).dropna()
            coverage = len(pair) / len(strategy) if len(strategy) else 0.0
            benchmark_coverage[name] = round(float(coverage), 4)
            benchmark_metrics[name] = _metrics(pair["benchmark"]) if not pair.empty else _metrics(pd.Series(dtype=float))
            benchmark_excess[name] = _metrics(pair["strategy"] - pair["benchmark"]) if not pair.empty else _metrics(pd.Series(dtype=float))
            if coverage < 0.9:
                missing_benchmark_evidence.append(f"{name}:coverage={coverage:.3f}")
        return {
            "status": DataStatus.OK.value if not missing_benchmark_evidence else DataStatus.PARTIAL.value,
            "baseline_metrics": baseline,
            "benchmark_metrics": benchmark_metrics,
            "excess_metrics": benchmark_excess,
            "benchmark_coverage": benchmark_coverage,
            "missing_evidence": missing_benchmark_evidence,
            "cost_slippage_impact_sensitivity": sensitivities,
            "rebalance_frequency_sensitivity": frequency_results,
            "regime_metrics": regime_results,
            "regime_coverage": sorted(regime_results),
            "required_regimes": ["BULL", "BEAR", "RANGE_BOUND", "LIQUIDITY_SHOCK"],
            "missing_regimes": sorted(set(["BULL", "BEAR", "RANGE_BOUND", "LIQUIDITY_SHOCK"]) - set(regime_results)),
            "sample_bias_warning": bool(set(["BULL", "BEAR", "RANGE_BOUND", "LIQUIDITY_SHOCK"]) - set(regime_results)),
            "updated_at": now_iso(),
        }
