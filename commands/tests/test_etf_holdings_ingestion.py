import pandas as pd

import data_pipeline


class Client:
    def __init__(self, empty: bool = False):
        self.empty = empty

    def _query(self, _api, ts_code):
        if self.empty:
            return pd.DataFrame()
        return pd.DataFrame([{
            "symbol": "688012.SH", "stk_mkv_ratio": 8.5,
            "end_date": "20250630", "ann_date": "20250720",
        }])


def test_weekly_etf_holdings_publish_to_normalized_datahub(tmp_path, monkeypatch):
    monkeypatch.setattr(data_pipeline, "NORMALIZED_DIR", tmp_path / "normalized")
    monkeypatch.setattr(data_pipeline, "_get_ts_client", lambda: Client())

    result = data_pipeline.incremental_etf_holdings()

    output = tmp_path / "normalized/etf_holdings/holdings.csv"
    assert result["status"] == "OK"
    assert output.exists()
    assert output.with_suffix(".manifest.json").exists()


def test_empty_etf_holdings_response_preserves_existing_snapshot(tmp_path, monkeypatch):
    output = tmp_path / "normalized/etf_holdings/holdings.csv"
    output.parent.mkdir(parents=True)
    output.write_text("etf_code,symbol,stk_mkv_ratio\n588710.SH,688012.SH,8.5\n", encoding="utf-8")
    original = output.read_bytes()
    monkeypatch.setattr(data_pipeline, "NORMALIZED_DIR", tmp_path / "normalized")
    monkeypatch.setattr(data_pipeline, "_get_ts_client", lambda: Client(empty=True))

    result = data_pipeline.incremental_etf_holdings()

    assert result["status"] == "MISSING"
    assert output.read_bytes() == original
