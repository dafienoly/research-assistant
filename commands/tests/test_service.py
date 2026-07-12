import json

from factor_lab.vnext.service import VNextService


def test_service_missing_component_is_explicit(tmp_path):
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.component("regime", "2026-07-10")
    assert result["status"] == "MISSING"
    assert result["missing_evidence"]


def _write_audit(tmp_path, relative_path, payload):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_data_health_reads_only_canonical_audit_artifacts(tmp_path):
    generated_at = "2026-07-10T15:30:00+08:00"
    _write_audit(
        tmp_path,
        "data/audit/health/coverage.json",
        {"generated_at": generated_at, "universe_status": "OK", "stocks_with_data": 5530, "active_missing_files": 0},
    )
    _write_audit(
        tmp_path,
        "data/audit/health/freshness.json",
        {"generated_at": generated_at, "status": "OK", "blocking_stock_count": 0},
    )
    _write_audit(
        tmp_path,
        "data/audit/health/integrity.json",
        {"generated_at": generated_at, "status": "OK", "files_checked": 5530, "problematic_file_count": 0},
    )
    _write_audit(
        tmp_path,
        "artifacts/vnext/data_audit_report.json",
        {"generated_at": generated_at, "status": "PARTIAL", "data_gap_status": "PARTIAL", "order_draft_status": "BLOCKED"},
    )
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.build_data_health("2026-07-10")
    assert result["status"] == "PARTIAL"
    assert [item["source"] for item in result["sources"]] == [
        "datahub:coverage", "datahub:freshness", "datahub:integrity", "vnext:data-audit"
    ]
    coverage = result["sources"][0]
    assert coverage["status"] == "OK"
    assert coverage["evidence"]["stocks_with_data"] == 5530
    assert result["sources"][-1]["evidence"]["order_draft_status"] == "BLOCKED"


def test_data_health_fails_visible_when_canonical_audits_are_missing(tmp_path):
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.build_data_health("2026-07-10")
    assert result["status"] == "MISSING"
    assert result["confidence"] == 0.0
    assert result["missing_evidence"] == [
        "datahub:coverage", "datahub:freshness", "datahub:integrity", "vnext:data-audit"
    ]


def test_data_health_marks_old_audit_artifact_stale(tmp_path):
    _write_audit(
        tmp_path,
        "data/audit/health/coverage.json",
        {"generated_at": "2026-01-01T15:30:00+08:00", "universe_status": "OK", "stocks_with_data": 5530},
    )
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.build_data_health("2026-07-10")
    coverage = next(item for item in result["sources"] if item["source"] == "datahub:coverage")
    assert coverage["status"] == "STALE"
    assert coverage["age_days"] > 2
