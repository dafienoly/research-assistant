"""Atomic state and append-only audit storage outside the repository."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any


class DecisionLoopStore:
    def __init__(self, root: str | Path | None = None):
        configured = root or os.environ.get("HERMES_DECISION_LOOP_STATE_DIR")
        self.root = Path(
            configured or Path.home() / ".hermes/state/research-assistant/decision-loop"
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        safe = Path(name)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError("state name must be relative")
        return self.root / safe

    def exclusive(self, name: str, timeout: float = 1.0):
        """Public cross-process lock used by scheduled cycles and ledgers."""
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        return self._lock(target, timeout)

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.path(name)
        if not target.exists():
            return default
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = target.with_suffix(target.suffix + ".bak")
            if backup.exists():
                recovered = json.loads(backup.read_text(encoding="utf-8"))
                self.append_jsonl(
                    "storage/recovery.jsonl",
                    {"file": name, "recovered_at": datetime.now().astimezone().isoformat()},
                )
                return recovered
            raise

    def write_json(self, name: str, payload: Any) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True, default=str
        )
        with self._lock(target):
            fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                if target.exists():
                    backup = target.with_suffix(target.suffix + ".bak")
                    backup.write_bytes(target.read_bytes())
                os.replace(tmp_name, target)
                self._bump_version(name)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        return target

    def update_json(
        self,
        name: str,
        default: Any,
        mutator: Callable[[Any], Any],
    ) -> Any:
        """Atomically apply a read-modify-write mutation under one file lock."""
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(target):
            if not target.exists():
                current = deepcopy(default)
            else:
                try:
                    current = json.loads(target.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    backup = target.with_suffix(target.suffix + ".bak")
                    if not backup.exists():
                        raise
                    current = json.loads(backup.read_text(encoding="utf-8"))
            updated = mutator(deepcopy(current))
            payload = current if updated is None else updated
            encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(encoded)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                if target.exists():
                    target.with_suffix(target.suffix + ".bak").write_bytes(target.read_bytes())
                os.replace(temporary, target)
                self._bump_version(name)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return payload

    def append_jsonl(self, name: str, payload: Any) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock(target):
            with target.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._bump_version(name)
        return target

    def append_unique_jsonl(self, name: str, payload: dict, idempotency_key: str) -> tuple[Path, bool]:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(target):
            for row in self._read_jsonl_rows(target):
                if row.get("idempotency_key") == idempotency_key:
                    return target, False
            record = {"idempotency_key": idempotency_key, **payload}
            with target.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._bump_version(name)
        return target, True

    def append_unique_jsonl_batch(
        self,
        name: str,
        records: list[tuple[dict, str]],
    ) -> tuple[Path, int]:
        """Append multiple idempotent records under one cross-process lock and fsync."""
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(target):
            existing = {
                str(row.get("idempotency_key"))
                for row in self._read_jsonl_rows(target)
            }
            pending = [
                {"idempotency_key": key, **payload}
                for payload, key in records
                if key not in existing
            ]
            if not pending:
                return target, 0
            with target.open("a", encoding="utf-8") as stream:
                for record in pending:
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._bump_version(name)
        return target, len(pending)

    def read_jsonl(self, name: str, limit: int | None = None) -> list[dict[str, Any]]:
        target = self.path(name)
        rows = self._read_jsonl_rows(target)
        return rows[-limit:] if limit else rows

    def archive_jsonl(self, name: str, before: datetime) -> Path | None:
        target = self.path(name)
        if not target.exists():
            return None
        with self._lock(target):
            rows = self._read_jsonl_rows(target)
            old, current = [], []
            for row in rows:
                raw_time = next(
                    (
                        row.get(key)
                        for key in (
                            "timestamp",
                            "generated_at",
                            "created_at",
                            "attempted_at",
                            "started_at",
                            "completed_at",
                            "acknowledged_at",
                            "updated_at",
                            "as_of",
                            "restored_at",
                            "revoked_at",
                            "activated_at",
                        )
                        if row.get(key)
                    ),
                    None,
                )
                try:
                    parsed = datetime.fromisoformat(str(raw_time))
                except (TypeError, ValueError):
                    current.append(row)
                    continue
                (old if parsed < before else current).append(row)
            if not old:
                return None
            archive = target.parent / "archive" / f"{target.stem}_{before:%Y%m%d}.jsonl"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archived_rows = []
            if archive.exists():
                archived_rows = self._read_jsonl_rows(archive)
            archived_keys = {
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                for row in archived_rows
            }
            unique_old = [
                row
                for row in old
                if json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                not in archived_keys
            ]
            self._atomic_text(
                archive,
                "".join(
                    json.dumps(row, ensure_ascii=False, default=str) + "\n"
                    for row in [*archived_rows, *unique_old]
                ),
            )
            self._atomic_text(
                target,
                "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in current),
            )
            self._bump_version(name)
            return archive

    def archive_selected_jsonl(
        self,
        name: str,
        archive_date: datetime,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> Path | None:
        """Move selected rows to an append-only archive before shrinking a live ledger."""
        target = self.path(name)
        if not target.exists():
            return None
        with self._lock(target):
            rows = self._read_jsonl_rows(target)
            selected = [row for row in rows if predicate(row)]
            if not selected:
                return None
            current = [row for row in rows if not predicate(row)]
            archive = target.parent / "archive" / f"{target.stem}_{archive_date:%Y%m%d}.jsonl"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archived_rows = self._read_jsonl_rows(archive)
            archived_keys = {
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                for row in archived_rows
            }
            unique_selected = [
                row
                for row in selected
                if json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                not in archived_keys
            ]
            self._atomic_text(
                archive,
                "".join(
                    json.dumps(row, ensure_ascii=False, default=str) + "\n"
                    for row in [*archived_rows, *unique_selected]
                ),
            )
            self._atomic_text(
                target,
                "".join(
                    json.dumps(row, ensure_ascii=False, default=str) + "\n"
                    for row in current
                ),
            )
            self._bump_version(name)
            return archive

    def _read_jsonl_rows(self, target: Path) -> list[dict[str, Any]]:
        if not target.exists():
            return []
        rows: list[dict[str, Any]] = []
        corrupt: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("JSONL row must be an object")
                rows.append(value)
            except (json.JSONDecodeError, ValueError) as exc:
                raw_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
                corrupt.append(
                    {
                        "idempotency_key": hashlib.sha256(
                            f"{target}:{line_number}:{raw_hash}".encode("utf-8")
                        ).hexdigest(),
                        "source_file": str(target.relative_to(self.root)),
                        "line_number": line_number,
                        "raw_sha256": raw_hash,
                        "raw_line": line,
                        "error": type(exc).__name__,
                        "quarantined_at": datetime.now().astimezone().isoformat(),
                    }
                )
        if corrupt and "quarantine" not in target.parts:
            self._append_corruption_records(corrupt)
        return rows

    def _append_corruption_records(self, records: list[dict[str, Any]]) -> None:
        quarantine = self.path("quarantine/jsonl_corruption.jsonl")
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(quarantine):
            existing: set[str] = set()
            if quarantine.exists():
                for line in quarantine.read_text(encoding="utf-8").splitlines():
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            existing.add(str(value.get("idempotency_key")))
                    except json.JSONDecodeError:
                        continue
            pending = [row for row in records if row["idempotency_key"] not in existing]
            if not pending:
                return
            with quarantine.open("a", encoding="utf-8") as stream:
                for row in pending:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    @staticmethod
    def _atomic_text(target: Path, content: str) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @contextmanager
    def _lock(self, target: Path, timeout: float = 10.0):
        lock = target.with_suffix(target.suffix + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with lock.open("a+", encoding="utf-8") as handle:
            acquired = False
            while not acquired:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    if time.monotonic() - started >= timeout:
                        raise TimeoutError(f"state lock timeout: {target.name}")
                    time.sleep(0.02)
            try:
                handle.seek(0)
                handle.truncate()
                handle.write(f"{os.getpid()} {time.time()}")
                handle.flush()
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _bump_version(self, name: str) -> None:
        version_file = self.root / "storage" / "versions.json"
        version_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(version_file):
            try:
                versions = json.loads(version_file.read_text(encoding="utf-8")) if version_file.exists() else {}
            except json.JSONDecodeError:
                versions = {}
            current = versions.get(name, {})
            versions[name] = {
                "version": int(current.get("version", 0)) + 1,
                "updated_at": datetime.now().astimezone().isoformat(),
            }
            fd, tmp_name = tempfile.mkstemp(prefix=".versions.", dir=version_file.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(versions, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, version_file)
