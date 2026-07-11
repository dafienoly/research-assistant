"""Row-level integrity audit for canonical DataHub daily market files."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from factor_lab.datahub_access import DATAHUB_ROOT, STOCK_BASIC_PATH, TRADE_CALENDAR_PATH


CANONICAL_DATE = re.compile(r"^\d{8}$")
REQUIRED_DAILY_COLUMNS = {"ts_code", "trade_date", "open", "high", "low", "close"}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _active_codes(path: Path) -> set[str]:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    required = {"ts_code", "list_status"}
    if frame.empty or not required.issubset(frame.columns):
        raise RuntimeError(f"canonical stock reference invalid: {path}")
    active = frame[frame["list_status"].str.strip().str.upper() == "L"]
    return set(active["ts_code"].dropna().str.strip().str.upper())


def _calendar_truth(path: Path) -> tuple[set[str], str | None, str | None]:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    required = {"cal_date", "is_open"}
    if frame.empty or not required.issubset(frame.columns):
        raise RuntimeError(f"canonical trade calendar invalid: {path}")
    dates = frame["cal_date"].str.replace(r"\.0$", "", regex=True)
    open_dates = set(dates[frame["is_open"].astype("string").str.replace(r"\.0$", "", regex=True) == "1"])
    usable = sorted(value for value in dates.dropna() if CANONICAL_DATE.fullmatch(value))
    return open_dates, (usable[0] if usable else None), (usable[-1] if usable else None)


def _finite(value: str | None) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _audit_file(
    path: Path,
    expected_code: str,
    open_dates: set[str],
    calendar_start: str | None,
    calendar_end: str | None,
) -> dict[str, Any]:
    counts = {
        "invalid_schema": 0,
        "invalid_date_format": 0,
        "non_trading_date": 0,
        "symbol_mismatch": 0,
        "invalid_numeric": 0,
        "ohlc_invariant": 0,
        "duplicate_date_conflict": 0,
    }
    samples: list[dict[str, Any]] = []
    seen_dates: dict[str, tuple[str, str, str, str]] = {}
    row_count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not REQUIRED_DAILY_COLUMNS.issubset(reader.fieldnames):
                counts["invalid_schema"] = 1
                return {"path": str(path), "row_count": 0, "counts": counts, "samples": samples}
            for line_number, row in enumerate(reader, start=2):
                row_count += 1
                date_value = str(row.get("trade_date", "")).replace(".0", "").strip()
                code_value = str(row.get("ts_code", "")).strip().upper()
                issues: list[str] = []
                if not CANONICAL_DATE.fullmatch(date_value):
                    counts["invalid_date_format"] += 1
                    issues.append("invalid_date_format")
                elif calendar_start and calendar_end and calendar_start <= date_value <= calendar_end and date_value not in open_dates:
                    counts["non_trading_date"] += 1
                    issues.append("non_trading_date")
                if code_value != expected_code:
                    counts["symbol_mismatch"] += 1
                    issues.append("symbol_mismatch")
                values = tuple(_finite(row.get(column)) for column in ("open", "high", "low", "close"))
                if any(value is None or value <= 0 for value in values):
                    counts["invalid_numeric"] += 1
                    issues.append("invalid_numeric")
                else:
                    open_value, high_value, low_value, close_value = values
                    if high_value < max(open_value, low_value, close_value) or low_value > min(open_value, high_value, close_value):
                        counts["ohlc_invariant"] += 1
                        issues.append("ohlc_invariant")
                signature = tuple(str(row.get(column, "")) for column in ("open", "high", "low", "close"))
                previous = seen_dates.setdefault(date_value, signature)
                if previous != signature:
                    counts["duplicate_date_conflict"] += 1
                    issues.append("duplicate_date_conflict")
                if issues and len(samples) < 20:
                    samples.append({"line": line_number, "trade_date": date_value, "issues": issues})
    except (OSError, UnicodeError, csv.Error) as exc:
        counts["invalid_schema"] += 1
        samples.append({"line": None, "issues": ["unreadable"], "error": str(exc)})
    return {"path": str(path), "row_count": row_count, "counts": counts, "samples": samples}


def audit_daily_integrity(
    *,
    root: Path = DATAHUB_ROOT,
    stock_basic_path: Path = STOCK_BASIC_PATH,
    calendar_path: Path = TRADE_CALENDAR_PATH,
    output_path: Path | None = None,
    max_workers: int = 16,
) -> dict[str, Any]:
    """Audit every active daily file without mutating or deleting source data."""
    active = _active_codes(stock_basic_path)
    open_dates, calendar_start, calendar_end = _calendar_truth(calendar_path)
    market_dir = root / "market"
    files = {
        path.name.removesuffix(".csv"): path
        for path in market_dir.glob("*.csv")
        if not path.name.startswith("valuation_")
    }
    active_files = [(files[code], code) for code in sorted(active & set(files))]

    def inspect(item: tuple[Path, str]) -> dict[str, Any]:
        path, code = item
        return _audit_file(path, code, open_dates, calendar_start, calendar_end)

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(active_files)))) as pool:
        inspected = list(pool.map(inspect, active_files))
    problematic = [item for item in inspected if any(item["counts"].values())]
    totals = {
        key: sum(item["counts"][key] for item in inspected)
        for key in next(iter(inspected), {"counts": {key: 0 for key in ()}})["counts"]
    }
    report = {
        "status": "FAIL" if problematic else "OK",
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": "canonical_datahub_daily_csv",
        "active_stock_count": len(active),
        "files_checked": len(active_files),
        "missing_active_files": sorted(active - set(files)),
        "problematic_file_count": len(problematic),
        "totals": totals,
        "problematic_files": problematic[:1000],
        "ignored_non_active_files": sorted(set(files) - active),
        "mutation_performed": False,
        "recovery_policy": "restore clean D-drive backup first, verify hashes, then incremental pull",
    }
    if report["missing_active_files"]:
        report["status"] = "FAIL"
    destination = output_path or root.parent / "audit" / "health" / "integrity.json"
    _atomic_json(destination, report)
    return report
