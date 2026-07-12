"""Read-only VNext access to canonical DataHub event truth."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


# Compatibility alias for callers while provider ownership moves to DataHub.
EventTruthSourceBuilder = EventTruthIngestion


def load_event_truth(project_root: Path, symbol: str) -> pd.DataFrame:
    root = (project_root / "data/normalized/events/event_truth").resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return pd.DataFrame()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return pd.DataFrame()
    if not isinstance(manifest, dict) or manifest.get("run_status") != "COMPLETE":
        return pd.DataFrame()
    result = next(
        (row for row in manifest.get("results", []) if str(row.get("symbol")) == symbol),
        None,
    )
    if not isinstance(result, dict) or result.get("status") != "OK":
        return pd.DataFrame()
    path = (root / f"{symbol}.csv").resolve()
    if root not in path.parents or not path.is_file():
        return pd.DataFrame()
    expected_hash = str(result.get("sha256") or "")
    if not expected_hash:
        return pd.DataFrame()
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            return pd.DataFrame()
        frame = pd.read_csv(path, dtype={"trade_date": str})
    except (OSError, UnicodeError, pd.errors.ParserError):
        return pd.DataFrame()
    if frame.empty or "trade_date" not in frame:
        return pd.DataFrame()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    return frame.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last").set_index("trade_date")
