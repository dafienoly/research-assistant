"""Reconcile vectorized research results against A-share event truth replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import DataStatus, now_iso, sha256_payload


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class BacktestReconciler:
    def reconcile(
        self,
        *,
        fast_manifest_path: str | Path,
        event_manifest_path: str | Path,
        output_path: str | Path,
        total_return_tolerance: float = 0.005,
        drawdown_tolerance: float = 0.005,
        ending_value_tolerance_ratio: float = 0.005,
    ) -> dict[str, Any]:
        fast_path = Path(fast_manifest_path)
        event_path = Path(event_manifest_path)
        fast = json.loads(fast_path.read_text(encoding="utf-8"))
        event = json.loads(event_path.read_text(encoding="utf-8"))
        identity_match = (
            fast.get("data_snapshot_id") == event.get("data_snapshot_id")
            and fast.get("target_weights_hash") == event.get("target_weights_hash")
        )
        fast_static = fast.get("static_target_scenario", {})
        fast_metrics = fast_static.get("metrics", {})
        event_metrics = event.get("metrics", {})
        initial_cash = 1_000_000.0
        comparisons = {
            "total_return_abs_gap": abs(float(fast_metrics.get("total_return", 0)) - float(event_metrics.get("total_return", 0))),
            "annualized_return_abs_gap": abs(
                float(fast_metrics.get("annualized_return", 0)) - float(event_metrics.get("annualized_return", 0))
            ),
            "sharpe_abs_gap": abs(float(fast_metrics.get("sharpe", 0)) - float(event_metrics.get("sharpe", 0))),
            "max_drawdown_abs_gap": abs(
                float(fast_metrics.get("max_drawdown", 0)) - float(event_metrics.get("max_drawdown", 0))
            ),
            "ending_value_abs_gap": abs(float(fast_static.get("ending_value", 0)) - float(event.get("ending_value", 0))),
            "ending_value_gap_ratio": abs(
                float(fast_static.get("ending_value", 0)) - float(event.get("ending_value", 0))
            )
            / initial_cash,
            "order_count_gap": int(event.get("orders", 0)) - int(fast_static.get("orders", 0)),
        }
        within_tolerance = (
            identity_match
            and comparisons["total_return_abs_gap"] <= total_return_tolerance
            and comparisons["max_drawdown_abs_gap"] <= drawdown_tolerance
            and comparisons["ending_value_gap_ratio"] <= ending_value_tolerance_ratio
        )
        event_missing = list(event.get("missing_evidence", []))
        promotion_blocked = (
            fast.get("quality_status") != DataStatus.OK.value
            or event.get("quality_status") != DataStatus.OK.value
            or bool(event_missing)
        )
        run_id = f"reconcile-{fast.get('as_of')}-{sha256_payload({'fast': fast.get('run_id'), 'event': event.get('run_id')})[:16]}"
        result = {
            "schema_version": "1.0",
            "status": DataStatus.OK.value if within_tolerance else DataStatus.PARTIAL.value,
            "run_id": run_id,
            "as_of": fast.get("as_of"),
            "data_snapshot_id": fast.get("data_snapshot_id"),
            "target_weights_hash": fast.get("target_weights_hash"),
            "identity_match": identity_match,
            "same_snapshot_and_weights_proven": identity_match,
            "fast_run_id": fast.get("run_id"),
            "event_run_id": event.get("run_id"),
            "fast_manifest_sha256": sha256_payload(fast),
            "event_manifest_sha256": sha256_payload(event),
            "comparisons": comparisons,
            "tolerances": {
                "total_return_abs": total_return_tolerance,
                "max_drawdown_abs": drawdown_tolerance,
                "ending_value_ratio": ending_value_tolerance_ratio,
            },
            "within_tolerance": within_tolerance,
            "expected_semantic_differences": [
                "vectorbt permits fractional target-percent allocation while event lane rounds to 100-share lots",
                "fast lane uses symmetric fee approximation; event lane applies minimum commission and exchange transfer fee",
                "event lane sequences sells then buys and enforces T+1, limits, capacity, partial fill and cancellation",
                "matrix fills are research estimates and never execution truth",
            ],
            "event_missing_evidence": event_missing,
            "promotion_status": DataStatus.BLOCKED.value if promotion_blocked else DataStatus.OK.value,
            "promotion_blocked": promotion_blocked,
            "paper_or_live_promotion_allowed": False,
            "real_broker_called": False,
            "generated_at": now_iso(),
        }
        _atomic_json(Path(output_path), result)
        return result
