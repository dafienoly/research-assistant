"""Atomic state and append-only audit storage outside the repository."""

from __future__ import annotations

import json
import os
import tempfile
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

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.path(name)
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))

    def write_json(self, name: str, payload: Any) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True, default=str
        )
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return target

    def append_jsonl(self, name: str, payload: Any) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return target

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
