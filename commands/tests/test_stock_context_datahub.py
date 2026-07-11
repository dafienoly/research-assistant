from __future__ import annotations

import json

import pandas as pd

from stock_context import build_context


def test_stock_context_reads_only_canonical_datahub_inputs(tmp_path):
    reference = tmp_path / "stock_basic.csv"
    pd.DataFrame([{"ts_code": "688012.SH", "symbol": "688012", "name": "中微公司", "industry": "半导体"}]).to_csv(reference, index=False)
    kline = tmp_path / "688012.SH.csv"
    pd.DataFrame([
        {"trade_date": date.strftime("%Y%m%d"), "close": 100 + index, "vol": 1000 + index}
        for index, date in enumerate(pd.date_range("2026-04-01", periods=61, freq="D"))
    ]).to_csv(kline, index=False)
    fundamentals = tmp_path / "fundamentals"
    fundamentals.mkdir()
    pd.DataFrame([{"end_date": "20260331", "eps": 1.48, "roe": 3.95}]).to_csv(fundamentals / "688012.SH.csv", index=False)
    flow = tmp_path / "flow"
    flow.mkdir()
    pd.DataFrame([{"trade_date": "20260710", "net_mf_amount": 1000}]).to_csv(flow / "688012.SH.csv", index=False)
    regulatory = tmp_path / "regulatory.json"
    regulatory.write_text(json.dumps({
        "covered_symbols": ["688012"],
        "announcements": [{"symbol": "688012", "title": "公告", "source": "sse", "source_ref": "a1"}],
    }), encoding="utf-8")

    context = build_context(
        "688012", kline_file=kline, reference_path=reference,
        fundamentals_root=fundamentals, fund_flow_root=flow, regulatory_path=regulatory,
    )

    assert context["name"] == "中微公司"
    assert context["kline"]["latest_date"].startswith("2026-")
    assert context["fundamentals"]["最新财务指标"]["eps"] == 1.48
    assert context["news"][0]["source_ref"] == "a1"
    assert not any("Baostock" in error or "Tavily" in error for error in context["errors"])
