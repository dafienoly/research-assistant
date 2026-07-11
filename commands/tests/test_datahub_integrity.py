from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from factor_lab.datahub_integrity import audit_daily_integrity


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "normalized"
    market = root / "market"
    reference = root / "reference"
    calendar = root / "calendar"
    for directory in (market, reference, calendar):
        directory.mkdir(parents=True)
    stock_basic = reference / "stock_basic.csv"
    pd.DataFrame(
        {"ts_code": ["000001.SZ", "600000.SH"], "list_status": ["L", "L"]}
    ).to_csv(stock_basic, index=False)
    trade_calendar = calendar / "trade_calendar.csv"
    pd.DataFrame(
        {"cal_date": ["20260709", "20260710", "20260711"], "is_open": [1, 1, 0]}
    ).to_csv(trade_calendar, index=False)
    daily = market / "000001.SZ.csv"
    pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20260709", "20260710"],
            "open": [10.0, 10.2],
            "high": [10.5, 10.6],
            "low": [9.9, 10.1],
            "close": [10.2, 10.4],
        }
    ).to_csv(daily, index=False)
    return root, stock_basic, trade_calendar, daily


def test_integrity_audit_is_read_only_and_reports_missing_active_file(tmp_path: Path) -> None:
    root, stock_basic, calendar, daily = _fixture(tmp_path)
    before = _sha(daily)
    output = tmp_path / "integrity.json"
    report = audit_daily_integrity(
        root=root,
        stock_basic_path=stock_basic,
        calendar_path=calendar,
        output_path=output,
        max_workers=2,
    )
    assert report["status"] == "FAIL"
    assert report["missing_active_files"] == ["600000.SH"]
    assert report["mutation_performed"] is False
    assert _sha(daily) == before
    assert output.exists()


def test_integrity_audit_detects_polluted_rows_and_ignores_non_active_sentinel(tmp_path: Path) -> None:
    root, stock_basic, calendar, daily = _fixture(tmp_path)
    polluted = pd.read_csv(daily)
    polluted.loc[len(polluted)] = ["000001.SZ", "2026-07-11", 10.0, 9.0, 11.0, 10.5]
    polluted.to_csv(daily, index=False)
    sentinel = root / "market" / "999999.SZ.csv"
    polluted.to_csv(sentinel, index=False)
    (root / "market" / "600000.SH.csv").write_text(daily.read_text(), encoding="utf-8")

    report = audit_daily_integrity(
        root=root,
        stock_basic_path=stock_basic,
        calendar_path=calendar,
        output_path=tmp_path / "integrity.json",
        max_workers=2,
    )
    assert report["status"] == "FAIL"
    assert report["problematic_file_count"] == 2
    assert report["totals"]["invalid_date_format"] == 2
    assert report["totals"]["ohlc_invariant"] == 2
    assert "999999.SZ" in report["ignored_non_active_files"]
