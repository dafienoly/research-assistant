from __future__ import annotations

from factor_lab.vnext.contracts import DataStatus
from factor_lab.vnext.recovery_drill import run_backup_restore_drill


def test_backup_restore_drill_is_hash_verified_and_non_destructive(tmp_path):
    source = tmp_path / "data" / "sample.csv"
    source.parent.mkdir()
    source.write_text("trade_date,close\n20260710,10\n", encoding="utf-8")

    report = run_backup_restore_drill(
        tmp_path,
        source_paths=[source],
        as_of="2026-07-10",
    )

    assert report["status"] == DataStatus.OK.value
    assert report["non_destructive"] is True
    assert report["production_restore_performed"] is False
    assert report["source_count"] == report["restored_count"] == 1
    assert report["restored"][0]["hash_valid"] is True
    assert source.read_text(encoding="utf-8").startswith("trade_date")
