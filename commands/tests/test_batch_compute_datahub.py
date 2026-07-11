from __future__ import annotations

from pathlib import Path

import pandas as pd

from factor_lab import batch_compute


def test_batch_compute_reads_canonical_datahub_index(monkeypatch, tmp_path: Path) -> None:
    canonical = tmp_path / "688012.SH.csv"
    pd.DataFrame({
        "ts_code": ["688012.SH", "688012.SH"],
        "trade_date": [20260709, 20260710],
        "open": [10, 11], "high": [11, 12], "low": [9, 10], "close": [10.5, 11.5],
        "vol": [100, 200], "amount": [1000, 2300],
    }).to_csv(canonical, index=False)
    monkeypatch.setattr(batch_compute, "daily_kline_index", lambda: {"688012": canonical})

    frame = batch_compute._load_kline_data()

    assert frame["symbol"].unique().tolist() == ["688012.SH"]
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-09", "2026-07-10"]
    assert frame["volume"].tolist() == [100, 200]


def test_batch_compute_has_no_legacy_kline_root() -> None:
    source = Path(batch_compute.__file__).read_text(encoding="utf-8")
    assert "data/market/daily_kline" not in source
    assert "*_daily_kline.csv" not in source
    assert "daily_kline_index" in source
