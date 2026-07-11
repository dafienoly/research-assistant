from __future__ import annotations

import json

from factor_lab.vnext.contracts import DataStatus
from factor_lab.vnext.reconciliation import BacktestReconciler


def test_reconciliation_requires_same_snapshot_and_weights_and_keeps_promotion_blocked(tmp_path):
    fast = {
        "run_id": "fast-1",
        "as_of": "2026-07-10",
        "data_snapshot_id": "snapshot-1",
        "target_weights_hash": "weights-1",
        "quality_status": "BACKTEST_ONLY",
        "static_target_scenario": {
            "metrics": {"total_return": 0.1, "annualized_return": 0.2, "sharpe": 1.0, "max_drawdown": 0.05},
            "ending_value": 1_100_000,
            "orders": 10,
        },
    }
    event = {
        "run_id": "event-1",
        "as_of": "2026-07-10",
        "data_snapshot_id": "snapshot-1",
        "target_weights_hash": "weights-1",
        "quality_status": "BACKTEST_ONLY",
        "metrics": {"total_return": 0.098, "annualized_return": 0.198, "sharpe": 0.98, "max_drawdown": 0.051},
        "ending_value": 1_098_000,
        "orders": 12,
        "missing_evidence": ["official_stk_limit"],
    }
    fast_path = tmp_path / "fast.json"
    event_path = tmp_path / "event.json"
    fast_path.write_text(json.dumps(fast), encoding="utf-8")
    event_path.write_text(json.dumps(event), encoding="utf-8")

    result = BacktestReconciler().reconcile(
        fast_manifest_path=fast_path,
        event_manifest_path=event_path,
        output_path=tmp_path / "reconciliation.json",
    )

    assert result["status"] == DataStatus.OK.value
    assert result["same_snapshot_and_weights_proven"] is True
    assert result["within_tolerance"] is True
    assert result["promotion_status"] == DataStatus.BLOCKED.value
    assert result["paper_or_live_promotion_allowed"] is False


def test_identity_mismatch_is_partial_even_when_metrics_match(tmp_path):
    base = {
        "run_id": "run",
        "as_of": "2026-07-10",
        "target_weights_hash": "weights",
        "quality_status": "OK",
        "metrics": {"total_return": 0.0, "annualized_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0},
        "ending_value": 1_000_000,
        "orders": 0,
        "missing_evidence": [],
    }
    fast = {
        **base,
        "data_snapshot_id": "snapshot-a",
        "static_target_scenario": {"metrics": base["metrics"], "ending_value": 1_000_000, "orders": 0},
    }
    event = {**base, "data_snapshot_id": "snapshot-b"}
    fast_path = tmp_path / "fast.json"
    event_path = tmp_path / "event.json"
    fast_path.write_text(json.dumps(fast), encoding="utf-8")
    event_path.write_text(json.dumps(event), encoding="utf-8")
    result = BacktestReconciler().reconcile(
        fast_manifest_path=fast_path,
        event_manifest_path=event_path,
        output_path=tmp_path / "out.json",
    )
    assert result["status"] == DataStatus.PARTIAL.value
    assert result["identity_match"] is False
