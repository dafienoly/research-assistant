"""Ingest official event truth into canonical DataHub storage."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class EventTruthIngestion:
    def __init__(self, project_root: str | Path, client: Any | None = None):
        self.root = Path(project_root).resolve()
        self.output_root = self.root / "data/normalized/events/event_truth"
        self.client = client

    def fetch(self, symbols: list[str], start_date: str, end_date: str) -> dict:
        client = self.client or self._client()
        results = []
        generated_at = datetime.now().astimezone().isoformat()
        manifest_path = self.output_root / "manifest.json"
        self._atomic_json(
            manifest_path,
            self._manifest(results, generated_at, start_date, end_date, "IN_PROGRESS"),
        )
        for symbol in symbols:
            datasets = {}
            errors = []
            for dataset, api_name, fields in (
                ("stk_limit", "stk_limit", "ts_code,trade_date,up_limit,down_limit"),
                ("suspend_d", "suspend_d", "ts_code,trade_date,suspend_type"),
                ("adj_factor", "fund_adj", "ts_code,trade_date,adj_factor"),
                ("dividend", "fund_div", "ts_code,ex_date,div_cash,div_proc"),
            ):
                try:
                    params = {"ts_code": symbol, "fields": fields}
                    if dataset != "dividend":
                        params.update({"start_date": start_date, "end_date": end_date})
                    frame = client._query(api_name, raise_on_failure=True, **params)
                    datasets[dataset] = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
                except Exception as exc:
                    datasets[dataset] = pd.DataFrame()
                    errors.append({"dataset": dataset, "api_name": api_name, "error": type(exc).__name__})
            merged = self._merge(datasets, start_date, end_date)
            destination = self.output_root / f"{symbol}.csv"
            fresh_rows = sum(len(frame) for frame in datasets.values())
            if fresh_rows:
                merged = self._merge_existing(destination, merged)
                self._atomic_frame(destination, merged)
                write_status = "UPDATED"
            else:
                merged = self._read_existing(destination)
                write_status = "PRESERVED" if destination.exists() else "NOT_WRITTEN"
            results.append(
                {
                    "symbol": symbol,
                    "path": str(destination),
                    "rows": len(merged),
                    "coverage": {name: len(frame) for name, frame in datasets.items()},
                    "errors": errors,
                    "write_status": write_status,
                    "status": "OK" if not errors and len(datasets["stk_limit"]) > 0 and len(datasets["adj_factor"]) > 0 else "PARTIAL",
                }
            )
            self._atomic_json(
                manifest_path,
                self._manifest(results, generated_at, start_date, end_date, "IN_PROGRESS"),
            )
        manifest = self._manifest(results, generated_at, start_date, end_date, "COMPLETE")
        self._atomic_json(manifest_path, manifest)
        return manifest

    @staticmethod
    def _manifest(
        results: list[dict], generated_at: str, start_date: str, end_date: str, run_status: str,
    ) -> dict:
        return {
            "generated_at": generated_at,
            "source": "tushare_official_structured_gateway",
            "start_date": start_date,
            "end_date": end_date,
            "results": results,
            "status": (
                "IN_PROGRESS"
                if run_status == "IN_PROGRESS"
                else ("OK" if results and all(row["status"] == "OK" for row in results) else "PARTIAL")
            ),
            "run_status": run_status,
            "conflict_policy": "retain source observation; never replace with calculated values",
        }

    @staticmethod
    def _client():
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()

    @staticmethod
    def _merge(datasets: dict[str, pd.DataFrame], start_date: str, end_date: str) -> pd.DataFrame:
        dates = pd.DataFrame(
            {"trade_date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date), freq="D").strftime("%Y%m%d")}
        )
        for name in ("stk_limit", "suspend_d", "adj_factor"):
            frame = datasets[name].copy()
            if frame.empty or "trade_date" not in frame:
                continue
            keep = [column for column in frame.columns if column != "ts_code"]
            dates = dates.merge(frame[keep].drop_duplicates("trade_date", keep="last"), on="trade_date", how="left")
        dividend = datasets["dividend"].copy()
        if not dividend.empty and "ex_date" in dividend:
            dividend = dividend.rename(columns={"ex_date": "trade_date", "div_cash": "cash_div"})
            keep = [column for column in dividend.columns if column != "ts_code"]
            dates = dates.merge(dividend[keep].drop_duplicates("trade_date", keep="last"), on="trade_date", how="left")
        dates["source_provider"] = "tushare"
        dates["observed_at"] = datetime.now().astimezone().isoformat()
        return dates

    @staticmethod
    def _read_existing(path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, encoding="utf-8-sig", dtype="string")

    @classmethod
    def _merge_existing(cls, path: Path, fresh: pd.DataFrame) -> pd.DataFrame:
        existing = cls._read_existing(path)
        if existing.empty:
            return fresh
        old = existing.drop_duplicates("trade_date", keep="last").set_index("trade_date")
        new = fresh.drop_duplicates("trade_date", keep="last").set_index("trade_date")
        combined = new.combine_first(old).reset_index()
        return combined.sort_values("trade_date", kind="stable").reset_index(drop=True)

    @staticmethod
    def _atomic_frame(path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=path.parent, delete=False) as handle:
                temp = Path(handle.name)
                frame.to_csv(handle, index=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            temp = None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temp = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            temp = None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
