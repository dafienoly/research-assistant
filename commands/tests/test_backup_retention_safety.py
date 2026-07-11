from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_backup_never_deletes_older_snapshots() -> None:
    script = (ROOT / "scripts/backup_data_to_d.sh").read_text(encoding="utf-8")

    assert "rm -rf" not in script
    assert "HERMES_BACKUP_KEEP" not in script
    assert "--link-dest" in script
    assert "FINAL_COMPLETE" in script


def test_restore_is_non_destructive_unless_exact_is_explicit() -> None:
    script = (ROOT / "scripts/restore_data_from_d.sh").read_text(encoding="utf-8")

    assert "EXACT=0" in script
    assert "((EXACT)) && args+=(--delete-delay)" in script
    assert "sha256sum -c" in script
    assert "dry run only" in script
