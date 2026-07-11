from __future__ import annotations

from data_quality import FreshnessChecker


def test_legacy_snapshot_freshness_is_auxiliary_not_core_blocking(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("data_quality.PATHS", {"data": tmp_path / "data", "audit": tmp_path / "audit"})

    report = FreshnessChecker().check_all()

    assert report["overall_status"] == "missing_files"
    assert report["auxiliary_degraded"] is True
    assert report["blocking"] is False
    assert all(row["gate_scope"].startswith("auxiliary") for row in report["files"])
