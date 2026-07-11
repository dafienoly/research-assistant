"""Trade attribution, path metrics, counterfactual comparison, and governed parameter promotion."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .models import ParameterCandidate, ReviewMetrics
from .storage import DecisionLoopStore


def _period_return(prices: list[float], horizon: int) -> float | None:
    if len(prices) <= horizon or prices[0] <= 0:
        return None
    return (prices[horizon] / prices[0] - 1.0) * 100


def calculate_review(
    entry_price: float,
    path_prices: list[float],
    exit_price: float,
    benchmark_prices: list[float] | None,
    recommended_exit_price: float | None,
    quantity: int,
    fees: float,
    expected_entry_price: float | None = None,
    attribution: dict[str, str] | None = None,
    ordered_quantity: int | None = None,
    filled_quantity: int | None = None,
) -> ReviewMetrics:
    if entry_price <= 0 or exit_price <= 0 or quantity <= 0:
        raise ValueError("entry, exit, and quantity must be positive")
    path = path_prices or [entry_price, exit_price]
    mfe = (max(path) / entry_price - 1.0) * 100
    mae = (min(path) / entry_price - 1.0) * 100
    horizons = {label: days for label, days in (("1d", 1), ("5d", 5), ("20d", 20))}
    returns = {label: _period_return(path, days) for label, days in horizons.items()}
    benchmark_returns = {
        label: _period_return(benchmark_prices, days) if benchmark_prices else None
        for label, days in horizons.items()
    }
    excess = {
        label: (returns[label] - benchmark_returns[label])
        if returns[label] is not None and benchmark_returns[label] is not None
        else None
        for label in horizons
    }
    actual_return = (exit_price / entry_price - 1.0) * 100
    counterfactual = (
        (recommended_exit_price / entry_price - 1.0) * 100
        if recommended_exit_price
        else None
    )
    slippage = (
        ((entry_price / expected_entry_price - 1.0) * 10000)
        if expected_entry_price
        else None
    )
    return ReviewMetrics(
        returns=returns,
        excess_returns=excess,
        mfe_pct=round(mfe, 4),
        mae_pct=round(mae, 4),
        slippage_bps=round(slippage, 4) if slippage is not None else None,
        total_cost=fees,
        execution_feasible=(filled_quantity >= ordered_quantity)
        if ordered_quantity is not None and filled_quantity is not None
        else None,
        system_counterfactual_return_pct=round(counterfactual, 4)
        if counterfactual is not None
        else None,
        actual_minus_system_pct=round(actual_return - counterfactual, 4)
        if counterfactual is not None
        else None,
        attribution=attribution
        or {
            "opportunity": "unreviewed",
            "validation": "unreviewed",
            "entry": "unreviewed",
            "sizing": "unreviewed",
            "exit": "unreviewed",
            "risk_alert": "unreviewed",
        },
    )


def calculate_system_metrics(
    equity_curve: list[float],
    period_days: int,
    turnover_notional: float,
    capacity_estimate: float | None,
    alerts: list[dict[str, Any]],
    book_trade_returns: dict[str, list[float]],
    planned_orders: int = 0,
    filled_orders: int = 0,
) -> dict[str, Any]:
    if len(equity_curve) < 2 or any(value <= 0 for value in equity_curve):
        raise ValueError("equity_curve requires at least two positive values")
    peak = equity_curve[0]
    maximum_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        maximum_drawdown = min(maximum_drawdown, value / peak - 1.0)
    total_return = equity_curve[-1] / equity_curve[0] - 1.0
    annualized_return = (
        (1.0 + total_return) ** (252 / max(period_days, 1)) - 1.0
        if total_return > -1
        else -1.0
    )
    calmar = annualized_return / abs(maximum_drawdown) if maximum_drawdown < 0 else None
    labelled = [row for row in alerts if row.get("true_positive") is not None]
    true_positives = sum(bool(row.get("true_positive")) for row in labelled)
    leads = [
        float(row["lead_minutes"])
        for row in labelled
        if row.get("true_positive") and row.get("lead_minutes") is not None
    ]
    by_book = {}
    for book, returns in book_trade_returns.items():
        by_book[book] = {
            "trades": len(returns),
            "average_return_pct": sum(returns) / len(returns) if returns else None,
            "win_rate": sum(value > 0 for value in returns) / len(returns)
            if returns
            else None,
        }
    return {
        "total_return_pct": total_return * 100,
        "max_drawdown_pct": maximum_drawdown * 100,
        "annualized_return_pct": annualized_return * 100,
        "calmar": calmar,
        "turnover": turnover_notional / (sum(equity_curve) / len(equity_curve)),
        "capacity_estimate": capacity_estimate,
        "execution_feasibility": filled_orders / planned_orders
        if planned_orders
        else None,
        "alert_precision": true_positives / len(labelled) if labelled else None,
        "alert_false_positive_rate": (len(labelled) - true_positives) / len(labelled)
        if labelled
        else None,
        "alert_average_lead_minutes": sum(leads) / len(leads) if leads else None,
        "by_book": by_book,
    }


class ParameterPromotionService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()

    def propose(
        self,
        parameter: str,
        current_value: Any,
        proposed_value: Any,
        evidence: dict[str, Any],
    ) -> ParameterCandidate:
        candidate = ParameterCandidate(
            candidate_id=f"param_{uuid.uuid4().hex}",
            parameter=parameter,
            current_value=current_value,
            proposed_value=proposed_value,
            evidence=evidence,
            created_at=datetime.now().astimezone(),
        )
        self._save(candidate, "proposed")
        return candidate

    def record_oos(
        self, candidate_id: str, passed: bool, metrics: dict[str, Any]
    ) -> ParameterCandidate:
        candidate = self._find(candidate_id)
        evidence = {**candidate.evidence, "oos_metrics": metrics}
        updated = candidate.model_copy(
            update={
                "oos_status": "passed" if passed else "failed",
                "evidence": evidence,
                "status": "candidate" if passed else "rejected",
            }
        )
        self._save(updated, "oos_evaluated")
        return updated

    def weekly_decide(
        self, candidate_id: str, approved: bool, reviewer: str
    ) -> ParameterCandidate:
        candidate = self._find(candidate_id)
        if approved and candidate.oos_status != "passed":
            raise ValueError(
                "parameter cannot be promoted before OOS validation passes"
            )
        now = datetime.now().astimezone()
        updated = candidate.model_copy(
            update={
                "human_status": "approved" if approved else "rejected",
                "status": "promoted" if approved else "rejected",
                "promoted_at": now if approved else None,
                "evidence": {**candidate.evidence, "weekly_reviewer": reviewer},
            }
        )
        self._save(updated, "weekly_decision")
        if approved:
            current = self.store.read_json(
                "parameters/production.json", default={"version": 0, "values": {}}
            )
            values = {
                **current.get("values", {}),
                updated.parameter: updated.proposed_value,
            }
            production = {
                "version": int(current.get("version", 0)) + 1,
                "values": values,
                "promoted_at": now.isoformat(),
                "candidate_id": candidate_id,
            }
            self.store.write_json("parameters/production.json", production)
            self.store.append_jsonl("parameters/production_history.jsonl", production)
        return updated

    def _find(self, candidate_id: str) -> ParameterCandidate:
        rows = self.store.read_jsonl("parameters/candidates.jsonl")
        for row in reversed(rows):
            if row.get("candidate_id") == candidate_id:
                return ParameterCandidate.model_validate(row)
        raise KeyError("parameter candidate not found")

    def _save(self, candidate: ParameterCandidate, action: str) -> None:
        payload = candidate.model_dump(mode="json")
        self.store.append_jsonl("parameters/candidates.jsonl", payload)
        self.store.append_jsonl("parameters/audit.jsonl", {"action": action, **payload})
