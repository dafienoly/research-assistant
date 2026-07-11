from __future__ import annotations

import pandas as pd

import dive_prediction.data_collector as collector
import factor_lab.datahub_access as datahub_access


def test_historical_collector_reads_canonical_datahub_without_writing(tmp_path, monkeypatch):
    source = tmp_path / "159516.SZ.csv"
    pd.DataFrame([
        {"trade_date": "20260709", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
         "vol": 100, "amount": 1000, "pct_chg": 5.0},
        {"trade_date": "20260710", "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
         "vol": 120, "amount": 1200, "pct_chg": 9.5},
    ]).to_csv(source, index=False)
    monkeypatch.setattr(collector, "daily_kline_path", lambda _code: source)

    frame = collector.fetch_etf_hist(days=1)

    assert len(frame) == 1
    assert {"日期", "volume", "change_pct"}.issubset(frame.columns)
    assert frame.iloc[0]["日期"].strftime("%Y-%m-%d") == "2026-07-10"
    assert list(tmp_path.glob("*_hist.csv")) == []


def test_intraday_collector_reads_canonical_snapshot(monkeypatch):
    monkeypatch.setattr(collector, "read_live_snapshot", lambda _codes: {
        collector.ETF_CODE: {
            "observed_at": "2026-07-10T10:00:00+08:00", "open": 1.0, "price": 1.1,
            "high": 1.2, "low": 0.9, "volume": 100, "amount": 1000, "change_pct": 2.0,
        }
    })

    frame = collector.fetch_etf_intraday()

    assert frame is not None
    assert frame.iloc[0]["收盘"] == 1.1


def test_daily_kline_path_searches_equity_and_fund_canonical_roots(tmp_path, monkeypatch):
    equity = tmp_path / "market"
    fund = tmp_path / "market_series" / "fund"
    equity.mkdir(parents=True)
    fund.mkdir(parents=True)
    (equity / "688012.SH.csv").write_text("trade_date,close\n20260710,1\n", encoding="utf-8")
    target = fund / "159516.SZ.csv"
    target.write_text("trade_date,close\n20260710,1\n", encoding="utf-8")
    monkeypatch.setattr(datahub_access, "_daily_kline_candidates", lambda: (equity, fund))

    assert datahub_access.daily_kline_path("159516") == target
