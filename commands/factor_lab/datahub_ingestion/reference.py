"""Ingest canonical security master reference data."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


class ReferenceIngestion:
    def __init__(self, project_root: str | Path, client: Any | None = None):
        self.root = Path(project_root).resolve()
        self.output_root = self.root / "data/normalized/reference"
        self.client = client

    def fetch_stock_basic(self) -> dict:
        client = self.client or self._client()
        frames = []
        statuses = {}
        for status in ("L", "P", "D"):
            try:
                frame = client._query("stock_basic", list_status=status)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    frame = frame.copy()
                    frame["list_status"] = status
                    frames.append(frame)
                statuses[status] = {"status": "OK", "rows": len(frame)}
            except Exception as exc:
                statuses[status] = {"status": "MISSING", "rows": 0, "error": type(exc).__name__}
        if not frames:
            return {"status": "MISSING", "datasets": statuses}
        combined = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code", keep="first")
        combined["symbol"] = combined["ts_code"].astype("string").str.strip()
        destination = self.output_root / "stock_basic.csv"
        EventTruthIngestion._atomic_frame(destination, combined)
        observed_at = datetime.now().astimezone().isoformat()
        manifest = {
            "status": "OK" if statuses["L"]["rows"] > 0 else "PARTIAL",
            "source": "tushare:stock_basic",
            "generated_at": observed_at,
            "observed_at": observed_at,
            "active_stocks": int((combined["list_status"] == "L").sum()),
            "total_records": len(combined),
            "datasets": statuses,
            "path": destination.name,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "conflicts": [],
        }
        EventTruthIngestion._atomic_json(self.output_root / "manifest.json", manifest)
        return manifest

    @staticmethod
    def _client():
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()
