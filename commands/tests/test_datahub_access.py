from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from factor_lab import datahub_access
from factor_lab.datahub_access import calendar_row, daily_kline_path, latest_open_date, read_trade_calendar


def write_calendar(tmp_path):
    path = tmp_path / "trade_calendar.csv"
    pd.DataFrame(
        [
            {"cal_date": 20260709, "is_open": 1},
            {"cal_date": 20260710, "is_open": 1},
            {"cal_date": 20260711, "is_open": 0},
        ]
    ).to_csv(path, index=False)
    return path


def test_downstream_calendar_reads_canonical_datahub_file(tmp_path):
    path = write_calendar(tmp_path)
    assert len(read_trade_calendar(path)) == 3
    assert int(calendar_row(date(2026, 7, 11), path)["is_open"]) == 0
    assert latest_open_date(date(2026, 7, 11), path=path) == date(2026, 7, 10)


def test_missing_or_invalid_calendar_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_trade_calendar(tmp_path / "missing.csv")
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("date,value\n20260711,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_trade_calendar(invalid)


def test_daily_kline_path_uses_canonical_roots_and_fails_when_symbol_missing(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    kline = shared / "market/daily_kline/600000.csv"
    kline.parent.mkdir(parents=True)
    kline.write_text("date,close\n2026-07-10,10\n", encoding="utf-8")
    monkeypatch.setattr(datahub_access, "SHARED_DATAHUB_ROOT", shared)
    monkeypatch.setattr(datahub_access, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(datahub_access, "DATAHUB_ROOT", tmp_path / "normalized")
    assert daily_kline_path("600000.SH") == kline
    with pytest.raises(FileNotFoundError):
        daily_kline_path("000001.SZ")
