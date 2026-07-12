"""Read auxiliary-data health from DataHub manifests only.

The minute decision loop must not discover its own data files or infer
freshness from arbitrary CSV mtimes. DataHub owns ingestion, provenance,
conflicts and publication; this module consumes the published manifests and
returns a fail-closed gate for missing or stale auxiliary evidence.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import DataItemStatus


BASE = Path(__file__).resolve().parents[3]
PROJECTION_MANIFEST = BASE / "data/audit/manifests/factor_input_projection.json"
EVENT_MANIFESTS = {
    "news": (
        BASE / "data/normalized/events/regulatory_watchlist.manifest.json",
        BASE / "data/events/policy_events.manifest.json",
        BASE / "data/events/preopen_events.manifest.json",
    ),
}

DATASETS = {
    "news": {"manifest_key": "sentiment", "max_age": timedelta(days=2)},
    "capital_flow": {"manifest_key": "fund-flow", "max_age": timedelta(days=7)},
    "fundamentals": {"manifest_key": "fundamentals", "max_age": timedelta(days=180)},
}


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y%m%d", "%Y-%m-%d", "%Y%m%d%H%M%S"):
        try:
            parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
            return parsed.astimezone() if parsed.tzinfo else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except (TypeError, ValueError):
            continue
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Publish one complete health snapshot without exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_projection_manifest() -> dict[str, Any]:
    payload = _read_json(PROJECTION_MANIFEST)
    if payload is None:
        return {"status": "MISSING", "datasets": {}, "path": str(PROJECTION_MANIFEST)}
    payload.setdefault("datasets", {})
    payload["path"] = str(PROJECTION_MANIFEST)
    return payload


def _event_manifest_status() -> dict[str, Any] | None:
    """Return the freshest canonical event manifest without scanning files."""
    manifests = [_read_json(path) for path in EVENT_MANIFESTS["news"]]
    manifests = [item for item in manifests if item]
    if not manifests:
        return None
    return max(
        manifests,
        key=lambda item: _parse_time(item.get("generated_at")) or datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo),
    )


def _conflicts(dataset: str) -> list[dict[str, Any]]:
    rows = []
    for path in (BASE / "data/audit/conflicts.jsonl", BASE / "data/audit/source_conflicts.jsonl"):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("dataset") in {dataset, dataset.replace("_", "-")} and not row.get("resolved_at"):
                rows.append(row)
    return rows


def _manifest_item(
    name: str,
    config: dict[str, Any],
    manifest: dict[str, Any],
    now: datetime,
) -> tuple[DataItemStatus, dict[str, Any]]:
    raw = manifest.get("datasets", {}).get(config["manifest_key"])
    if not isinstance(raw, dict):
        return (
            DataItemStatus(name=name, available=False, fresh=False, source="datahub_manifest", detail="dataset manifest entry missing"),
            {"status": "MISSING", "reason": "dataset manifest entry missing"},
        )
    status = str(raw.get("status") or "MISSING").upper()
    observed = _parse_time(raw.get("observed_at") or raw.get("generated_at"))
    fresh = bool(observed and now - observed <= config["max_age"])
    available = status in {"OK", "PARTITIONED", "COMPLETE"}
    if status in {"EMPTY", "BLOCKED", "MISSING", "INVALID"}:
        available = False
    detail = f"manifest={manifest.get('path', PROJECTION_MANIFEST)}; status={status}"
    if raw.get("evidence"):
        detail += f"; evidence={raw['evidence']}"
    item = DataItemStatus(
        name=name,
        available=available,
        fresh=fresh,
        source=str(raw.get("source") or "datahub_manifest"),
        as_of=observed,
        detail=detail,
    )
    return item, {
        **raw,
        "manifest_status": status,
        "fresh": fresh,
        "conflict_count": 0,
    }


def load_auxiliary_gate(now: datetime | None = None) -> tuple[list[DataItemStatus], list[dict[str, Any]], dict[str, Any]]:
    """Load news/capital-flow/fundamental status without globbing data files."""
    now = now or datetime.now().astimezone()
    projection = _read_projection_manifest()
    items: list[DataItemStatus] = []
    all_conflicts: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "source": "datahub_manifest",
        "projection_manifest": projection.get("path", str(PROJECTION_MANIFEST)),
        "datasets": {},
    }
    for name, config in DATASETS.items():
        item, evidence = _manifest_item(name, config, projection, now)
        # News has an additional canonical event manifest. It is evidence only;
        # the factor projection remains the single status owner.
        if name == "news":
            event_manifest = _event_manifest_status()
            if event_manifest:
                evidence["event_manifest_status"] = event_manifest.get("status")
                evidence["event_manifest_generated_at"] = event_manifest.get("generated_at")
        conflicts = _conflicts(name)
        all_conflicts.extend(conflicts)
        evidence["conflict_count"] = len(conflicts)
        manifest["datasets"][name] = {**item.model_dump(mode="json"), **evidence}
        items.append(item)
    output = BASE / "data/audit/health/decision_gate_manifest.json"
    _atomic_json(output, manifest)
    return items, all_conflicts, manifest
