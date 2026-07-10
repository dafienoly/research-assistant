"""Antifragile attribution and structured learning feedback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import DataStatus, ReviewDecision, clamp, finite_number, now_iso


class AntifragileReviewEngine:
    DIMENSIONS = (
        "regime_correct",
        "semi_state_correct",
        "policy_put_correct",
        "box_timing_correct",
        "breadth_divergence_correct",
        "style_rotation_correct",
        "strategy_signal_correct",
        "factor_signal_correct",
        "ml_rank_correct",
        "entry_timing_correct",
        "position_sizing_correct",
        "risk_action_followed",
        "execution_quality",
        "data_quality",
        "true_alpha",
    )

    def review(self, event: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
        values = {name: finite_number(event.get(name)) for name in self.DIMENSIONS}
        available = {name: clamp(value) for name, value in values.items() if value is not None}
        missing = [name for name, value in values.items() if value is None]
        pnl = finite_number(event.get("return"))
        benchmark = finite_number(event.get("benchmark_return"))
        semi_beta = finite_number(event.get("semiconductor_beta_return"))
        excess = pnl - benchmark if pnl is not None and benchmark is not None else None
        alpha_after_semi = pnl - semi_beta if pnl is not None and semi_beta is not None else None
        score = sum(available.values()) / len(available) if available else None
        risk_effectiveness = finite_number(event.get("risk_control_effectiveness"))
        missed = finite_number(event.get("missed_opportunity_score"))
        aggression = finite_number(event.get("over_aggression_score"))
        decision = self._decide(score, excess, risk_effectiveness, missed, aggression, len(available))
        attribution = self._attribution(values, pnl, benchmark, semi_beta)
        return {
            "status": (DataStatus.OK if not missing else DataStatus.PARTIAL).value if available else DataStatus.MISSING.value,
            "as_of": as_of,
            "review_id": event.get("review_id"),
            "decision": decision.value,
            "attribution": attribution,
            "evidence": [f"{name}={value:.3f}" for name, value in available.items()],
            "missing_evidence": missing,
            "metrics": {
                "policy_put_hypothesis_score": values["policy_put_correct"],
                "semi_mainline_state_accuracy": values["semi_state_correct"],
                "box_timing_accuracy": values["box_timing_correct"],
                "breadth_divergence_validity": values["breadth_divergence_correct"],
                "style_rotation_validity": values["style_rotation_correct"],
                "missed_opportunity_score": missed,
                "over_aggression_score": aggression,
                "risk_control_effectiveness": risk_effectiveness,
                "regime_hit_rate": values["regime_correct"],
                "model_signal_decay": finite_number(event.get("model_signal_decay")),
                "paper_vs_backtest_gap": finite_number(event.get("paper_vs_backtest_gap")),
                "shadow_vs_paper_gap": finite_number(event.get("shadow_vs_paper_gap")),
                "excess_return": excess,
                "alpha_after_semiconductor_beta": alpha_after_semi,
            },
            "structured_training_sample": {
                "features": {name: value for name, value in values.items()},
                "outcome_return": pnl,
                "benchmark_return": benchmark,
                "label": decision.value,
                "loss_sample": pnl is not None and pnl < 0,
            },
            "updated_at": now_iso(),
        }

    @staticmethod
    def _decide(
        score: float | None,
        excess: float | None,
        risk_effectiveness: float | None,
        missed: float | None,
        aggression: float | None,
        evidence_count: int,
    ) -> ReviewDecision:
        if evidence_count < 5 or score is None:
            return ReviewDecision.WATCH
        if risk_effectiveness is not None and risk_effectiveness < 0.25:
            return ReviewDecision.ESCALATE
        if score < 0.28 and excess is not None and excess < -0.03:
            return ReviewDecision.RETIRE
        if score < 0.42 or (aggression is not None and aggression > 0.7):
            return ReviewDecision.DOWNGRADE
        if (missed is not None and missed > 0.65) or score < 0.62:
            return ReviewDecision.TUNE
        if excess is not None and excess > 0 and score >= 0.68:
            return ReviewDecision.KEEP
        return ReviewDecision.WATCH

    @staticmethod
    def _attribution(
        values: Mapping[str, float | None],
        pnl: float | None,
        benchmark: float | None,
        semi_beta: float | None,
    ) -> list[str]:
        reasons: list[str] = []
        labels = {
            "regime_correct": "regime judgement",
            "semi_state_correct": "semiconductor mainline judgement",
            "entry_timing_correct": "entry timing",
            "position_sizing_correct": "position sizing",
            "execution_quality": "execution quality",
            "data_quality": "data quality",
        }
        for key, label in labels.items():
            value = values.get(key)
            if value is not None and value < 0.4:
                reasons.append(f"weak {label}")
        if pnl is not None and benchmark is not None and abs(pnl - benchmark) < 0.005:
            reasons.append("outcome is mostly market beta")
        if pnl is not None and semi_beta is not None and abs(pnl - semi_beta) < 0.005:
            reasons.append("outcome is mostly semiconductor beta")
        if not reasons:
            reasons.append("no single dominant failure source; treat as normal variance pending more samples")
        return reasons

    @staticmethod
    def append_training_sample(path: str | Path, review: Mapping[str, Any]) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(review["structured_training_sample"], ensure_ascii=False) + "\n")

    @staticmethod
    def aggregate(reviews: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not reviews:
            return {"status": DataStatus.MISSING.value, "reviews": 0}
        metric_keys = set().union(*(review.get("metrics", {}).keys() for review in reviews))
        aggregate: dict[str, float | None] = {}
        for key in metric_keys:
            values = [finite_number(review.get("metrics", {}).get(key)) for review in reviews]
            clean = [value for value in values if value is not None]
            aggregate[key] = sum(clean) / len(clean) if clean else None
        decisions: dict[str, int] = {}
        for review in reviews:
            label = str(review.get("decision", "WATCH"))
            decisions[label] = decisions.get(label, 0) + 1
        return {
            "status": DataStatus.OK.value,
            "reviews": len(reviews),
            "decision_counts": decisions,
            "metrics": aggregate,
            "updated_at": now_iso(),
        }
