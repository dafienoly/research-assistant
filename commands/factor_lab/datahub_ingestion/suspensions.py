"""Persist official suspension evidence for stale active securities."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class SuspensionIngestion:
    def __init__(self, project_root: str | Path, client: Any | None = None):
        self.root = Path(project_root).resolve()
        self.output_root = self.root / "data/normalized/suspend"
        self.client = client

    def refresh_from_health(self) -> dict[str, Any]:
        health_path = self.root / "data/audit/health/freshness.json"
        health = self._read_json(health_path)
        as_of = self._latest_open_date(str(health.get("as_of_open_date") or ""))
        candidates: dict[str, str] = {}
        for key in ("stale_stocks", "old_stocks", "ancient_stocks"):
            for row in health.get(key, []):
                code = str(row.get("ts_code") or "").strip().upper()
                latest = str(row.get("latest_date") or "").strip()
                if code and latest:
                    candidates[code] = latest

        client = self.client or self._client()
        observed_at = datetime.now().astimezone().isoformat()
        fetched_frames: list[pd.DataFrame] = []
        results: list[dict[str, Any]] = []
        for code, latest in sorted(candidates.items()):
            start = (pd.Timestamp(latest) + pd.Timedelta(days=1)).strftime("%Y%m%d")
            end = pd.Timestamp(as_of).strftime("%Y%m%d")
            try:
                frame = client._query(
                    "suspend_d",
                    ts_code=code,
                    start_date=start,
                    end_date=end,
                    fields="ts_code,trade_date,suspend_type",
                )
                frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
                error = None
            except Exception as exc:
                frame = pd.DataFrame()
                error = type(exc).__name__
            if not frame.empty:
                frame = frame.copy()
                frame["source_provider"] = "tushare:suspend_d"
                frame["observed_at"] = observed_at
                fetched_frames.append(frame)
            dates = set(frame.get("trade_date", pd.Series(dtype="string")).astype("string"))
            explained = end in dates
            results.append(
                {
                    "ts_code": code,
                    "latest_market_date": latest,
                    "query_start": start,
                    "query_end": end,
                    "rows": len(frame),
                    "suspended_through_as_of": explained,
                    "error": error,
                }
            )

        destination = self.output_root / "records.csv"
        existing = self._read_frame(destination)
        additions = pd.concat(fetched_frames, ignore_index=True) if fetched_frames else pd.DataFrame()
        combined = pd.concat([existing, additions], ignore_index=True) if not existing.empty else additions
        if not combined.empty:
            combined = combined.drop_duplicates(["ts_code", "trade_date"], keep="last").sort_values(
                ["ts_code", "trade_date"]
            )
            self._atomic_frame(destination, combined)

        unexplained = [row["ts_code"] for row in results if not row["suspended_through_as_of"]]
        errors = [row for row in results if row["error"]]
        manifest = {
            "generated_at": observed_at,
            "source": "tushare:suspend_d",
            "source_health_report": str(health_path),
            "as_of_open_date": as_of,
            "candidate_count": len(candidates),
            "explained_suspensions": len(candidates) - len(unexplained),
            "unexplained_symbols": unexplained,
            "results": results,
            "status": "OK" if not unexplained and not errors else "PARTIAL",
            "conflict_policy": "merge by ts_code+trade_date; preserve historical rows and latest observation metadata",
        }
        self._atomic_json(self.output_root / "manifest.json", manifest)
        return manifest

    @staticmethod
    def _client():
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _read_frame(path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype={"ts_code": "string", "trade_date": "string"})
        except (OSError, UnicodeError, pd.errors.ParserError):
            return pd.DataFrame()

    def _latest_open_date(self, fallback: str) -> str:
        calendar = self.root / "data/normalized/calendar/trade_calendar.csv"
        try:
            frame = pd.read_csv(calendar, encoding="utf-8-sig")
            dates = pd.to_datetime(frame.get("cal_date"), format="%Y%m%d", errors="coerce")
            is_open = pd.to_numeric(frame.get("is_open"), errors="coerce")
            today = pd.Timestamp(datetime.now().astimezone().date())
            eligible = dates[(is_open == 1) & (dates <= today)].dropna()
            if not eligible.empty:
                return eligible.max().date().isoformat()
        except (OSError, UnicodeError, pd.errors.ParserError, TypeError, ValueError):
            pass
        return fallback or datetime.now().astimezone().date().isoformat()

    @staticmethod
    def _atomic_frame(path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8-sig", newline="", dir=path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                frame.to_csv(handle, index=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
