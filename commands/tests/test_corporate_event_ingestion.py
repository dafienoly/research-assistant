from __future__ import annotations

import json

import pandas as pd
import pytest

from factor_lab.datahub_ingestion.corporate_events import CorporateEventIngestion
from factor_lab.semiconductor_events import SemiconductorEventEngine


class Client:
    def _query(self, api_name, **_params):
        if api_name == "forecast":
            return pd.DataFrame([{"ann_date": "20260710", "type": "1", "p_change_min": 20}])
        if api_name == "repurchase":
            return pd.DataFrame([{"ann_date": "20260710", "amount": 80_000_000}])
        return pd.DataFrame()


def test_corporate_ingestion_owns_provider_and_publishes_long_events(tmp_path):
    manifest = CorporateEventIngestion(tmp_path, Client()).fetch(["688012.SH"], "20260701", "20260711")
    output = tmp_path / "data/normalized/events/corporate_events/688012.SH.csv"
    frame = pd.read_csv(output, encoding="utf-8-sig")

    assert manifest["results"][0]["status"] == "OK"
    assert set(frame["event_dataset"]) == {"forecast", "repurchase"}
    assert json.loads(frame.iloc[0]["payload"])


def test_semiconductor_engine_reads_canonical_corporate_events(tmp_path, monkeypatch):
    root = tmp_path / "normalized/events/corporate_events"
    root.mkdir(parents=True)
    pd.DataFrame([{
        "ts_code": "688012.SH", "event_dataset": "forecast", "event_date": "20260710",
        "payload": json.dumps({"type": "1"}), "source_provider": "tushare",
        "observed_at": "2026-07-10T16:00:00+08:00",
    }]).to_csv(root / "688012.SH.csv", index=False)
    import factor_lab.semiconductor_events as module
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    engine = SemiconductorEventEngine(["688012"])
    engine._trade_cal = pd.DataFrame({"date": pd.to_datetime(["2026-07-10"]), "is_open": [1]})

    events = engine.load_all_events("20260701", "20260711", include_csv=False)

    assert len(events) == 1
    assert events[0].event_type == "业绩预告"
    assert events[0].event_source == "datahub_corporate_events"


def test_legacy_provider_methods_fail_closed():
    engine = SemiconductorEventEngine(["688012"])
    with pytest.raises(RuntimeError, match="CorporateEventIngestion"):
        engine._fetch_forecast_events()
    with pytest.raises(RuntimeError, match="CorporateEventIngestion"):
        engine._fetch_holdertrade_events()
