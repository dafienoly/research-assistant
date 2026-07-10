#!/usr/bin/env python3
"""
Tests for data_pipeline — batch_daily / batch_fina / batch_valuation.

Uses monkeypatching/mocking to avoid real Tushare API calls.
Tests cover:
  - batch_daily: file output, row counting, batching, error handling
  - batch_fina: file output, empty data handling
  - batch_valuation: output file naming, parameter passing
  - CLI handlers: argument parsing, universe loading
"""

from __future__ import annotations

import json
import sys
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd

# ── Path setup ──
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

import data_pipeline as data_pipeline_module
from data_pipeline import (
    batch_daily,
    batch_fina,
    batch_valuation,
    cmd_pull_daily,
    cmd_pull_fina,
    cmd_pull_valuation,
    DAILY_DIR,
    FINA_DIR,
    VALUATION_DIR,
    BATCH_SIZE,
    BATCH_SLEEP,
)


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def clean_normalized_dirs(tmp_path, monkeypatch):
    """Isolate every test from the real data/normalized directories."""
    daily_dir = tmp_path / "market"
    fina_dir = tmp_path / "fundamentals"
    valuation_dir = tmp_path / "valuation"
    fund_flow_dir = tmp_path / "fund_flow"
    etc_dir = tmp_path / "normalized"

    for directory in [daily_dir, fina_dir, valuation_dir, fund_flow_dir, etc_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    isolated_dirs = {
        "DAILY_DIR": daily_dir,
        "FINA_DIR": fina_dir,
        "VALUATION_DIR": valuation_dir,
        "FUND_FLOW_DIR": fund_flow_dir,
        "ETC_DIR": etc_dir,
    }
    for name, directory in isolated_dirs.items():
        monkeypatch.setattr(data_pipeline_module, name, directory)

    # Existing assertions import these constants directly, so point the test
    # module aliases at the same isolated paths as the production module.
    test_module = sys.modules[__name__]
    monkeypatch.setattr(test_module, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(test_module, "FINA_DIR", fina_dir)
    monkeypatch.setattr(test_module, "VALUATION_DIR", valuation_dir)
    yield


@pytest.fixture
def mock_market_provider(monkeypatch):
    """Mock TushareMarketProvider to return controlled DataFrames."""
    from data_pipeline import TushareMarketProvider

    mock_instance = MagicMock(spec=TushareMarketProvider)

    def make_daily_df(ts_code: str, n_rows: int = 10) -> pd.DataFrame:
        dates = pd.date_range(start="2026-01-05", periods=n_rows, freq="B")
        return pd.DataFrame({
            "ts_code": [ts_code] * n_rows,
            "trade_date": dates,
            "open": [10.0 + i for i in range(n_rows)],
            "high": [11.0 + i for i in range(n_rows)],
            "low": [9.0 + i for i in range(n_rows)],
            "close": [10.5 + i for i in range(n_rows)],
            "pre_close": [10.0 + i for i in range(n_rows)],
            "change": [0.5] * n_rows,
            "pct_chg": [5.0] * n_rows,
            "vol": [1_000_000] * n_rows,
            "amount": [10_000_000] * n_rows,
        })

    def make_basic_df(ts_code: str, n_rows: int = 10) -> pd.DataFrame:
        dates = pd.date_range(start="2026-01-05", periods=n_rows, freq="B")
        return pd.DataFrame({
            "ts_code": [ts_code] * n_rows,
            "trade_date": dates,
            "pe": [15.0] * n_rows,
            "pb": [2.0] * n_rows,
            "total_mv": [50_000_000_000] * n_rows,
            "circ_mv": [30_000_000_000] * n_rows,
            "turnover_rate": [2.5] * n_rows,
        })

    def mock_daily(ts_code="", start_date="", end_date="", trade_date=""):
        if "no_data" in ts_code:
            return pd.DataFrame()
        if "error_stock" in ts_code:
            raise RuntimeError("API error")
        return make_daily_df(ts_code)

    def mock_daily_basic(ts_code="", trade_date="", start_date="", end_date=""):
        if "no_data" in ts_code:
            return pd.DataFrame()
        if "error_stock" in ts_code:
            raise RuntimeError("API error")
        return make_basic_df(ts_code)

    mock_instance.daily.side_effect = mock_daily
    mock_instance.daily_basic.side_effect = mock_daily_basic

    def mock_get_market_provider():
        return mock_instance

    monkeypatch.setattr("data_pipeline._get_market_provider", mock_get_market_provider)
    return mock_instance


@pytest.fixture
def mock_fina_provider(monkeypatch):
    """Mock TushareFinaProvider to return controlled DataFrames."""
    from data_pipeline import TushareFinaProvider

    mock_instance = MagicMock(spec=TushareFinaProvider)

    def make_fina_df(ts_code: str, n_rows: int = 4) -> pd.DataFrame:
        # Use valid end-of-quarter dates (Feb has 28 days in 2026)
        periods = pd.to_datetime(["20260331", "20251231", "20250930"])
        return pd.DataFrame({
            "ts_code": [ts_code] * 3,
            "end_date": periods,
            "roe": [10.0] * 3,
            "eps": [1.5] * 3,
            "bps": [12.0] * 3,
            "gross_margin": [40.0] * 3,
            "net_margin": [20.0] * 3,
        })

    def mock_fina_indicator(ts_code="", start_date="", end_date="", period=""):
        if "no_data" in ts_code:
            return pd.DataFrame()
        if "error_stock" in ts_code:
            raise RuntimeError("API error")
        return make_fina_df(ts_code)

    mock_instance.fina_indicator.side_effect = mock_fina_indicator

    def mock_get_fina_provider():
        return mock_instance

    monkeypatch.setattr("data_pipeline._get_fina_provider", mock_get_fina_provider)
    return mock_instance


@pytest.fixture
def mock_universe_fresh(monkeypatch):
    """Mock universes.get_universe to return a controlled universe."""
    def mock_get_universe(name: str) -> dict[str, Any]:
        return {
            "name": name,
            "stocks": [
                {"ts_code": "688012.SH", "symbol": "688012", "name": "中微公司"},
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},
                {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台"},
            ],
        }
    monkeypatch.setattr("universes.get_universe", mock_get_universe)


# ═════════════════════════════════════════════════════════════════════════
# batch_daily 测试
# ═════════════════════════════════════════════════════════════════════════


class TestBatchDaily:
    def test_basic_batch(self, mock_market_provider, clean_normalized_dirs):
        codes = ["688012.SH", "000001.SZ"]
        result = batch_daily(codes, start="20260101", end="20260708")

        assert len(result) == 2
        assert result["688012.SH"] == 10
        assert result["000001.SZ"] == 10

        # 验证文件已写入
        assert (DAILY_DIR / "688012.SH.csv").exists()
        assert (DAILY_DIR / "000001.SZ.csv").exists()

        # 验证 CSV 可读
        df = pd.read_csv(DAILY_DIR / "688012.SH.csv", encoding="utf-8-sig")
        assert len(df) == 10
        assert "ts_code" in df.columns
        assert "trade_date" in df.columns

    def test_empty_data(self, mock_market_provider, clean_normalized_dirs):
        result = batch_daily(["no_data_stock"], start="20260101", end="20260708")
        assert result["no_data_stock"] == 0
        assert not (DAILY_DIR / "no_data_stock.csv").exists()

    def test_handles_errors(self, mock_market_provider, clean_normalized_dirs):
        result = batch_daily(["error_stock"], start="20260101", end="20260708")
        assert result["error_stock"] == -1  # -1 signals error

    def test_batch_size_triggers_batching(self, mock_market_provider, clean_normalized_dirs):
        """Verify that BATCH_SIZE splitting is triggered with many codes."""
        codes = [f"{str(i).zfill(6)}.SZ" for i in range(25)]  # 25 codes, 3 batches
        result = batch_daily(codes, start="20260101", end="20260708")

        assert len(result) == 25
        # All should succeed with mocked provider
        successful = [k for k, v in result.items() if v > 0]
        assert len(successful) == 25

    def test_empty_code_list(self, mock_market_provider, clean_normalized_dirs):
        result = batch_daily([], start="20260101", end="20260708")
        assert result == {}

    def test_provider_called_with_correct_params(self, mock_market_provider, clean_normalized_dirs):
        batch_daily(["688012.SH"], start="20200101", end="20260708")
        mock_market_provider.daily.assert_called_once_with(
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )


# ═════════════════════════════════════════════════════════════════════════
# batch_fina 测试
# ═════════════════════════════════════════════════════════════════════════


class TestBatchFina:
    def test_basic_batch(self, mock_fina_provider, clean_normalized_dirs):
        codes = ["688012.SH", "000001.SZ"]
        result = batch_fina(codes, start="20240101", end="20260708")

        assert len(result) == 2
        assert result["688012.SH"] == 3
        assert result["000001.SZ"] == 3

        # 验证文件已写入
        assert (FINA_DIR / "688012.SH.csv").exists()
        assert (FINA_DIR / "000001.SZ.csv").exists()

        df = pd.read_csv(FINA_DIR / "688012.SH.csv", encoding="utf-8-sig")
        assert len(df) == 3
        assert "roe" in df.columns

    def test_empty_data(self, mock_fina_provider, clean_normalized_dirs):
        result = batch_fina(["no_data_stock"], start="20240101", end="20260708")
        assert result["no_data_stock"] == 0

    def test_handles_errors(self, mock_fina_provider, clean_normalized_dirs):
        result = batch_fina(["error_stock"], start="20240101", end="20260708")
        assert result["error_stock"] == -1

    def test_provider_called_with_correct_params(self, mock_fina_provider, clean_normalized_dirs):
        batch_fina(["688012.SH"], start="20200101", end="20260708")
        mock_fina_provider.fina_indicator.assert_called_once_with(
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )


# ═════════════════════════════════════════════════════════════════════════
# batch_valuation 测试
# ═════════════════════════════════════════════════════════════════════════


class TestBatchValuation:
    def test_basic_batch(self, mock_market_provider, clean_normalized_dirs):
        codes = ["688012.SH", "000001.SZ"]
        result = batch_valuation(codes, start="20260101", end="20260708")

        assert len(result) == 2
        assert result["688012.SH"] == 10

        # 验证文件已写入 (valuation_ 前缀)
        assert (VALUATION_DIR / "valuation_688012.SH.csv").exists()
        assert (VALUATION_DIR / "valuation_000001.SZ.csv").exists()

        df = pd.read_csv(VALUATION_DIR / "valuation_688012.SH.csv", encoding="utf-8-sig")
        assert len(df) == 10
        assert "pe" in df.columns

    def test_empty_data(self, mock_market_provider, clean_normalized_dirs):
        result = batch_valuation(["no_data_stock"], start="20260101", end="20260708")
        assert result["no_data_stock"] == 0

    def test_handles_errors(self, mock_market_provider, clean_normalized_dirs):
        result = batch_valuation(["error_stock"], start="20260101", end="20260708")
        assert result["error_stock"] == -1

    def test_provider_called_with_correct_params(self, mock_market_provider, clean_normalized_dirs):
        batch_valuation(["688012.SH"], start="20200101", end="20260708")
        mock_market_provider.daily_basic.assert_called_once_with(
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )


# ═════════════════════════════════════════════════════════════════════════
# CLI Handler 测试
# ═════════════════════════════════════════════════════════════════════════


class TestCLIHandlers:
    def test_cmd_pull_daily_with_universe(
        self, mock_market_provider, mock_universe_fresh, clean_normalized_dirs, capsys
    ):
        cmd_pull_daily(["--start", "20260101", "--end", "20260708", "--universe", "U0"])
        captured = capsys.readouterr()
        assert "688012.SH" in captured.out or "日线" in captured.out

    def test_cmd_pull_daily_with_codes(
        self, mock_market_provider, mock_universe_fresh, clean_normalized_dirs, capsys
    ):
        cmd_pull_daily(["--codes", "688012.SH,000001.SZ"])
        captured = capsys.readouterr()
        assert "688012.SH" in captured.out or "日线" in captured.out

    def test_cmd_pull_fina_with_universe(
        self, mock_fina_provider, mock_universe_fresh, clean_normalized_dirs, capsys
    ):
        cmd_pull_fina(["--start", "20240101", "--end", "20260708", "--universe", "U0"])
        captured = capsys.readouterr()
        assert "财务" in captured.out

    def test_cmd_pull_fina_with_codes(
        self, mock_fina_provider, mock_universe_fresh, clean_normalized_dirs, capsys
    ):
        cmd_pull_fina(["--codes", "688012.SH"])
        captured = capsys.readouterr()
        assert "财务" in captured.out or "688012" in captured.out

    def test_cmd_pull_valuation_with_universe(
        self, mock_market_provider, mock_universe_fresh, clean_normalized_dirs, capsys
    ):
        cmd_pull_valuation(["--start", "20260101", "--end", "20260708", "--universe", "U0"])
        captured = capsys.readouterr()
        assert "估值" in captured.out

    def test_cmd_pull_valuation_with_codes(
        self, mock_market_provider, mock_universe_fresh, clean_normalized_dirs, capsys
    ):
        cmd_pull_valuation(["--codes", "000001.SZ"])
        captured = capsys.readouterr()
        assert "估值" in captured.out or "000001" in captured.out


class TestGapReport:
    def test_partial_concept_and_industry_are_reported_as_gaps(
        self, monkeypatch, clean_normalized_dirs, capsys
    ):
        ts_client = MagicMock()
        ts_client._query.return_value = pd.DataFrame(
            {"ts_code": [f"{i:06d}.SZ" for i in range(100)]}
        )
        monkeypatch.setattr(data_pipeline_module, "_get_ts_client", lambda: ts_client)
        monkeypatch.setattr(data_pipeline_module, "_get_trade_days", lambda _start: [])

        concept_path = data_pipeline_module.ETC_DIR / "concept" / "concept_list.csv"
        industry_path = data_pipeline_module.ETC_DIR / "industry" / "industry_list.csv"
        concept_path.parent.mkdir(parents=True, exist_ok=True)
        industry_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"code": range(16)}).to_csv(concept_path, index=False)
        pd.DataFrame({"code": range(1)}).to_csv(industry_path, index=False)

        result = data_pipeline_module.gap_report_and_plan()
        captured = capsys.readouterr()
        by_type = {item["type"]: item for item in result["gaps"]}

        assert by_type["概念板块"] == {
            "type": "概念板块",
            "have": 16,
            "need": 380,
            "gap": 364,
            "status": "PARTIAL",
        }
        assert by_type["行业分类"] == {
            "type": "行业分类",
            "have": 1,
            "need": 80,
            "gap": 79,
            "status": "PARTIAL",
        }
        assert "⚠️ 概念板块" in captured.out
        assert "⚠️ 行业分类" in captured.out

    def test_missing_stock_baseline_is_unknown_not_complete(
        self, monkeypatch, clean_normalized_dirs, capsys
    ):
        ts_client = MagicMock()
        ts_client._query.return_value = pd.DataFrame()
        monkeypatch.setattr(data_pipeline_module, "_get_ts_client", lambda: ts_client)
        monkeypatch.setattr(data_pipeline_module, "_get_trade_days", lambda _start: [])

        result = data_pipeline_module.gap_report_and_plan()
        captured = capsys.readouterr()

        for item in result["gaps"][:4]:
            assert item["need"] == "UNKNOWN"
            assert item["gap"] == "UNKNOWN"
            assert item["status"] == "UNKNOWN"
        assert "✅ 日线 kline" not in captured.out
        assert "⚠️ 日线 kline" in captured.out
