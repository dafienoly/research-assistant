"""Build real auxiliary-data gate items from DataHub files and provenance."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import DataItemStatus


BASE = Path(__file__).resolve().parents[3]


DATASETS = {
    "news": {
        "patterns": ["data/events/**/*.json", "data/events/**/*.jsonl", "data/news/**/*.json"],
        "max_age": timedelta(days=2),
    },
    "capital_flow": {
        "patterns": ["data/normalized/fund_flow/*.csv"],
        "max_age": timedelta(days=7),
    },
    "fundamentals": {
        "patterns": ["data/normalized/fundamentals/*.csv", "data/fundamentals/*.csv"],
        "max_age": timedelta(days=180),
    },
}


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y%m%d", "%Y-%m-%d", "%Y%m%d%H%M%S"):
        try:
            parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
            return parsed.astimezone() if parsed.tzinfo else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            continue
    return None


def _csv_metadata(path: Path) -> tuple[datetime | None, str | None]:
    best = None
    source = None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                source = source or row.get("source_provider") or row.get("source")
                for key in ("observed_at", "trade_date", "ann_date", "end_date", "date", "timeString"):
                    parsed = _parse_time(row.get(key))
                    if parsed and (best is None or parsed > best):
                        best = parsed
                if index >= 500:
                    break
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    return best, source


def _json_metadata(path: Path) -> tuple[datetime | None, str | None]:
    try:
        if path.suffix == ".jsonl":
            lines = path.read_text(encoding="utf-8").splitlines()
            payload = json.loads(lines[-1]) if lines else {}
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            payload = payload[-1] if payload else {}
        if not isinstance(payload, dict):
            return None, None
        observed = None
        for key in ("observed_at", "generated_at", "as_of", "timestamp", "date"):
            observed = _parse_time(payload.get(key))
            if observed:
                break
        return observed, payload.get("source_provider") or payload.get("source")
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None


def _conflicts(dataset: str) -> list[dict[str, Any]]:
    rows = []
    for path in (BASE / "data/audit/conflicts.jsonl", BASE / "data/audit/source_conflicts.jsonl"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("dataset") == dataset and not row.get("resolved_at"):
                rows.append(row)
    return rows


def load_auxiliary_gate(now: datetime | None = None) -> tuple[list[DataItemStatus], list[dict[str, Any]], dict[str, Any]]:
    now = now or datetime.now().astimezone()
    items = []
    manifest: dict[str, Any] = {"generated_at": now.isoformat(), "datasets": {}}
    all_conflicts = []
    for name, config in DATASETS.items():
        paths = []
        for pattern in config["patterns"]:
            paths.extend(BASE.glob(pattern))
        paths = [path for path in paths if path.is_file() and path.stat().st_size > 0]
        latest_path = max(paths, key=lambda path: path.stat().st_mtime) if paths else None
        observed = None
        source = None
        if latest_path:
            observed, source = _csv_metadata(latest_path) if latest_path.suffix == ".csv" else _json_metadata(latest_path)
            observed = observed or datetime.fromtimestamp(latest_path.stat().st_mtime, tz=now.tzinfo)
        conflicts = _conflicts(name)
        all_conflicts.extend(conflicts)
        fresh = bool(observed and now - observed <= config["max_age"])
        item = DataItemStatus(
            name=name,
            available=bool(paths),
            fresh=fresh,
            source=source or ("datahub" if paths else None),
            as_of=observed,
            detail=(f"files={len(paths)}; latest={latest_path}" if paths else "no durable files"),
        )
        items.append(item)
        manifest["datasets"][name] = {
            **item.model_dump(mode="json"),
            "conflict_count": len(conflicts),
        }
    output = BASE / "data/audit/health/decision_gate_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return items, all_conflicts, manifest
