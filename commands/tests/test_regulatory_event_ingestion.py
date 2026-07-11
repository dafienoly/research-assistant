import json

import pandas as pd

from factor_lab.datahub_ingestion.regulatory_events import RegulatoryEventIngestion
from factor_lab.risk.pretrade_risk_check import run_pretrade_risk_check
from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist
from factor_lab.risk.st_watchlist import STWatchlist


def test_regulatory_ingestion_classifies_and_records_coverage(tmp_path):
    def fetcher(symbol):
        return [{
            "symbol": symbol, "title": "收到中国证监会立案调查通知",
            "date": "2026-07-10", "source": "cninfo", "id": "ann-1",
        }]

    payload = RegulatoryEventIngestion(tmp_path, fetcher).fetch(["688012.SH"])
    watchlist = RegulatoryWatchlist(tmp_path / "data/normalized/events/regulatory_watchlist.json")

    assert payload["status"] == "OK"
    assert watchlist.load_cache()
    assert watchlist.covers("688012.SH")
    assert not watchlist.covers("688072.SH")
    assert watchlist.is_blacklisted("688012.SH")


def test_pretrade_blocks_symbol_absent_from_regulatory_coverage(tmp_path):
    regulatory = tmp_path / "regulatory.json"
    regulatory.write_text(json.dumps({
        "status": "OK", "covered_symbols": ["688012"], "events": [],
    }), encoding="utf-8")
    stock_basic = tmp_path / "stock_basic.csv"
    stock_basic.write_text(
        "ts_code,symbol,name,list_status\n688012.SH,688012,中微公司,L\n688072.SH,688072,拓荆科技,L\n",
        encoding="utf-8",
    )
    frame = pd.DataFrame([
        {"date": "2026-07-10", "symbol": "688072.SH", "close": 100, "volume": 1000},
    ])
    result = run_pretrade_risk_check(
        [{"symbol": "688072.SH"}], frame, "2026-07-10",
        st_watchlist=STWatchlist(stock_basic),
        regulatory_watchlist=RegulatoryWatchlist(regulatory),
    )

    assert "regulatory_truth_unavailable" in result["details"][0]["risk_type"]
