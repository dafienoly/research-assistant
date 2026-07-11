"""Ingest index and fund daily series into canonical DataHub storage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


class MarketSeriesIngestion:
    def __init__(self, project_root: str | Path, client: Any | None = None):
        self.root = Path(project_root).resolve()
        self.output_root = self.root / "data/normalized/market_series"
        self.client = client

    def fetch(self, datasets: dict[str, list[str]], start_date: str, end_date: str) -> dict:
        client = self.client or self._client()
        manifest_path = self.output_root / "manifest.json"
        previous = self._read_manifest(manifest_path)
        result_index = {
            (row.get("dataset"), row.get("symbol")): row
            for row in previous.get("results", [])
            if row.get("dataset") and row.get("symbol")
        }
        generated_at = datetime.now().astimezone().isoformat()
        EventTruthIngestion._atomic_json(
            manifest_path,
            self._manifest(result_index, start_date, end_date, generated_at, "IN_PROGRESS"),
        )
        for api_name, symbols in datasets.items():
            category = "index" if api_name == "index_daily" else "fund"
            for symbol in symbols:
                try:
                    frame = client._query(
                        api_name,
                        ts_code=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        raise_on_failure=True,
                    )
                    if not isinstance(frame, pd.DataFrame) or frame.empty:
                        raise ValueError("empty provider response")
                    destination = self.output_root / category / f"{symbol}.csv"
                    existing = pd.read_csv(destination, encoding="utf-8-sig") if destination.exists() else pd.DataFrame()
                    combined = pd.concat([existing, frame], ignore_index=True)
                    combined["trade_date"] = combined["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True)
                    combined = combined.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
                    EventTruthIngestion._atomic_frame(destination, combined)
                    row = {"dataset": api_name, "symbol": symbol, "status": "OK", "rows": len(combined), "path": str(destination)}
                except Exception as exc:
                    row = {"dataset": api_name, "symbol": symbol, "status": "MISSING", "rows": 0, "error": type(exc).__name__}
                result_index[(api_name, symbol)] = row
                EventTruthIngestion._atomic_json(
                    manifest_path,
                    self._manifest(result_index, start_date, end_date, generated_at, "IN_PROGRESS"),
                )
        manifest = self._manifest(result_index, start_date, end_date, generated_at, "COMPLETE")
        EventTruthIngestion._atomic_json(manifest_path, manifest)
        return manifest

    @staticmethod
    def _read_manifest(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _manifest(
        result_index: dict[tuple[object, object], dict],
        start_date: str,
        end_date: str,
        generated_at: str,
        run_status: str,
    ) -> dict:
        results = sorted(result_index.values(), key=lambda row: (row.get("dataset", ""), row.get("symbol", "")))
        return {
            "source": "tushare_official_structured_gateway",
            "generated_at": generated_at,
            "start_date": start_date,
            "end_date": end_date,
            "results": results,
            "status": (
                "IN_PROGRESS"
                if run_status == "IN_PROGRESS"
                else ("OK" if results and all(row["status"] == "OK" for row in results) else "PARTIAL")
            ),
            "run_status": run_status,
            "merge_policy": "upsert manifest rows by dataset and symbol; never erase unrequested coverage",
        }

    @staticmethod
    def _client():
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()
