from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factor_lab.datahub_ingestion.suspensions import SuspensionIngestion


class FakeClient:
    def _query(self, _api_name: str, **params):
        if params["ts_code"] == "600405.SH":
            return pd.DataFrame(
                {"ts_code": ["600405.SH"], "trade_date": [params["end_date"]], "suspend_type": ["S"]}
            )
        return pd.DataFrame()


def test_suspension_ingestion_preserves_evidence_and_reports_unexplained(tmp_path: Path) -> None:
    health = tmp_path / "data/audit/health/freshness.json"
    health.parent.mkdir(parents=True)
    health.write_text(
        json.dumps(
            {
                "as_of_open_date": "2026-07-10",
                "stale_stocks": [
                    {"ts_code": "600405.SH", "latest_date": "2026-07-03"},
                    {"ts_code": "000001.SZ", "latest_date": "2026-07-02"},
                ],
                "old_stocks": [],
                "ancient_stocks": [],
            }
        ),
        encoding="utf-8",
    )
    ingestion = SuspensionIngestion(tmp_path, FakeClient())

    result = ingestion.refresh_from_health()

    assert result["status"] == "PARTIAL"
    assert result["explained_suspensions"] == 1
    assert result["unexplained_symbols"] == ["000001.SZ"]
    records = pd.read_csv(tmp_path / "data/normalized/suspend/records.csv", encoding="utf-8-sig")
    assert records.loc[0, "source_provider"] == "tushare:suspend_d"
    assert records.loc[0, "trade_date"] == 20260710


def test_suspension_ingestion_merges_without_dropping_history(tmp_path: Path) -> None:
    health = tmp_path / "data/audit/health/freshness.json"
    health.parent.mkdir(parents=True)
    health.write_text(
        json.dumps(
            {
                "as_of_open_date": "2026-07-10",
                "stale_stocks": [{"ts_code": "600405.SH", "latest_date": "2026-07-03"}],
            }
        ),
        encoding="utf-8",
    )
    records = tmp_path / "data/normalized/suspend/records.csv"
    records.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "ts_code": ["600405.SH"],
            "trade_date": ["20260709"],
            "suspend_type": ["S"],
            "source_provider": ["tushare:suspend_d"],
            "observed_at": ["earlier"],
        }
    ).to_csv(records, index=False, encoding="utf-8-sig")

    SuspensionIngestion(tmp_path, FakeClient()).refresh_from_health()

    merged = pd.read_csv(records, encoding="utf-8-sig", dtype={"trade_date": "string"})
    assert merged["trade_date"].tolist() == ["20260709", "20260710"]
