from __future__ import annotations

import json

import pandas as pd

from factor_lab.datahub_ingestion import market_turnover


def test_market_turnover_projection_aggregates_canonical_partitions(tmp_path, monkeypatch) -> None:
    files = {}
    for symbol, multiplier in (("600000", 1), ("000001", 2)):
        path = tmp_path / f"{symbol}.csv"
        pd.DataFrame(
            {
                "trade_date": [f"202606{day:02d}" for day in range(1, 21)],
                "amount": [100.0 * multiplier] * 20,
            }
        ).to_csv(path, index=False)
        files[symbol] = path
    monkeypatch.setattr(market_turnover, "daily_kline_index", lambda: files)
    output = tmp_path / "derived/market_turnover/daily.csv"

    manifest = market_turnover.build_market_turnover_projection(output)

    projected = pd.read_csv(output)
    assert manifest["status"] == "OK"
    assert manifest["source_files"] == 2
    assert projected["market_amount"].tolist() == [300_000.0] * 20
    assert manifest["unit"] == "CNY"
    persisted = json.loads((output.parent / "manifest.json").read_text(encoding="utf-8"))
    assert persisted["sha256"] == manifest["sha256"]
