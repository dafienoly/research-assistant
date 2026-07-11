from __future__ import annotations

from pathlib import Path

import pytest

from factor_lab.vnext.review_orchestrator import ArtifactAntifragileReview


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_formal_antifragile_review_consumes_common_lineage(tmp_path: Path) -> None:
    result = ArtifactAntifragileReview().run(
        PROJECT_ROOT,
        as_of="2026-07-10",
        output_path=tmp_path / "review.json",
    )

    assert result["data_snapshot_id"] == "vnext-2026-07-10-3645917185de479e2cdc"
    assert result["target_weights_hash"] == "59f5a5fca61e07569198c3c76adba06b09a9394b50287dafbbc03e5bc948b8a8"
    assert set(result["layer_attribution"]) == {
        "Data",
        "Regime",
        "Semi State",
        "Policy Put",
        "Factor/ML",
        "Portfolio",
        "Execution",
    }
    assert result["metrics"]["over_aggression_score"] == pytest.approx(0.23)
    assert result["unexplained_discrepancy_count"] == 0
    assert result["promotion_status"] == "BLOCKED"
    assert result["real_broker_called"] is False


def test_formal_antifragile_review_fails_when_required_artifacts_are_absent(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="required review input missing"):
        ArtifactAntifragileReview().run(
            tmp_path,
            as_of="2026-07-10",
            output_path=tmp_path / "review.json",
        )
