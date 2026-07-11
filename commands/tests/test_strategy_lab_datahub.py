from __future__ import annotations

from pathlib import Path

import pandas as pd

from strategy_lab import backtest, regime, universe


def test_strategy_backtest_reads_canonical_kline(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "688012.SH.csv"
    pd.DataFrame({
        "ts_code": ["688012.SH"], "trade_date": [20260710], "close": [11.5],
        "open": [11], "high": [12], "low": [10], "vol": [200],
    }).to_csv(source, index=False)
    monkeypatch.setattr(backtest, "daily_kline_path", lambda symbol: source)

    rows = backtest.load_kline("688012")

    assert rows[0]["date"] == "2026-07-10"
    assert rows[0]["symbol"] == "688012.SH"
    assert rows[0]["volume"] == 200


def test_strategy_regime_reads_canonical_sse(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "000001.SH.csv"
    pd.DataFrame({
        "trade_date": [20260102, 20260105], "close": [3000.0, 3300.0],
    }).to_csv(source, index=False)
    monkeypatch.setattr(regime, "daily_kline_path", lambda symbol: source)

    assert regime._sse_return("2026-01-01", "2026-12-31") == 0.1


def test_strategy_universe_uses_canonical_reference(monkeypatch, tmp_path: Path) -> None:
    tags = tmp_path / "tags"
    tags.mkdir()
    pd.DataFrame({"code": ["688012"], "name": ["中微公司"]}).to_csv(
        tags / "semiconductor_chain_tags.csv", index=False,
    )
    monkeypatch.setattr(universe, "WSL_TAGS", tags)
    monkeypatch.setattr(universe, "read_stock_industry_map", lambda: {
        "688012": "半导体设备", "000001": "银行",
    })

    stocks, metadata = universe.build_semiconductor_theme()

    assert stocks == [{"symbol": "688012", "universe": "semiconductor_theme"}]
    assert "datahub:stock_basic" in metadata["source_files"]


def test_strategy_lab_contains_no_machine_specific_data_paths() -> None:
    for module in (backtest, regime, universe):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "/mnt/c/Users/" not in source
        assert "/home/ly/" not in source
