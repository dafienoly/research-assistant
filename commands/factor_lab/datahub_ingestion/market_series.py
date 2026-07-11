"""Ingest index and fund daily series into canonical DataHub storage."""

from __future__ import annotations

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
        results = []
        for api_name, symbols in datasets.items():
            category = "index" if api_name == "index_daily" else "fund"
            for symbol in symbols:
                try:
                    frame = client._query(api_name, ts_code=symbol, start_date=start_date, end_date=end_date)
                    if not isinstance(frame, pd.DataFrame) or frame.empty:
                        raise ValueError("empty provider response")
                    destination = self.output_root / category / f"{symbol}.csv"
                    existing = pd.read_csv(destination, encoding="utf-8-sig") if destination.exists() else pd.DataFrame()
                    combined = pd.concat([existing, frame], ignore_index=True)
                    combined["trade_date"] = combined["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True)
                    combined = combined.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
                    EventTruthIngestion._atomic_frame(destination, combined)
                    results.append({"dataset": api_name, "symbol": symbol, "status": "OK", "rows": len(combined), "path": str(destination)})
                except Exception as exc:
                    results.append({"dataset": api_name, "symbol": symbol, "status": "MISSING", "rows": 0, "error": type(exc).__name__})
        manifest = {
            "source": "tushare_official_structured_gateway",
            "start_date": start_date,
            "end_date": end_date,
            "results": results,
            "status": "OK" if results and all(row["status"] == "OK" for row in results) else "PARTIAL",
        }
        EventTruthIngestion._atomic_json(self.output_root / "manifest.json", manifest)
        return manifest

    @staticmethod
    def _client():
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()
