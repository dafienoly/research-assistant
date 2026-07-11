from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from factor_lab import datahub_access
from factor_lab.datahub_access import (
    calendar_row,
    daily_kline_path,
    latest_open_date,
    read_live_snapshot,
    read_etf_holdings,
    read_latest_north_flow,
    read_market_turnover,
    read_trade_calendar,
)


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


def write_live_manifest(path, observed_at):
    manifest = {
        "status": "OK",
        "observed_at": observed_at,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "conflicts": [],
    }
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


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
    normalized = tmp_path / "normalized"
    kline = normalized / "market/600000.csv"
    kline.parent.mkdir(parents=True)
    kline.write_text("date,close\n2026-07-10,10\n", encoding="utf-8")
    monkeypatch.setattr(datahub_access, "DATAHUB_ROOT", normalized)
    assert daily_kline_path("600000.SH") == kline
    with pytest.raises(FileNotFoundError):
        daily_kline_path("000001.SZ")


def test_daily_kline_path_blocks_conflicting_canonical_datasets(tmp_path, monkeypatch):
    normalized = tmp_path / "normalized"
    equity = normalized / "market/159516.SZ.csv"
    fund = normalized / "market_series/fund/159516.SZ.csv"
    equity.parent.mkdir(parents=True)
    fund.parent.mkdir(parents=True)
    equity.write_text("trade_date,close\n20260710,1\n", encoding="utf-8")
    fund.write_text("trade_date,close\n20260710,2\n", encoding="utf-8")
    monkeypatch.setattr(datahub_access, "DATAHUB_ROOT", normalized)

    with pytest.raises(ValueError, match="daily conflict"):
        daily_kline_path("159516.SZ")


def test_live_snapshot_normalizes_codes_and_reports_provenance(tmp_path):
    snapshot = tmp_path / "live_snapshot.csv"
    pd.DataFrame(
        [{
            "code": "sh600000", "last_price": 10.5, "change_pct": -1.2,
            "volume": 100, "amount": 1050, "source": "akshare",
            "update_time": "2026-07-10T10:30:00+08:00",
        }]
    ).to_csv(snapshot, index=False)
    write_live_manifest(snapshot, "2026-07-10T10:30:00+08:00")
    rows = read_live_snapshot(
        ["600000", "sh600000"], path=snapshot,
        now=datetime(2026, 7, 10, 10, 30, 30, tzinfo=timezone.utc).astimezone(),
        max_age_seconds=24 * 3600,
    )
    assert rows["600000"]["price"] == 10.5
    assert rows["sh600000"]["change_pct"] == -1.2
    assert rows["600000"]["source"] == "datahub:akshare"


def test_live_snapshot_rejects_stale_truth(tmp_path):
    snapshot = tmp_path / "live_snapshot.csv"
    pd.DataFrame(
        [{
            "code": "600000", "last_price": 10.5, "change_pct": -1.2,
            "source": "akshare", "update_time": "2026-07-10T10:00:00+08:00",
        }]
    ).to_csv(snapshot, index=False)
    write_live_manifest(snapshot, "2026-07-10T10:00:00+08:00")
    with pytest.raises(ValueError, match="stale"):
        read_live_snapshot(
            ["600000"], path=snapshot,
            now=datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc), max_age_seconds=60,
        )


def test_etf_holdings_select_latest_disclosure(tmp_path):
    path = tmp_path / "holdings.csv"
    pd.DataFrame([
        {"etf_code": "588710.SH", "symbol": "688012.SH", "stk_mkv_ratio": 4.0, "end_date": 20250331},
        {"etf_code": "588710.SH", "symbol": "688012.SH", "stk_mkv_ratio": 5.0, "end_date": 20250630},
        {"etf_code": "588710.SH", "symbol": "688072.SH", "stk_mkv_ratio": 6.0, "end_date": 20250630},
    ]).to_csv(path, index=False)

    result = read_etf_holdings("588710.SH", path)

    assert result["end_date"].nunique() == 1
    assert result.iloc[0]["symbol"] == "688072.SH"


def test_north_flow_reads_latest_canonical_observation(tmp_path):
    path = tmp_path / "north.csv"
    pd.DataFrame([
        {"trade_date": 20260709, "north_money": 100},
        {"trade_date": 20260710, "north_money": -250},
    ]).to_csv(path, index=False)
    assert read_latest_north_flow(path)["north_money"] == -250


def test_market_turnover_requires_matching_manifest_hash(tmp_path):
    path = tmp_path / "derived/market_turnover/daily.csv"
    path.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "trade_date": [f"202606{day:02d}" for day in range(1, 21)],
            "market_amount": [500_000_000_000] * 20,
        }
    )
    frame.to_csv(path, index=False)
    manifest = {
        "status": "OK",
        "generated_at": "2026-07-10T16:00:00+08:00",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (path.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = read_market_turnover(
        path,
        now=datetime(2026, 7, 11, 16, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    assert len(result) == 20

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_market_turnover(
            path,
            now=datetime(2026, 7, 11, 16, 0, tzinfo=timezone(timedelta(hours=8))),
        )
