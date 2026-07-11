"""Ingest corporate event truth for research consumers into canonical DataHub."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_recovery import atomic_write_frame
from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


EVENT_APIS = {
    "forecast": ("forecast", ("ann_date", "end_date")),
    "holdertrade": ("stk_holdertrade", ("change_date", "ann_date")),
    "repurchase": ("repurchase", ("ann_date", "end_date")),
    "share_float": ("share_float", ("float_date", "ann_date")),
    "dividend": ("dividend", ("ann_date", "ex_date")),
}


class CorporateEventIngestion:
    """Single owner for structured company-event provider calls and persistence."""

    def __init__(
        self,
        project_root: str | Path,
        client: Any | None = None,
        *,
        circuit_breaker_threshold: int = 3,
    ):
        self.root = Path(project_root).resolve()
        self.output_root = self.root / "data/normalized/events/corporate_events"
        self.client = client
        if circuit_breaker_threshold < 1:
            raise ValueError("circuit_breaker_threshold must be positive")
        self.circuit_breaker_threshold = circuit_breaker_threshold

    def fetch(self, symbols: list[str], start_date: str, end_date: str) -> dict:
        client = self.client or self._client()
        observed_at = datetime.now().astimezone().isoformat()
        results = []
        failures = {dataset: 0 for dataset in EVENT_APIS}
        circuits: dict[str, dict] = {}
        manifest_path = self.output_root / "manifest.json"
        EventTruthIngestion._atomic_json(
            manifest_path,
            self._manifest(results, observed_at, start_date, end_date, circuits, "IN_PROGRESS"),
        )
        for symbol in dict.fromkeys(symbols):
            rows: list[dict] = []
            errors: list[dict] = []
            coverage: dict[str, int] = {}
            for dataset, (api_name, date_candidates) in EVENT_APIS.items():
                if dataset in circuits:
                    coverage[dataset] = 0
                    errors.append({
                        "dataset": dataset,
                        "api_name": api_name,
                        "error": "CircuitOpen",
                        "reason": circuits[dataset]["reason"],
                    })
                    continue
                try:
                    params = {"ts_code": symbol}
                    if dataset != "dividend":
                        params.update({"start_date": start_date, "end_date": end_date})
                    frame = client._query(api_name, **params)
                    frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
                    coverage[dataset] = len(frame)
                    rows.extend(self._normalize(frame, symbol, dataset, date_candidates, observed_at, start_date, end_date))
                except Exception as error:
                    failures[dataset] += 1
                    coverage[dataset] = 0
                    error_name = type(error).__name__
                    errors.append({"dataset": dataset, "api_name": api_name, "error": error_name})
                    if failures[dataset] >= self.circuit_breaker_threshold:
                        circuits[dataset] = {
                            "api_name": api_name,
                            "reason": f"{failures[dataset]} cumulative {error_name} failures in this run",
                            "opened_at_symbol": symbol,
                        }
            destination = self.output_root / f"{symbol}.csv"
            merged = self._merge_existing(destination, pd.DataFrame(rows))
            if not merged.empty:
                content_hash = atomic_write_frame(merged, destination)
            else:
                content_hash = None
            status = "OK" if rows and not errors else ("PARTIAL" if rows or destination.exists() else "MISSING")
            results.append({
                "symbol": symbol,
                "path": destination.name,
                "rows": len(merged),
                "new_rows": len(rows),
                "coverage": coverage,
                "errors": errors,
                "sha256": content_hash,
                "status": status,
            })
            EventTruthIngestion._atomic_json(
                manifest_path,
                self._manifest(results, observed_at, start_date, end_date, circuits, "IN_PROGRESS"),
            )
        manifest = self._manifest(results, observed_at, start_date, end_date, circuits)
        EventTruthIngestion._atomic_json(manifest_path, manifest)
        return manifest

    @staticmethod
    def _manifest(
        results: list[dict],
        observed_at: str,
        start_date: str,
        end_date: str,
        circuits: dict[str, dict],
        run_status: str = "COMPLETE",
    ) -> dict:
        return {
            "status": (
                "IN_PROGRESS"
                if run_status == "IN_PROGRESS"
                else ("OK" if results and all(row["status"] == "OK" for row in results) else "PARTIAL")
            ),
            "run_status": run_status,
            "dataset": "normalized/events/corporate_events",
            "generated_at": observed_at,
            "start_date": start_date,
            "end_date": end_date,
            "source": "tushare_official_structured_gateway",
            "results": results,
            "circuits": circuits,
            "conflict_policy": "append observations; deduplicate exact dataset/date/payload identity",
        }

    @staticmethod
    def _normalize(
        frame: pd.DataFrame,
        symbol: str,
        dataset: str,
        date_candidates: tuple[str, ...],
        observed_at: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        if frame.empty:
            return []
        rows = []
        for payload in frame.to_dict(orient="records"):
            raw_date = None
            for key in date_candidates:
                candidate = payload.get(key)
                if candidate is not None and not pd.isna(candidate) and str(candidate).strip():
                    raw_date = candidate
                    break
            parsed = pd.to_datetime(raw_date, errors="coerce")
            if pd.isna(parsed):
                continue
            compact = parsed.strftime("%Y%m%d")
            if compact < start_date or compact > end_date:
                continue
            rows.append({
                "ts_code": symbol,
                "event_dataset": dataset,
                "event_date": compact,
                "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                "source_provider": "tushare",
                "observed_at": observed_at,
            })
        return rows

    @staticmethod
    def _merge_existing(path: Path, fresh: pd.DataFrame) -> pd.DataFrame:
        frames = []
        if path.exists():
            frames.append(pd.read_csv(path, encoding="utf-8-sig", dtype="string"))
        if not fresh.empty:
            frames.append(fresh)
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True, sort=False)
        return (
            combined.drop_duplicates(["ts_code", "event_dataset", "event_date", "payload"], keep="last")
            .sort_values(["event_date", "event_dataset"], kind="stable")
            .reset_index(drop=True)
        )

    @staticmethod
    def _client():
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()
