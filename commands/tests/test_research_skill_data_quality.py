import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import factor_lab.research_skill.builtins as builtins
from factor_lab.research_skill.skill_registry import REGISTRY_ROOT
from factor_lab.research_skill.skill_runtime import RUNTIME_ROOT


def _health(root: Path, age_hours: int = 0) -> None:
    health = root / "data" / "audit" / "health"
    health.mkdir(parents=True)
    generated = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    reports = {
        "coverage": {"generated_at": generated, "universe_status": "OK", "active_missing_files": 0, "stocks_with_data": 2, "total_stocks": 2},
        "freshness": {"generated_at": generated, "status": "OK"},
        "integrity": {"generated_at": generated, "status": "OK"},
    }
    for name, report in reports.items():
        (health / f"{name}.json").write_text(json.dumps(report), encoding="utf-8")


def test_research_skill_data_quality_uses_canonical_audits(monkeypatch, tmp_path) -> None:
    _health(tmp_path)
    monkeypatch.setattr(builtins, "PROJECT_ROOT", tmp_path)
    result = builtins._execute_data_quality(None, {})
    assert result["status"] == "OK"
    assert result["coverage"] == "2/2"
    assert result["source"] == "canonical_datahub_audits"


def test_research_skill_data_quality_blocks_stale_audits(monkeypatch, tmp_path) -> None:
    _health(tmp_path, age_hours=25)
    monkeypatch.setattr(builtins, "PROJECT_ROOT", tmp_path)
    result = builtins._execute_data_quality(None, {})
    assert result["status"] == "BLOCKED"
    assert len(result["errors"]) == 3


def test_research_skill_runtime_state_is_outside_source_tree() -> None:
    source_root = Path(__file__).resolve().parents[2]
    assert not REGISTRY_ROOT.is_relative_to(source_root)
    assert not RUNTIME_ROOT.is_relative_to(source_root)
