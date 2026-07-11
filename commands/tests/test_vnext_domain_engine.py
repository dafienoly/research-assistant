from __future__ import annotations

from factor_lab.vnext.contracts import QualityStatus
from factor_lab.vnext.domain_engine import (
    BreadthDivergenceEngine,
    MultiAssetUniverseRegistry,
)


def test_multi_asset_universe_registry_maps_roles_to_listed_proxies():
    result = MultiAssetUniverseRegistry().build(
        {
            "data_snapshot_id": "snapshot",
            "portfolio_weights": {"semiconductor": 0.5, "bond": 0.5},
        }
    )
    assert result["status"] == QualityStatus.OK.value
    assert {entry["instrument_id"] for entry in result["entries"]} == {"512480.SH", "511010.SH"}
    assert result["account_permission_required_downstream"] is True


def test_breadth_engine_fails_visible_when_market_breadth_is_missing():
    result = BreadthDivergenceEngine().evaluate(
        {
            "advancing": None,
            "declining": None,
            "intraday_reversal_strength": 0.6,
            "semiconductor_relative_strength": 0.7,
            "large_cap_tech_support": 0.5,
        },
        as_of="2026-07-10",
    )
    assert result["status"] == QualityStatus.PARTIAL.value
    assert "market_breadth" in result["missing_evidence"]
    assert result["breadth_divergence_score"] is not None
