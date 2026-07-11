from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_capability_status_generator_has_no_ledger_maintenance_side_effects() -> None:
    source = (ROOT / "commands/scripts/generate_capability_status.py").read_text(encoding="utf-8")

    assert "archive_jsonl" not in source
    assert "unlink(" not in source
    assert "replace(" not in source
