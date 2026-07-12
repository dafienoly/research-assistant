from __future__ import annotations

import json
from pathlib import Path

from factor_lab.vnext.contracts import TargetPortfolioWeights


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "vnext"


def _load(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))


def test_real_fast_and_event_artifacts_share_snapshot_and_target_weight_identity():
    weights = TargetPortfolioWeights.model_validate(_load("target_weights.json"))
    fast = _load("fast_backtest_manifest.json")
    event = _load("event_backtest_manifest.json")
    reconciliation = _load("reconciliation_report.json")
    assert fast["data_snapshot_id"] == event["data_snapshot_id"] == weights.data_snapshot_id
    assert fast["target_weights_hash"] == event["target_weights_hash"] == weights.target_weights_hash
    assert reconciliation["same_snapshot_and_weights_proven"] is True
    comparisons = reconciliation["comparisons"]
    tolerances = reconciliation["tolerances"]
    expected_within_tolerance = (
        reconciliation["same_snapshot_and_weights_proven"] is True
        and comparisons["total_return_abs_gap"] <= tolerances["total_return_abs"]
        and comparisons["max_drawdown_abs_gap"] <= tolerances["max_drawdown_abs"]
        and comparisons["ending_value_gap_ratio"] <= tolerances["ending_value_ratio"]
    )
    assert reconciliation["within_tolerance"] is expected_within_tolerance


def test_real_vectorbt_manifest_is_isolated_and_never_execution_truth():
    fast = _load("fast_backtest_manifest.json")
    assert fast["engine"]["name"] == "vectorbt"
    assert fast["engine"]["version"] == "1.1.0"
    assert len(fast["parameter_scan"]) == 18
    assert len(fast["walk_forward"]) == 2
    assert fast["data_download_used"] is False
    assert fast["external_network_used"] is False
    assert fast["real_broker_called"] is False
    assert fast["matrix_fills_are_real_execution"] is False
    assert fast["boundary_audit"]["violations"] == []


def test_real_event_manifest_exposes_a_share_mechanics_and_missing_truth_data():
    event = _load("event_backtest_manifest.json")
    mechanics = event["mechanics"]
    for key in (
        "t_plus_one",
        "dynamic_price_limits",
        "st_limit",
        "suspension",
        "board_permission",
        "partial_fill",
        "end_of_day_cancel",
        "volume_capacity",
        "market_impact",
        "adjustment_factor_supported",
    ):
        assert mechanics[key] is True
    assert event["real_broker_called"] is False
    assert event["external_gateway_calls"] == 0
    assert isinstance(event["missing_evidence"], list)
    if event["missing_evidence"]:
        assert event["status"] == "PARTIAL"
    else:
        assert event["status"] == "OK"


def test_reconciliation_cannot_promote_backtest_only_outputs():
    reconciliation = _load("reconciliation_report.json")
    assert reconciliation["promotion_status"] == "BLOCKED"
    assert reconciliation["paper_or_live_promotion_allowed"] is False
    assert reconciliation["real_broker_called"] is False
