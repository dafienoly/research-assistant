from __future__ import annotations

import pandas as pd

from factor_lab.datahub_ingestion.market_series import MarketSeriesIngestion


class Client:
    def _query(self, _api_name, **params):
        return pd.DataFrame([{"ts_code": params["ts_code"], "trade_date": "20260710", "close": 100}])


def test_market_series_ingestion_writes_canonical_datahub_files(tmp_path):
    result = MarketSeriesIngestion(tmp_path, Client()).fetch(
        {"index_daily": ["000001.SH"], "fund_daily": ["512480.SH"]},
        "20260701",
        "20260710",
    )
    assert result["status"] == "OK"
    assert (tmp_path / "data/normalized/market_series/index/000001.SH.csv").exists()
    assert (tmp_path / "data/normalized/market_series/fund/512480.SH.csv").exists()
