from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from factor_lab.datahub_access import calendar_row, latest_open_date, read_trade_calendar


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
