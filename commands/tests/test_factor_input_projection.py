from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factor_lab.datahub_ingestion.factor_inputs import FactorInputProjection


def test_legacy_rebuilder_is_only_a_datahub_facade() -> None:
    source = (Path(__file__).resolve().parents[1] / "data_hub_rebuilder.py").read_text(encoding="utf-8")
    assert "FactorInputProjection" in source
    for forbidden in ("requests", "MX_APIKEY", "baostock", "csv.writer", "news-search"):
        assert forbidden not in source


def test_projection_materializes_canonical_fundamentals_and_fund_flow(tmp_path: Path) -> None:
    fundamentals = tmp_path / "data/normalized/fundamentals"
    fund_flow = tmp_path / "data/normalized/fund_flow"
    fundamentals.mkdir(parents=True)
    fund_flow.mkdir(parents=True)
    pd.DataFrame({
        "ts_code": ["688012.SH"], "ann_date": [20260428], "end_date": [20260331],
        "roe": [12.5], "netprofit_margin": [18.0], "grossprofit_margin": [45.0],
        "debt_to_assets": [20.0], "eps": [1.2],
    }).to_csv(fundamentals / "688012.SH.csv", index=False)
    pd.DataFrame({
        "ts_code": ["688012.SH"], "trade_date": [20260710], "net_mf_amount": [10.0],
        "buy_elg_amount": [7.0], "sell_elg_amount": [2.0],
        "buy_lg_amount": [6.0], "sell_lg_amount": [3.0],
        "buy_md_amount": [4.0], "sell_md_amount": [5.0],
        "buy_sm_amount": [1.0], "sell_sm_amount": [2.0],
    }).to_csv(fund_flow / "688012.SH.csv", index=False)

    projection = FactorInputProjection(tmp_path)
    fundamental_result = projection.build("fundamentals")
    flow_result = projection.build("fund-flow")

    assert fundamental_result["status"] == "OK"
    assert flow_result["status"] == "PARTITIONED"
    fundamental_frame = pd.read_csv(tmp_path / fundamental_result["path"], dtype={"symbol": "string"})
    assert fundamental_frame.iloc[0]["symbol"] == "688012"
    assert fundamental_frame.iloc[0]["report_date"] == "2026-03-31"
    assert fundamental_frame.iloc[0]["pub_date"] == "2026-04-28"
    assert flow_result["path"] == "data/normalized/fund_flow"
    assert flow_result["evidence"]["policy"] == "consumers read only requested symbol partitions"
    assert fundamental_result["sha256"]


def test_sentiment_projection_uses_only_verified_regulatory_snapshot(tmp_path: Path) -> None:
    event_dir = tmp_path / "data/normalized/events"
    event_dir.mkdir(parents=True)
    (event_dir / "regulatory_watchlist.json").write_text(json.dumps({
        "status": "OK", "covered_symbols": ["688012"],
        "announcements": [{
            "symbol": "688012", "date": "2026-07-11", "title": "收到监管函并启动回购",
        }],
    }), encoding="utf-8")

    result = FactorInputProjection(tmp_path).build("sentiment")

    assert result["status"] == "OK"
    frame = pd.read_csv(tmp_path / result["path"], dtype={"symbol": "string"})
    assert frame.iloc[0]["symbol"] == "688012"
    assert frame.iloc[0]["sentiment_score"] == 0.0
    assert result["evidence"]["covered_symbols"] == ["688012"]


def test_projection_preserves_existing_output_when_canonical_input_is_missing(tmp_path: Path) -> None:
    output = tmp_path / "data/fundamentals/fundamentals_timeseries.csv"
    output.parent.mkdir(parents=True)
    output.write_text("sentinel\nkeep\n", encoding="utf-8")

    result = FactorInputProjection(tmp_path).build("fundamentals")

    assert result["status"] == "BLOCKED"
    assert output.read_text(encoding="utf-8") == "sentinel\nkeep\n"
