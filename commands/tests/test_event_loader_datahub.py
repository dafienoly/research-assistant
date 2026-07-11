import json
from pathlib import Path

import pandas as pd

import factor_lab.alpha.event_loader as loader


def _partition(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts_code": "688012.SH", "event_dataset": "share_float", "event_date": "20260710", "payload": json.dumps({"float_date": "20260710"}), "source_provider": "tushare", "observed_at": "2026-07-12T00:00:00+08:00"},
        {"ts_code": "688012.SH", "event_dataset": "repurchase", "event_date": "20260710", "payload": json.dumps({"proc": "实施"}), "source_provider": "tushare", "observed_at": "2026-07-12T00:00:00+08:00"},
        {"ts_code": "688012.SH", "event_dataset": "dividend", "event_date": "20260710", "payload": json.dumps({"cash_div_tax": 0.3, "ex_date": "20260710"}), "source_provider": "tushare", "observed_at": "2026-07-12T00:00:00+08:00"},
        {"ts_code": "688012.SH", "event_dataset": "forecast", "event_date": "20260710", "payload": json.dumps({"type": "预增"}), "source_provider": "tushare", "observed_at": "2026-07-12T00:00:00+08:00"},
    ]
    pd.DataFrame(rows).to_csv(root / "688012.SH.csv", index=False)


def test_event_loader_reads_only_canonical_partitions(monkeypatch, tmp_path) -> None:
    _partition(tmp_path)
    monkeypatch.setattr(loader, "CORPORATE_EVENT_ROOT", tmp_path)
    events = loader.get_event_data(["688012"])
    assert all(events[f"has_{name}"] for name in ("lockup", "buyback", "dividend", "forecast"))
    assert events["dividend"].iloc[0]["dividend_amount"] == 0.3
    assert events["forecast"].iloc[0]["forecast_type_code"] == 1.0


def test_event_loader_reports_missing_forecast_without_fallback(monkeypatch, tmp_path) -> None:
    _partition(tmp_path)
    frame = pd.read_csv(tmp_path / "688012.SH.csv")
    frame[frame["event_dataset"] != "forecast"].to_csv(tmp_path / "688012.SH.csv", index=False)
    monkeypatch.setattr(loader, "CORPORATE_EVENT_ROOT", tmp_path)
    status = loader.event_data_status()
    assert status["status"] == "PARTIAL"
    assert status["datasets"]["forecast"]["status"] == "MISSING"


def test_event_loader_has_no_legacy_event_csv_fallback() -> None:
    source = Path(loader.__file__).read_text(encoding="utf-8")
    for forbidden in ("announcements_extracted.csv", "adjust_factor.csv", "forecast_report.csv"):
        assert forbidden not in source
    assert "CORPORATE_EVENT_ROOT" in source
