"""Non-destructive backup and restore drill for VNext data artifacts."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable

from .contracts import DataStatus, now_iso


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def run_backup_restore_drill(
    project_root: str | Path,
    *,
    source_paths: Iterable[str | Path],
    as_of: str,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Archive real files, restore to an isolated directory, and verify hashes."""
    root = Path(project_root).resolve()
    destination = Path(output_root).resolve() if output_root else root / "artifacts" / "vnext" / "data_backups"
    destination.mkdir(parents=True, exist_ok=True)
    sources: list[tuple[Path, str, str]] = []
    missing: list[str] = []
    for raw in source_paths:
        path = Path(raw).resolve()
        if not path.exists() or not path.is_file():
            missing.append(str(path))
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            missing.append(f"outside_project_root:{path}")
            continue
        data = path.read_bytes()
        sources.append((path, relative, _hash_bytes(data)))
    identity = _hash_bytes(
        json.dumps([(relative, digest) for _, relative, digest in sources], sort_keys=True).encode("utf-8")
    )
    archive = destination / f"recovery_drill_{as_of}_{identity[:12]}.zip"
    if sources and not archive.exists():
        temporary = archive.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path, relative, _ in sources:
                bundle.write(path, arcname=relative)
        temporary.replace(archive)
    archive_hash = _hash_bytes(archive.read_bytes()) if archive.exists() else None
    restore_root = destination / f"restored_{identity[:12]}"
    restored: list[dict[str, Any]] = []
    errors: list[str] = []
    if archive.exists():
        with zipfile.ZipFile(archive, "r") as bundle:
            expected = {relative: digest for _, relative, digest in sources}
            for info in bundle.infolist():
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    errors.append(f"unsafe_archive_member:{info.filename}")
                    continue
                target = (restore_root / member).resolve()
                if restore_root.resolve() not in target.parents:
                    errors.append(f"restore_path_escape:{info.filename}")
                    continue
                data = bundle.read(info)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(data)
                temporary.replace(target)
                actual_hash = _hash_bytes(target.read_bytes())
                restored.append(
                    {
                        "source_relative_path": info.filename,
                        "restored_path": str(target),
                        "expected_sha256": expected.get(info.filename),
                        "actual_sha256": actual_hash,
                        "hash_valid": actual_hash == expected.get(info.filename),
                    }
                )
    verified = bool(sources) and len(restored) == len(sources) and all(item["hash_valid"] for item in restored)
    status = DataStatus.OK if verified and not missing and not errors else DataStatus.PARTIAL if sources else DataStatus.MISSING
    report = {
        "schema_version": "1.0",
        "status": status.value,
        "as_of": as_of,
        "generated_at": now_iso(),
        "non_destructive": True,
        "production_restore_performed": False,
        "archive_path": str(archive),
        "archive_sha256": archive_hash,
        "archive_identity": identity,
        "source_count": len(sources),
        "restored_count": len(restored),
        "restore_root": str(restore_root),
        "restored": restored,
        "missing_sources": missing,
        "errors": errors,
    }
    _atomic_json(destination.parent / "data_recovery_drill_report.json", report)
    return report
