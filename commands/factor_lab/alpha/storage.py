"""Cross-process atomic JSON storage for Alpha Registry state."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def update_json(path: Path, default: Any, mutator: Callable[[Any], Any]) -> Any:
    """Lock one JSON file across the complete read-modify-atomic-write transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = read_json(path, default)
        updated = mutator(copy.deepcopy(current))
        _atomic_write(path, current if updated is None else updated)
        return current if updated is None else updated


def write_json(path: Path, payload: Any) -> None:
    update_json(path, payload, lambda _current: payload)


def append_jsonl_unique(path: Path, payload: dict[str, Any], *, unique_fields: tuple[str, ...]) -> bool:
    """Append one durable JSONL row once while preserving all existing bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            with path.open("r", encoding="utf-8") as source:
                for raw in source:
                    try:
                        existing = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(existing, dict) and all(
                        existing.get(field) == payload.get(field) for field in unique_fields
                    ):
                        return False
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, encoded.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True


def _atomic_write(path: Path, payload: Any) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
