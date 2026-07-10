import os
from datetime import datetime

from factor_lab.vnext.service import VNextService


def test_service_missing_component_is_explicit(tmp_path):
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.component("regime", "2026-07-10")
    assert result["status"] == "MISSING"
    assert result["missing_evidence"]


def test_data_health_does_not_count_valuation_files_as_daily(tmp_path):
    market = tmp_path / "data" / "normalized" / "market"
    market.mkdir(parents=True)
    (market / "600000.SH.csv").write_text("trade_date,close\n20260710,10\n", encoding="utf-8")
    (market / "valuation_600000.SH.csv").write_text("trade_date,pe\n20260710,10\n", encoding="utf-8")
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.build_data_health("2026-07-10")
    daily = next(item for item in result["sources"] if item["source"] == "Tushare日线")
    valuation = next(item for item in result["sources"] if item["source"] == "Tushare估值")
    assert daily["records_or_files"] == 1
    assert valuation["records_or_files"] == 1
    assert valuation["coverage_ratio"] == 1.0


def test_data_health_marks_incomplete_directory_coverage_partial(tmp_path):
    market = tmp_path / "data" / "normalized" / "market"
    flow = tmp_path / "data" / "normalized" / "fund_flow"
    market.mkdir(parents=True)
    flow.mkdir(parents=True)
    for index in range(10):
        (market / f"{index:06d}.SH.csv").write_text("trade_date,close\n20260710,10\n", encoding="utf-8")
    for index in range(5):
        (flow / f"{index:06d}.SH.csv").write_text("trade_date,buy_sm_amount\n20260710,1\n", encoding="utf-8")
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.build_data_health("2026-07-10")
    fund_flow = next(item for item in result["sources"] if item["source"] == "Tushare资金流")
    assert fund_flow["status"] == "PARTIAL"
    assert fund_flow["expected_files"] == 10
    assert fund_flow["coverage_ratio"] == 0.5


def test_data_health_marks_old_directory_files_stale(tmp_path):
    market = tmp_path / "data" / "normalized" / "market"
    market.mkdir(parents=True)
    path = market / "600000.SH.csv"
    path.write_text("trade_date,close\n20260101,10\n", encoding="utf-8")
    stale_epoch = datetime(2026, 1, 1).timestamp()
    os.utime(path, (stale_epoch, stale_epoch))
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    result = service.build_data_health("2026-07-10")
    daily = next(item for item in result["sources"] if item["source"] == "Tushare日线")
    assert daily["status"] == "STALE"
    assert daily["message"].startswith("age_days=")
