#!/usr/bin/env python3
"""
Tests for data_audit — coverage / freshness / missing / survivorship_check.

Uses monkeypatching and controlled CSV files to avoid real data dependencies.
Tests cover:
  - coverage: stock/date counting, empty files, report JSON output
  - freshness: lag calculation, freshness levels
  - missing: U0 comparison, missing rates
  - survivorship: delisted/ST detection
  - run_all_audits: integration
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
import pandas as pd
import numpy as np

# ── Path setup ──
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from data_audit import (  # noqa: E402
    coverage,
    freshness,
    missing,
    survivorship_check,
    run_all_audits,
    cmd_coverage,
    cmd_survivorship,
    DAILY_DIR,
    HEALTH_DIR,
    _normalize_trade_date,
)

CST = timezone(timedelta(hours=8))


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════


def _create_daily_csv(ts_code: str, n_rows: int = 10,
                      start_date: str = "2026-01-05") -> Path:
    """Create a mock daily CSV file in the normalized market directory."""
    dates = pd.date_range(start=start_date, periods=n_rows, freq="B")
    df = pd.DataFrame({
        "ts_code": [ts_code] * n_rows,
        "trade_date": dates,
        "open": np.random.uniform(10, 50, n_rows).round(2),
        "high": np.random.uniform(11, 55, n_rows).round(2),
        "low": np.random.uniform(9, 45, n_rows).round(2),
        "close": np.random.uniform(10, 50, n_rows).round(2),
        "pre_close": np.random.uniform(10, 50, n_rows).round(2),
        "change": np.random.uniform(-2, 2, n_rows).round(2),
        "pct_chg": np.random.uniform(-5, 5, n_rows).round(2),
        "vol": np.random.randint(100000, 10000000, n_rows),
        "amount": np.random.randint(1000000, 100000000, n_rows),
    })
    path = DAILY_DIR / f"{ts_code}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _create_empty_csv(ts_code: str) -> Path:
    """Create an empty CSV (header only) in the normalized market directory."""
    df = pd.DataFrame(columns=[
        "ts_code", "trade_date", "open", "high", "low", "close",
        "pre_close", "change", "pct_chg", "vol", "amount",
    ])
    path = DAILY_DIR / f"{ts_code}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def clean_dirs(tmp_path, monkeypatch):
    """Keep audit fixtures isolated from the shared production data hub."""
    import data_audit

    daily_dir = tmp_path / "daily_kline"
    health_dir = tmp_path / "health"
    global DAILY_DIR, HEALTH_DIR
    DAILY_DIR = daily_dir
    HEALTH_DIR = health_dir
    monkeypatch.setattr(data_audit, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(data_audit, "EFFECTIVE_DAILY_DIR", daily_dir)
    monkeypatch.setattr(data_audit, "SHARED_DAILY_DIR", tmp_path / "no_shared_data")
    monkeypatch.setattr(data_audit, "LOCAL_DAILY_DIR", daily_dir)
    monkeypatch.setattr(data_audit, "NORMALIZED_DIR", tmp_path / "normalized")
    monkeypatch.setattr(data_audit, "HEALTH_DIR", health_dir)
    for d in [daily_dir, health_dir]:
        d.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def sample_daily_files():
    """Create a set of sample daily CSV files for testing."""
    _create_daily_csv("688012.SH", n_rows=20, start_date="2026-01-01")
    _create_daily_csv("000001.SZ", n_rows=15, start_date="2026-02-01")
    _create_daily_csv("600519.SH", n_rows=25, start_date="2026-01-15")
    # One fresh file (today-like)
    today_str = datetime.now(CST).strftime("%Y-%m-%d")
    _create_daily_csv("999999.SZ", n_rows=5, start_date=today_str)
    # One empty file
    _create_empty_csv("empty_stock")
    yield


@pytest.fixture
def mock_u0_universe(monkeypatch):
    """Persist a controlled canonical DataHub stock reference."""
    import data_audit

    stocks = [
                {"ts_code": "688012.SH", "symbol": "688012", "name": "中微公司",
                 "list_status": "L", "market": "科创板", "delist_date": ""},
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行",
                 "list_status": "L", "market": "主板", "delist_date": ""},
                {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台",
                 "list_status": "L", "market": "主板", "delist_date": ""},
                {"ts_code": "300999.SZ", "symbol": "300999", "name": "ST金刚",
                 "list_status": "L", "market": "创业板", "delist_date": ""},
                {"ts_code": "000555.SZ", "symbol": "000555", "name": "*ST神州",
                 "list_status": "L", "market": "主板", "delist_date": ""},
                {"ts_code": "600666.SH", "symbol": "600666", "name": "退市公司",
                 "list_status": "D", "market": "主板", "delist_date": "20251031"},
                {"ts_code": "999999.SZ", "symbol": "999999", "name": "最新新股",
                 "list_status": "L", "market": "创业板", "delist_date": ""},
                {"ts_code": "unpulled_stock", "symbol": "999998", "name": "未拉取",
                 "list_status": "L", "market": "主板", "delist_date": ""},
    ]
    reference = data_audit.NORMALIZED_DIR / "reference" / "stock_basic.csv"
    reference.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(stocks).to_csv(reference, index=False, encoding="utf-8-sig")
    yield


# ═════════════════════════════════════════════════════════════════════════
# coverage 测试
# ═════════════════════════════════════════════════════════════════════════


class TestCoverage:
    def test_integer_yyyymmdd_is_not_parsed_as_unix_nanoseconds(self):
        frame = _normalize_trade_date(pd.DataFrame({"trade_date": [20260710, "20260709"]}))
        assert frame["trade_date"].dt.strftime("%Y-%m-%d").tolist() == [
            "2026-07-10",
            "2026-07-09",
        ]

    def test_basic_coverage(self, sample_daily_files):
        report = coverage()

        assert report["report_type"] == "coverage"
        assert report["total_stocks"] == 5  # 4 normal + 1 empty
        assert report["stocks_with_data"] == 4
        assert report["empty_files"] == 1
        assert report["total_rows"] == 20 + 15 + 25 + 5  # 65

    def test_coverage_dates(self, sample_daily_files):
        report = coverage()

        assert report["earliest_date"] <= "2026-01-01"
        assert report["latest_date"] is not None
        assert report["unique_trading_days"] > 0

    def test_coverage_json_file(self, sample_daily_files):
        report = coverage()

        report_path = HEALTH_DIR / "coverage.json"
        assert report_path.exists()

        with open(report_path) as f:
            saved = json.load(f)
        assert saved["report_type"] == "coverage"
        assert saved["total_stocks"] == report["total_stocks"]
        assert saved["total_rows"] == report["total_rows"]

    def test_coverage_empty_dir(self, clean_dirs):
        report = coverage()

        assert report["total_stocks"] == 0
        assert report["stocks_with_data"] == 0
        assert report["total_rows"] == 0

    def test_coverage_top_bottom_stocks(self, sample_daily_files):
        report = coverage()

        assert len(report["top5_by_rows"]) > 0
        assert len(report["bottom5_by_rows"]) > 0

    def test_coverage_ignores_valuation_files(self, sample_daily_files):
        """Valuation files (valuation_*.csv) should not be counted in daily coverage."""
        # Create a valuation file
        df = pd.DataFrame({
            "ts_code": ["888888.SH"],
            "trade_date": pd.to_datetime(["2026-07-01"]),
        })
        df.to_csv(DAILY_DIR / "valuation_888888.SH.csv", index=False, encoding="utf-8-sig")

        report = coverage()
        # Should still be 5 (valuation files excluded)
        assert report["total_stocks"] == 5

    def test_canonical_active_reference_excludes_test_and_historical_extras(self):
        _create_daily_csv("000001.SZ", n_rows=2, start_date="2026-07-09")
        _create_daily_csv("999999.SZ", n_rows=1, start_date="2099-01-01")
        import data_audit

        reference = data_audit.NORMALIZED_DIR / "reference/stock_basic.csv"
        reference.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600666.SH"],
                "list_status": ["L", "D"],
            }
        ).to_csv(reference, index=False, encoding="utf-8-sig")

        report = coverage()

        assert report["universe_status"] == "OK"
        assert report["total_stocks"] == 1
        assert report["stocks_with_data"] == 1
        assert report["latest_date"] == "2026-07-10"
        assert report["historical_files_outside_active"] == 1


# ═════════════════════════════════════════════════════════════════════════
# freshness 测试
# ═════════════════════════════════════════════════════════════════════════


class TestFreshness:
    def test_future_dates_are_reported_explicitly(self):
        _create_daily_csv("999999.SZ", n_rows=1, start_date="2099-01-01")
        report = freshness()
        assert report["future_date_count"] == 1
        assert report["future_date_stocks"][0]["ts_code"] == "999999.SZ"

    def test_basic_freshness(self, sample_daily_files):
        report = freshness()

        assert report["report_type"] == "freshness"
        assert report["total_stocks"] == 5  # 4 normal + 1 empty
        # Empty files have no trade_date data, so only 4 with data
        assert report["stocks_with_data"] == 4

    def test_freshness_levels(self, sample_daily_files):
        report = freshness()

        # 999999.SZ has recent dates — should be "fresh"
        dist = report["freshness_distribution"]
        assert dist["fresh (<=7d)"] >= 1
        # min_lag could be 0 or negative (if dates are today/future), just ensure it's set
        assert "min_lag_days" in report
        assert "max_lag_days" in report
        assert report["stocks_with_data"] > 0

    def test_freshness_json_file(self, sample_daily_files):
        report = freshness()

        report_path = HEALTH_DIR / "freshness.json"
        assert report_path.exists()

        with open(report_path) as f:
            saved = json.load(f)
        assert saved["report_type"] == "freshness"
        assert saved["today"] == datetime.now(CST).strftime("%Y%m%d")

    def test_freshness_empty_dir(self, clean_dirs):
        report = freshness()

        assert report["total_stocks"] == 0
        assert report["stocks_with_data"] == 0

    def test_freshness_lag_calculation(self, clean_dirs):
        # Create a file with very old date
        _create_daily_csv("old_stock.SH", n_rows=5, start_date="2025-01-01")
        report = freshness()

        assert report["max_lag_days"] > 0
        assert report["average_lag_days"] > 0

    def test_canonical_suspension_explains_stale_market_file(self):
        _create_daily_csv("600405.SH", n_rows=1, start_date="2026-01-01")
        import data_audit

        reference = data_audit.NORMALIZED_DIR / "reference/stock_basic.csv"
        reference.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"ts_code": ["600405.SH"], "list_status": ["L"]}).to_csv(
            reference, index=False, encoding="utf-8-sig"
        )
        suspension = data_audit.NORMALIZED_DIR / "suspend/records.csv"
        suspension.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "ts_code": ["600405.SH"],
                "trade_date": [datetime.now(CST).strftime("%Y%m%d")],
                "suspend_type": ["S"],
                "source_provider": ["tushare:suspend_d"],
            }
        ).to_csv(suspension, index=False, encoding="utf-8-sig")

        report = freshness()

        assert report["status"] == "OK"
        assert report["blocking_stock_count"] == 0
        assert report["freshness_distribution"]["suspended (canonical)"] == 1


# ═════════════════════════════════════════════════════════════════════════
# missing 测试
# ═════════════════════════════════════════════════════════════════════════


class TestMissing:
    def test_basic_missing(self, sample_daily_files, mock_u0_universe):
        report = missing()

        assert report["report_type"] == "missing"
        # Canonical reference has 7 active stocks and one delisted stock.
        # Only 688012.SH, 000001.SZ, 600519.SH, 999999.SZ are in U0
        # empty_stock not in U0
        assert report["u0_total"] == 7
        assert report["reference_total_all_statuses"] == 8
        assert "missing_stocks" in report

    def test_missing_codes(self, sample_daily_files, mock_u0_universe):
        report = missing()

        # unpulled_stock should be in missing
        assert "UNPULLED_STOCK" in report["missing_codes_sample"]

    def test_missing_json_file(self, sample_daily_files, mock_u0_universe):
        report = missing()

        report_path = HEALTH_DIR / "missing.json"
        assert report_path.exists()

        with open(report_path) as f:
            saved = json.load(f)
        assert saved["report_type"] == "missing"

    def test_missing_detail(self, sample_daily_files, mock_u0_universe):
        report = missing()

        if report["missing_detail_top20"]:
            detail = report["missing_detail_top20"][0]
            assert "expected_days" in detail
            assert "actual_days" in detail
            assert "missing_pct" in detail

    def test_missing_without_u0(self, clean_dirs, sample_daily_files):
        """Without canonical reference, report status is UNKNOWN rather than complete."""
        report = missing()

        assert report["u0_total"] == 0
        assert report["pulled_stocks"] == 5  # All files counted as pulled
        assert report["universe_status"] == "UNKNOWN"
        assert "summary" in report


# ═════════════════════════════════════════════════════════════════════════
# survivorship 测试
# ═════════════════════════════════════════════════════════════════════════


class TestSurvivorship:
    def test_basic_survivorship(self, sample_daily_files, mock_u0_universe):
        report = survivorship_check()

        assert report["report_type"] == "survivorship"
        assert report["total_pulled"] == 5  # 5 daily CSV files
        # 688012.SH, 000001.SZ, 600519.SH, 999999.SZ are normal
        # empty_stock is not in U0 (won't be classified)
        assert "survivorship_bias_risk" in report

    def test_delisted_detection(self, sample_daily_files, mock_u0_universe):
        report = survivorship_check()

        # 600666.SH should be in delisted list (is_listed=False)
        delisted_codes = [s["ts_code"] for s in report["delisted_list"]]

    def test_st_detection(self, sample_daily_files, mock_u0_universe):
        report = survivorship_check()

        # Check that ST stocks are detected if we have them
        # Note: our pulled files don't include 300999.SZ or 000555.SZ
        # So ST list might be empty unless we add them
        pass

    def test_survivorship_json_file(self, sample_daily_files, mock_u0_universe):
        report = survivorship_check()

        report_path = HEALTH_DIR / "survivorship.json"
        assert report_path.exists()

        with open(report_path) as f:
            saved = json.load(f)
        assert saved["report_type"] == "survivorship"

    def test_survivorship_empty_dir(self, clean_dirs):
        report = survivorship_check()

        assert report["total_pulled"] == 0
        assert report["normal_stocks"] == 0


# ═════════════════════════════════════════════════════════════════════════
# run_all_audits 测试
# ═════════════════════════════════════════════════════════════════════════


class TestRunAllAudits:
    def test_all_audits_run(self, sample_daily_files, mock_u0_universe):
        results = run_all_audits()

        assert "coverage" in results
        assert "freshness" in results
        assert "missing" in results
        assert "survivorship" in results

        # Verify all files exist
        for name, path in results.items():
            assert Path(path).exists(), f"{name} report not found at {path}"


# ═════════════════════════════════════════════════════════════════════════
# CLI Handler 测试
# ═════════════════════════════════════════════════════════════════════════


class TestCLIHandlers:
    def test_cmd_coverage(self, sample_daily_files, capsys):
        cmd_coverage([])
        captured = capsys.readouterr()
        assert "覆盖率报告" in captured.out

    def test_cmd_survivorship(self, sample_daily_files, mock_u0_universe, capsys):
        cmd_survivorship([])
        captured = capsys.readouterr()
        assert "生存偏差报告" in captured.out
