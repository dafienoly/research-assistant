"""Artifact-driven seven-layer Antifragile Review orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from .contracts import DataStatus, clamp, now_iso, sha256_payload
from .review import AntifragileReviewEngine


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class ArtifactAntifragileReview:
    """Build review metrics only from formal, lineage-bound artifacts."""

    def run(self, project_root: str | Path, *, as_of: str, output_path: str | Path) -> dict[str, Any]:
        root = Path(project_root).resolve()
        formal = root / "artifacts" / "vnext"
        data = self._read(formal / "data_audit_report.json")
        domain = self._read(formal / "domain_decision.json")
        weights = self._read(formal / "target_weights.json")
        optimization = self._read(formal / "portfolio_optimization.json")
        ml = self._read(formal / "ml_ranker_manifest.json")
        fast = self._read(formal / "fast_backtest_manifest.json")
        event = self._read(formal / "event_backtest_manifest.json")
        reconciliation = self._read(formal / "reconciliation_report.json")
        execution = self._read(formal / "execution_certification.json")
        hypothesis = self._read(root / "data" / "vnext" / "backtests" / f"{as_of}.json")

        inputs = [data, domain, weights, optimization, ml, fast, event, reconciliation, execution, hypothesis]
        snapshot_ids = {str(item["data_snapshot_id"]) for item in inputs if item.get("data_snapshot_id")}
        weights_hashes = {str(item["target_weights_hash"]) for item in inputs if item.get("target_weights_hash")}
        if len(snapshot_ids) != 1 or len(weights_hashes) > 1:
            raise ValueError("review inputs do not share one snapshot and target-weight lineage")
        correlation_id = "corr_" + sha256_payload(
            {"as_of": as_of, "snapshot_ids": sorted(snapshot_ids), "weights_hashes": sorted(weights_hashes)}
        )[:20]

        policy_score = self._signal_hit_rate(hypothesis, ("policy_support_signal", "policy_support_dynamic_signal"))
        box_score = self._signal_hit_rate(hypothesis, ("upper_box_risk_signal", "upper_box_dynamic_risk_signal"))
        breadth_score = self._signal_hit_rate(hypothesis, ("breadth_divergence_signal",))
        xgb_oos = ml.get("ranker", {}).get("oos_score", {})
        ml_positive_rate = self._number(xgb_oos.get("daily_rank_ic_positive_rate"))
        baseline_sharpe = self._number(hypothesis.get("robustness", {}).get("baseline_metrics", {}).get("sharpe"))
        strategy_score = clamp(0.5 + baseline_sharpe) if baseline_sharpe is not None else None
        hard_constraints = optimization.get("hard_constraints_enforced") is True
        execution_ok = execution.get("status") == DataStatus.OK.value
        data_score = {DataStatus.OK.value: 1.0, DataStatus.PARTIAL.value: 0.5}.get(str(data.get("status")), 0.0)
        invested = self._number(weights.get("invested_weight"))
        if invested is None:
            invested = sum(
                float(item.get("eligible_target_weight", 0))
                for item in weights.get("weights", [])
                if isinstance(item, dict)
            )
        risk_budget = self._number(domain.get("recommended_risk_budget"))
        over_aggression = clamp(max(0.0, invested - risk_budget)) if risk_budget is not None else None
        risk_effectiveness = 1.0 if reconciliation.get("within_tolerance") is True and hard_constraints else 0.0

        event_input = {
            "review_id": f"vnext-formal-{as_of}",
            "regime_correct": None,
            "semi_state_correct": None,
            "policy_put_correct": policy_score,
            "box_timing_correct": box_score,
            "breadth_divergence_correct": breadth_score,
            "style_rotation_correct": None,
            "strategy_signal_correct": strategy_score,
            "factor_signal_correct": None,
            "ml_rank_correct": ml_positive_rate,
            "entry_timing_correct": box_score,
            "position_sizing_correct": 1.0 if hard_constraints else 0.0,
            "risk_action_followed": 1.0 if hard_constraints else 0.0,
            "execution_quality": 1.0 if execution_ok else 0.0,
            "data_quality": data_score,
            "true_alpha": None,
            "risk_control_effectiveness": risk_effectiveness,
            "missed_opportunity_score": None,
            "over_aggression_score": over_aggression,
            "model_signal_decay": None,
            "paper_vs_backtest_gap": None,
            "shadow_vs_paper_gap": None,
        }
        base_review = AntifragileReviewEngine().review(event_input, as_of=as_of)
        required_metric_gaps = [
            "semi_mainline_state_accuracy:realized_label_missing",
            "style_rotation_validity:realized_label_missing",
            "regime_hit_rate:realized_label_missing",
            "model_signal_decay:rolling_review_history_missing",
            "paper_vs_backtest_gap:paper_equity_curve_missing",
            "shadow_vs_paper_gap:shadow_equity_curve_missing",
        ]
        unexplained_discrepancies = []
        if reconciliation.get("within_tolerance") is not True:
            unexplained_discrepancies.append("BACKTEST_LANE_GAP_OUTSIDE_TOLERANCE")
        expected_differences = list(reconciliation.get("expected_semantic_differences", []))
        layer_attribution = {
            "Data": self._layer("DOWNGRADE" if data_score < 1 else "KEEP", data.get("status"), ["DATA_AUDIT_PARTIAL"] if data_score < 1 else []),
            "Regime": self._layer("WATCH", domain.get("quality_status"), ["REALIZED_REGIME_LABEL_MISSING"]),
            "Semi State": self._layer("WATCH", domain.get("state"), ["REALIZED_SEMI_STATE_LABEL_MISSING"]),
            "Policy Put": self._layer("TUNE" if (policy_score or 0) < 0.6 else "KEEP", hypothesis.get("status"), ["PRELIMINARY_HYPOTHESIS_EVIDENCE"]),
            "Factor/ML": self._layer("WATCH" if ml.get("promotion_status") == "BLOCKED" else "KEEP", ml.get("status"), list(ml.get("ranker", {}).get("risk_warning", []))),
            "Portfolio": self._layer("KEEP" if hard_constraints else "ESCALATE", optimization.get("status"), [] if hard_constraints else ["HARD_CONSTRAINT_FAILURE"]),
            "Execution": self._layer("WATCH" if execution.get("qmt_read_only_probe", {}).get("status") != DataStatus.OK.value else "KEEP", execution.get("status"), ["QMT_READ_ONLY_PROBE_NOT_READY"] if execution.get("qmt_read_only_probe", {}).get("status") != DataStatus.OK.value else []),
        }
        promotion_blockers = list(data.get("blocking_reasons", [])) + required_metric_gaps + unexplained_discrepancies
        result = {
            **base_review,
            "schema_version": "1.0",
            "status": DataStatus.PARTIAL.value if promotion_blockers else DataStatus.OK.value,
            "correlation_id": correlation_id,
            "data_snapshot_id": next(iter(snapshot_ids)),
            "target_weights_hash": next(iter(weights_hashes), None),
            "layer_attribution": layer_attribution,
            "metrics": {
                **base_review["metrics"],
                "policy_put_hypothesis_score": policy_score,
                "box_timing_accuracy": box_score,
                "breadth_divergence_validity": breadth_score,
                "semi_mainline_state_accuracy": None,
                "style_rotation_validity": None,
                "regime_hit_rate": None,
                "model_signal_decay": None,
                "paper_vs_backtest_gap": None,
                "shadow_vs_paper_gap": None,
            },
            "metric_methodology": {
                "policy_put_hypothesis_score": "mean excess_hit_rate across fixed and dynamic policy-support hypotheses",
                "box_timing_accuracy": "mean excess_hit_rate across fixed and dynamic upper-box hypotheses",
                "breadth_divergence_validity": "mean excess_hit_rate across breadth-divergence hypotheses",
                "over_aggression_score": "max(0, target invested weight - domain recommended risk budget)",
                "risk_control_effectiveness": "1 only when lane reconciliation is within tolerance and portfolio hard constraints pass",
            },
            "reason_codes": sorted({code for layer in layer_attribution.values() for code in layer["reason_codes"]}),
            "required_metric_gaps": required_metric_gaps,
            "expected_semantic_differences": expected_differences,
            "unexplained_discrepancy_count": len(unexplained_discrepancies),
            "unexplained_discrepancies": unexplained_discrepancies,
            "promotion_status": "BLOCKED" if promotion_blockers else "ELIGIBLE_FOR_REVIEW",
            "promotion_blockers": promotion_blockers,
            "input_lineage": {
                "snapshot_ids": sorted(snapshot_ids),
                "target_weights_hashes": sorted(weights_hashes),
                "approval_ids": sorted(str(item.get("approval_id")) for item in execution.get("runs", {}).values() if item.get("approval_id")),
                "execution_ledger_paths": sorted(str(item.get("ledger_path")) for item in execution.get("runs", {}).values() if item.get("ledger_path")),
                "fast_run_id": fast.get("run_id"),
                "event_run_id": event.get("run_id"),
                "reconciliation_run_id": reconciliation.get("run_id"),
            },
            "real_broker_called": False,
            "updated_at": now_iso(),
        }
        result["review_hash"] = sha256_payload({key: value for key, value in result.items() if key != "updated_at"})
        _atomic_json(Path(output_path), result)
        return result

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"required review input missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"review input must be an object: {path}")
        return payload

    @staticmethod
    def _signal_hit_rate(payload: dict[str, Any], signals: Iterable[str]) -> float | None:
        wanted = set(signals)
        values = [
            float(item["excess_hit_rate"])
            for item in payload.get("hypothesis_results", [])
            if item.get("signal") in wanted and item.get("excess_hit_rate") is not None
        ]
        return round(fmean(values), 8) if values else None

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _layer(decision: str, status: Any, reason_codes: list[str]) -> dict[str, Any]:
        return {"decision": decision, "status": status, "reason_codes": reason_codes}
