from __future__ import annotations

import pandas as pd

from factor_lab.datahub_ingestion.reference import ReferenceIngestion
from factor_lab.datahub_access import read_stock_industry_map, read_stock_name_map
from factor_lab.vnext.data_audit import _expected_stock_count


class Client:
    def _query(self, _api_name, **params):
        code = {"L": "600000.SH", "P": "600001.SH", "D": "600002.SH"}[params["list_status"]]
        return pd.DataFrame([{"ts_code": code, "name": code, "industry": "银行"}])


def test_reference_ingestion_persists_active_universe_for_audit(tmp_path):
    result = ReferenceIngestion(tmp_path, Client()).fetch_stock_basic()
    assert result["status"] == "OK"
    assert result["active_stocks"] == 1
    assert _expected_stock_count(tmp_path) == (
        1,
        "data/normalized/reference/stock_basic.csv:list_status=L",
    )
    persisted = tmp_path / "data/normalized/reference/stock_basic.csv"
    assert read_stock_name_map(persisted)["600000"] == "600000.SH"
    assert read_stock_industry_map(persisted)["600000"] == "银行"
