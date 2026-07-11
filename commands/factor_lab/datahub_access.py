"""Read-only access to canonical DataHub datasets for downstream modules."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATAHUB_ROOT = Path(os.environ.get("HERMES_DATAHUB_ROOT", PROJECT_ROOT / "data" / "normalized"))
TRADE_CALENDAR_PATH = DATAHUB_ROOT / "calendar" / "trade_calendar.csv"


def read_trade_calendar(path: Path | None = None) -> pd.DataFrame:
    source = path or TRADE_CALENDAR_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub trade calendar missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig")
    required = {"cal_date", "is_open"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical trade calendar missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.copy()
    frame["cal_date"] = frame["cal_date"].astype("string").str.replace(r"\.0$", "", regex=True)
    frame["is_open"] = pd.to_numeric(frame["is_open"], errors="coerce")
    return frame.dropna(subset=["cal_date", "is_open"])


def calendar_row(trading_date: date, path: Path | None = None) -> dict:
    target = trading_date.strftime("%Y%m%d")
    frame = read_trade_calendar(path)
    match = frame[frame["cal_date"].str.replace("-", "") == target]
    if match.empty:
        raise ValueError(f"canonical trade calendar has no row for {target}")
    return match.iloc[-1].to_dict()


def latest_open_date(on_or_before: date, *, lookback_days: int = 20, path: Path | None = None) -> date:
    frame = read_trade_calendar(path)
    parsed = pd.to_datetime(frame["cal_date"], format="%Y%m%d", errors="coerce")
    lower = pd.Timestamp(on_or_before - timedelta(days=lookback_days))
    upper = pd.Timestamp(on_or_before)
    eligible = parsed[(frame["is_open"] == 1) & parsed.between(lower, upper)].dropna()
    if eligible.empty:
        raise ValueError("canonical trade calendar has no recent open date")
    return eligible.max().date()
