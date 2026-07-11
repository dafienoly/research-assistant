import json
from datetime import datetime, timedelta, timezone

from commands.scripts import v5_data_integrity_check as integrity


def _reports(root, age_hours: int = 0) -> None:
    root.mkdir(parents=True, exist_ok=True)
    generated = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    payloads = {
        "coverage": {
            "generated_at": generated,
            "universe_status": "OK",
            "active_missing_files": 0,
            "empty_files": 0,
            "stocks_with_data": 2,
            "total_stocks": 2,
            "latest_date": "2026-07-10",
        },
        "freshness": {"generated_at": generated, "status": "OK", "blocking_stock_count": 0},
        "integrity": {"generated_at": generated, "status": "OK", "problematic_file_count": 0},
    }
    for name, payload in payloads.items():
        (root / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_v5_integrity_uses_canonical_health_reports(monkeypatch, tmp_path) -> None:
    _reports(tmp_path)
    monkeypatch.setattr(integrity, "HEALTH_DIR", tmp_path)
    result = integrity.check_kline()
    assert result["status"] == "PASS"
    assert result["source"] == "canonical_datahub_audits"


def test_v5_integrity_fails_closed_on_stale_report(monkeypatch, tmp_path) -> None:
    _reports(tmp_path, age_hours=25)
    monkeypatch.setattr(integrity, "HEALTH_DIR", tmp_path)
    result = integrity.check_kline()
    assert result["status"] == "FAIL"
    assert all("stale" in error for error in result["errors"])
