from __future__ import annotations

import asyncio
import json
from pathlib import Path

from factor_lab.api_server import routes_data


def _body(response):
    return json.loads(response.body.decode("utf-8"))


def test_coverage_endpoint_reads_health_manifest_without_csv_scan(tmp_path, monkeypatch):
    health = tmp_path / "health"
    health.mkdir()
    (health / "coverage.json").write_text(
        json.dumps({
            "generated_at": "2026-07-12T10:00:00+08:00",
            "universe_status": "OK",
            "total_stocks": 10,
            "stocks_with_data": 10,
            "active_missing_files": 0,
            "total_rows": 123,
            "earliest_date": "20260101",
            "latest_date": "20260711",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_data, "HEALTH_ROOT", health)
    result = _body(asyncio.run(routes_data.data_coverage()))
    assert result["data"]["source"] == "datahub:audit/health/coverage.json"
    assert result["data"]["coverage"][0]["row_count"] == 123


def test_manifest_endpoint_uses_explicit_paths_and_keeps_missing_status(tmp_path, monkeypatch):
    health = tmp_path / "health"
    health.mkdir()
    (health / "coverage.json").write_text('{"status":"OK"}', encoding="utf-8")
    manifest = tmp_path / "reference.json"
    manifest.write_text(
        json.dumps({"status": "OK", "source": "test", "total_records": 10, "sha256": "abc"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_data, "HEALTH_ROOT", health)
    monkeypatch.setattr(routes_data, "EXPLICIT_MANIFESTS", {"reference": manifest, "missing": tmp_path / "none.json"})
    result = _body(asyncio.run(routes_data.data_manifests()))
    rows = {item["manifest_id"]: item for item in result["data"]["manifests"]}
    assert rows["reference"]["status"] == "OK"
    assert rows["reference"]["record_count"] == 10
    assert rows["missing"]["status"] == "MISSING"


def test_data_routes_do_not_glob_or_delegate_to_legacy_data_quality():
    source = Path(routes_data.__file__).read_text(encoding="utf-8")
    assert ".glob(" not in source
    assert "data_quality" not in source
    assert "data/market/daily_kline" not in source
