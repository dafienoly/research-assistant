"""Atomic artifact store for VNext APIs, reports and historical views."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .contracts import DataStatus, now_iso


SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _json_safe(value: Any) -> Any:
    """Recursively replace non-finite numeric values with JSON ``null``."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            return value
    return value


class VNextArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate(value: str, label: str) -> str:
        if not value or not SAFE_NAME.fullmatch(value):
            raise ValueError(f"unsafe {label}: {value!r}")
        return value

    def component_path(self, component: str, as_of: str) -> Path:
        component = self._validate(component, "component")
        as_of = self._validate(as_of, "date")
        return self.root / component / f"{as_of}.json"

    def write(self, component: str, as_of: str, payload: Mapping[str, Any]) -> Path:
        path = self.component_path(component, as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _json_safe(dict(payload))
        data.setdefault("as_of", as_of)
        data.setdefault("updated_at", now_iso())
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
        latest = path.parent / "latest.json"
        latest_tmp = latest.with_suffix(".json.tmp")
        latest_tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
        latest_tmp.replace(latest)
        return path

    def read(self, component: str, as_of: str | None = None) -> dict[str, Any]:
        component = self._validate(component, "component")
        path = self.component_path(component, as_of) if as_of else self.root / component / "latest.json"
        if not path.exists():
            return self.missing(component, as_of, f"artifact not found: {path.name}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return self.missing(component, as_of, f"artifact unreadable: {type(exc).__name__}")

    def list(self, component: str) -> list[dict[str, Any]]:
        component = self._validate(component, "component")
        directory = self.root / component
        if not directory.exists():
            return []
        output = []
        for path in sorted(directory.glob("*.json"), reverse=True):
            if path.name == "latest.json":
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                output.append(
                    {
                        "id": path.stem,
                        "path": str(path),
                        "status": payload.get("status", DataStatus.PARTIAL.value),
                        "as_of": payload.get("as_of", path.stem),
                        "updated_at": payload.get("updated_at"),
                    }
                )
            except (OSError, json.JSONDecodeError):
                output.append({"id": path.stem, "path": str(path), "status": DataStatus.PARTIAL.value})
        return output

    def report_path(self, as_of: str, extension: str = "md") -> Path:
        self._validate(as_of, "date")
        self._validate(extension, "extension")
        return self.root / "reports" / f"vnext_premarket_{as_of}.{extension}"

    @staticmethod
    def missing(component: str, as_of: str | None, reason: str) -> dict[str, Any]:
        return {
            "status": DataStatus.MISSING.value,
            "component": component,
            "as_of": as_of,
            "confidence": 0.0,
            "evidence": [],
            "missing_evidence": [reason],
            "data_sources": [],
            "updated_at": now_iso(),
            "payload": {},
        }
