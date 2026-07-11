"""Atomic state and append-only audit storage outside the repository."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
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
            if target.exists():
                for line in target.read_text(encoding="utf-8").splitlines():
                    if line.strip() and json.loads(line).get("idempotency_key") == idempotency_key:
                        return target, False
            record = {"idempotency_key": idempotency_key, **payload}
            with target.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._bump_version(name)
        return target, True

    def read_jsonl(self, name: str, limit: int | None = None) -> list[dict[str, Any]]:
        target = self.path(name)
        if not target.exists():
            return []
        rows = [
            json.loads(line)
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return rows[-limit:] if limit else rows

    def archive_jsonl(self, name: str, before: datetime) -> Path | None:
        target = self.path(name)
        if not target.exists():
            return None
        with self._lock(target):
            rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
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
                archived_rows = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line.strip()]
            self._atomic_text(
                archive,
                "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in [*archived_rows, *old]),
            )
            self._atomic_text(
                target,
                "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in current),
            )
            self._bump_version(name)
            return archive

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
        started = time.monotonic()
        fd = None
        while fd is None:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 120:
                        lock.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() - started >= timeout:
                    raise TimeoutError(f"state lock timeout: {target.name}")
                time.sleep(0.02)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

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
