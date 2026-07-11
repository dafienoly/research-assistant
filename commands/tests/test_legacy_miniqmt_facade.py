from pathlib import Path

import pandas as pd
import pytest

import factor_lab.miniqmt as miniqmt


def test_legacy_miniqmt_account_failure_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(miniqmt, "_connected", False)
    with pytest.raises(RuntimeError, match="QMT Bridge"):
        miniqmt.query_positions()
    with pytest.raises(RuntimeError, match="QMT Bridge"):
        miniqmt.query_account()


def test_legacy_miniqmt_kline_reads_canonical_facade(monkeypatch, tmp_path) -> None:
    path = tmp_path / "688012.SH.csv"
    pd.DataFrame(
        [{"trade_date": "20260710", "open": 1, "high": 2, "low": 1, "close": 2, "vol": 100, "amount": 200}]
    ).to_csv(path, index=False)
    monkeypatch.setattr(miniqmt, "daily_kline_path", lambda _symbol: path)
    rows = miniqmt.get_kline("688012", count=1)
    assert rows == [{"date": "20260710", "open": 1.0, "high": 2.0, "low": 1.0, "close": 2.0, "volume": 100.0, "amount": 200.0}]
    with pytest.raises(ValueError, match="minute"):
        miniqmt.get_kline("688012", period="5m")


def test_legacy_miniqmt_has_no_xtdata_or_cache_fallback() -> None:
    source = Path(miniqmt.__file__).read_text(encoding="utf-8")
    assert "xtdata" not in source
    assert "_load_cached" not in source
    assert "except:" not in source
    assert "MiniQMTPositionAdapter" in source
    assert "read_live_snapshot" in source
