import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import factor_commands
import live_readiness


def _write_health(root: Path, *, age_hours: int = 0) -> None:
    health = root / "data" / "audit" / "health"
    health.mkdir(parents=True, exist_ok=True)
    generated_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    payloads = {
        "coverage.json": {
            "generated_at": generated_at,
            "universe_status": "OK",
            "active_missing_files": 0,
            "empty_files": 0,
            "stocks_with_data": 2,
            "total_stocks": 2,
        },
        "freshness.json": {
            "generated_at": generated_at,
            "status": "OK",
            "blocking_stock_count": 0,
        },
        "integrity.json": {
            "generated_at": generated_at,
            "status": "OK",
            "problematic_file_count": 0,
        },
    }
    for name, payload in payloads.items():
        (health / name).write_text(json.dumps(payload), encoding="utf-8")


def test_live_readiness_requires_fresh_canonical_audits(monkeypatch, tmp_path: Path) -> None:
    _write_health(tmp_path)
    monkeypatch.setattr(live_readiness, "PROJECT_ROOT", tmp_path)
    result = live_readiness.LiveReadinessChecker().check_data_health()
    assert result.passed is True
    assert "coverage=2/2" in result.evidence

    _write_health(tmp_path, age_hours=25)
    result = live_readiness.LiveReadinessChecker().check_data_health()
    assert result.passed is False
    assert "audit stale" in result.evidence


def test_cli_production_data_paths_use_datahub_facade() -> None:
    factor_source = Path(factor_commands.__file__).read_text(encoding="utf-8")
    readiness_source = Path(live_readiness.__file__).read_text(encoding="utf-8")
    hermes_source = (Path(__file__).parents[1] / "hermes_cli.py").read_text(encoding="utf-8")
    forbidden = "/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline"
    assert forbidden not in factor_source
    assert forbidden not in readiness_source
    assert forbidden not in hermes_source
    assert "daily_kline_path" in factor_source
    assert "daily_kline_index" in factor_source


def test_production_data_audit_commands_read_health_manifests() -> None:
    pipeline_source = (Path(__file__).parents[1] / "data_pipeline.py").read_text(encoding="utf-8")
    cli_source = (Path(__file__).parents[1] / "hermes_cli.py").read_text(encoding="utf-8")
    assert "run_all_audits" not in pipeline_source
    assert "FreshnessChecker" not in pipeline_source
    assert "DataGapReporter" not in pipeline_source
    assert "from data_quality" not in cli_source
    assert "from data_audit" not in cli_source
    assert "factor_input_projection.json" in pipeline_source
    assert "from data_pipeline import cmd_data_coverage" in cli_source
    assert "from data_pipeline import cmd_data_survivorship" in cli_source
