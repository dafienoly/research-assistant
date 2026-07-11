from __future__ import annotations

import pandas as pd

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion
from factor_lab.vnext.event_truth_sources import load_event_truth


class Client:
    def _query(self, api_name, **_params):
        if api_name == "stk_limit":
            return pd.DataFrame([{"ts_code": "510300.SH", "trade_date": "20260710", "up_limit": 5, "down_limit": 4}])
        if api_name == "fund_adj":
            return pd.DataFrame([{"ts_code": "510300.SH", "trade_date": "20260710", "adj_factor": 1.2}])
        return pd.DataFrame()


def test_ingestion_owns_provider_call_and_vnext_only_reads_canonical_output(tmp_path):
    manifest = EventTruthIngestion(tmp_path, client=Client()).fetch(["510300.SH"], "20260710", "20260710")
    assert manifest["status"] == "OK"
    assert "data/normalized/events/event_truth" in manifest["results"][0]["path"]
    frame = load_event_truth(tmp_path, "510300.SH")
    assert float(frame.iloc[0]["up_limit"]) == 5
    assert float(frame.iloc[0]["adj_factor"]) == 1.2
