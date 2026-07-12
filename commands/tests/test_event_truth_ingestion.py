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


def test_vnext_event_truth_rejects_tampered_canonical_file(tmp_path):
    EventTruthIngestion(tmp_path, client=Client()).fetch(["510300.SH"], "20260710", "20260710")
    output = tmp_path / "data/normalized/events/event_truth/510300.SH.csv"
    output.write_text(output.read_text(encoding="utf-8-sig") + "\n", encoding="utf-8-sig")
    assert load_event_truth(tmp_path, "510300.SH").empty


def test_failed_refresh_preserves_existing_event_truth(tmp_path):
    output = tmp_path / "data/normalized/events/event_truth/510300.SH.csv"
    output.parent.mkdir(parents=True)
    original = pd.DataFrame([{
        "trade_date": "20260710", "up_limit": 5, "down_limit": 4,
        "adj_factor": 1.2, "source_provider": "tushare", "observed_at": "old",
    }])
    original.to_csv(output, index=False, encoding="utf-8-sig")
    before = output.read_bytes()

    class FailedClient:
        def _query(self, _api_name, **_params):
            raise RuntimeError("provider unavailable")

    manifest = EventTruthIngestion(tmp_path, client=FailedClient()).fetch(
        ["510300.SH"], "20260710", "20260710",
    )

    assert output.read_bytes() == before
    assert manifest["run_status"] == "COMPLETE"
    assert manifest["results"][0]["write_status"] == "PRESERVED"
    assert len(manifest["results"][0]["errors"]) == 4


def test_partial_refresh_keeps_old_non_null_fields(tmp_path):
    output = tmp_path / "data/normalized/events/event_truth/510300.SH.csv"
    output.parent.mkdir(parents=True)
    pd.DataFrame([{
        "trade_date": "20260710", "up_limit": 5, "down_limit": 4,
        "adj_factor": 1.1, "cash_div": 0.3, "source_provider": "tushare", "observed_at": "old",
    }]).to_csv(output, index=False, encoding="utf-8-sig")

    EventTruthIngestion(tmp_path, client=Client()).fetch(["510300.SH"], "20260710", "20260710")
    frame = pd.read_csv(output, encoding="utf-8-sig")

    assert float(frame.iloc[0]["adj_factor"]) == 1.2
    assert float(frame.iloc[0]["cash_div"]) == 0.3
