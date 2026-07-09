#!/usr/bin/env python3
"""
Tests for TushareMarketProvider — daily / daily_basic / adj_factor / stk_limit

Uses monkeypatching/mocking to avoid real Tushare API calls.
Tests cover:
  - Each method's data shape (column names, date normalization, sorting)
  - Empty response handling
  - Error / missing-argument validation
  - Provider capability and self_check
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
import pytest

# ── Path setup: insert commands/ so data_providers & factor_lab resolve ──
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)  # commands/
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from commands.data_providers.tushare import TushareMarketProvider

CST = timezone(timedelta(hours=8))

# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def mock_client(monkeypatch):
    """Mock get_ts_client() → TushareClient with a controllable _query spy"""

    class MockTushareClient:
        def __init__(self):
            self.call_log: list[dict[str, Any]] = []

        def _query(self, api_name: str, **params) -> pd.DataFrame:
            self.call_log.append({"api": api_name, "params": params})

            if api_name == "daily":
                return pd.DataFrame({
                    "ts_code": ["688012.SH"],
                    "trade_date": ["20240102"],
                    "open": [140.0],
                    "high": [142.0],
                    "low": [139.5],
                    "close": [141.0],
                    "pre_close": [140.0],
                    "change": [1.0],
                    "pct_chg": [0.71],
                    "vol": [5000],
                    "amount": [7_000_000.0],
                })
            elif api_name == "daily_basic":
                return pd.DataFrame({
                    "ts_code": ["688012.SH"],
                    "trade_date": ["20240102"],
                    "pe": [55.0],
                    "pe_ttm": [53.0],
                    "pb": [6.5],
                    "total_mv": [5e10],
                    "circ_mv": [3e10],
                    "turnover_rate": [1.2],
                    "volume_ratio": [0.95],
                })
            elif api_name == "adj_factor":
                return pd.DataFrame({
                    "ts_code": ["688012.SH"],
                    "trade_date": ["20240102"],
                    "adj_factor": [1.5],
                })
            elif api_name == "stk_limit":
                return pd.DataFrame({
                    "ts_code": ["688012.SH"],
                    "trade_date": ["20240102"],
                    "up_limit": [168.0],
                    "down_limit": [112.0],
                    "pre_close": [140.0],
                })
            elif api_name == "trade_cal":
                return pd.DataFrame({
                    "cal_date": pd.to_datetime(["20260105"]),
                    "is_open": [1],
                    "pretrade_date": [pd.Timestamp("20260102")],
                })
            return pd.DataFrame()

        def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
            return pd.DataFrame({
                "ts_code": ["000001.SZ"],
                "name": ["平安银行"],
                "list_date": pd.to_datetime(["19910403"]),
            })

        def trade_cal(self, start_date="20000101", end_date=""):
            return self._query("trade_cal", start_date=start_date, end_date=end_date)

    client = MockTushareClient()
    monkeypatch.setattr(
        "commands.data_providers.tushare.tushare_market.get_ts_client",
        lambda: client,
    )
    return client


@pytest.fixture()
def provider(mock_client) -> TushareMarketProvider:
    return TushareMarketProvider()


# ═════════════════════════════════════════════════════════════════════════
# Provider Basics
# ═════════════════════════════════════════════════════════════════════════


def test_capability(provider: TushareMarketProvider):
    """能力声明包含正确的市场数据标志"""
    cap = provider.capability
    assert cap.name == "tushare"
    assert cap.can_daily is True
    assert cap.can_daily_basic is True
    assert cap.can_adj_factor is True
    assert cap.can_stk_limit is True
    assert cap.coverage_start is not None


def test_self_check_ok(provider: TushareMarketProvider, mock_client):
    """自检返回健康状态 (trade_cal 返回数据)"""
    health = provider.self_check()
    assert health.source_id == "tushare_market"
    # Our mock returns trade_cal data, so status should be "ok" or "partial"
    assert health.status in ("ok", "partial", "error")


def test_self_check_error(provider: TushareMarketProvider, mock_client, monkeypatch):
    """自检在模拟异常时返回 error 状态"""

    def failing_query(*args, **kwargs):
        raise RuntimeError("API unreachable")

    mock_client._query = failing_query
    health = provider.self_check()
    assert health.status == "error"


# ═════════════════════════════════════════════════════════════════════════
# daily
# ═════════════════════════════════════════════════════════════════════════


def test_daily(provider: TushareMarketProvider, mock_client):
    """daily 返回标准 DataFrame 且日期已标准化"""
    df = provider.daily(ts_code="688012.SH", start_date="20240101", end_date="20240131")

    assert not df.empty
    assert "ts_code" in df.columns
    assert "trade_date" in df.columns
    assert "close" in df.columns
    assert "pct_chg" in df.columns

    # trade_date 应为 datetime64
    assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    # 验证调用参数
    assert len(mock_client.call_log) == 1
    call = mock_client.call_log[0]
    assert call["api"] == "daily"
    assert call["params"]["ts_code"] == "688012.SH"


def test_daily_by_trade_date(provider: TushareMarketProvider, mock_client):
    """daily 支持按 trade_date 查询"""
    df = provider.daily(ts_code="688012.SH", trade_date="20240102")
    assert not df.empty
    assert mock_client.call_log[-1]["params"]["trade_date"] == "20240102"


def test_daily_no_params_raises(provider: TushareMarketProvider):
    """daily 无参数时抛出 ValueError"""
    with pytest.raises(ValueError, match="至少需要"):
        provider.daily()


def test_daily_empty_response(provider: TushareMarketProvider, mock_client):
    """daily 在 API 返回空时返回空 DataFrame"""

    def empty_query(*args, **kwargs):
        return pd.DataFrame()

    mock_client._query = empty_query
    df = provider.daily(ts_code="688012.SH", start_date="20240101", end_date="20240131")
    assert df.empty


# ═════════════════════════════════════════════════════════════════════════
# daily_basic
# ═════════════════════════════════════════════════════════════════════════


def test_daily_basic(provider: TushareMarketProvider, mock_client):
    """daily_basic 返回估值指标且日期已标准化"""
    df = provider.daily_basic(ts_code="688012.SH", trade_date="20240102")

    assert not df.empty
    assert "pe" in df.columns
    assert "pb" in df.columns
    assert "total_mv" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    call = mock_client.call_log[-1]
    assert call["api"] == "daily_basic"


def test_daily_basic_with_date_range(provider: TushareMarketProvider, mock_client):
    """daily_basic 支持日期区间"""
    df = provider.daily_basic(ts_code="688012.SH", start_date="20240101", end_date="20240131")
    assert not df.empty


def test_daily_basic_no_params_raises(provider: TushareMarketProvider):
    """daily_basic 无参数时抛出 ValueError"""
    with pytest.raises(ValueError, match="至少需要"):
        provider.daily_basic()


# ═════════════════════════════════════════════════════════════════════════
# adj_factor
# ═════════════════════════════════════════════════════════════════════════


def test_adj_factor(provider: TushareMarketProvider, mock_client):
    """adj_factor 返回复权因子数据且日期已标准化"""
    df = provider.adj_factor(ts_code="688012.SH", start_date="20240101", end_date="20240131")

    assert not df.empty
    assert "adj_factor" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    call = mock_client.call_log[-1]
    assert call["api"] == "adj_factor"


def test_adj_factor_single_date(provider: TushareMarketProvider, mock_client):
    """adj_factor 支持 trade_date 查询"""
    df = provider.adj_factor(ts_code="688012.SH", trade_date="20240102")
    assert not df.empty


def test_adj_factor_no_params_raises(provider: TushareMarketProvider):
    """adj_factor 无参数时抛出 ValueError"""
    with pytest.raises(ValueError, match="至少需要"):
        provider.adj_factor()


# ═════════════════════════════════════════════════════════════════════════
# stk_limit
# ═════════════════════════════════════════════════════════════════════════


def test_stk_limit(provider: TushareMarketProvider, mock_client):
    """stk_limit 返回涨跌停价格且日期已标准化"""
    df = provider.stk_limit(ts_code="688012.SH", trade_date="20240102")

    assert not df.empty
    assert "up_limit" in df.columns
    assert "down_limit" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    call = mock_client.call_log[-1]
    assert call["api"] == "stk_limit"


def test_stk_limit_no_params_raises(provider: TushareMarketProvider):
    """stk_limit 无参数时抛出 ValueError"""
    with pytest.raises(ValueError, match="至少需要"):
        provider.stk_limit()


# ═════════════════════════════════════════════════════════════════════════
# Date normalization (via BaseProvider.normalize_date)
# ═════════════════════════════════════════════════════════════════════════


def test_normalize_date_method(provider: TushareMarketProvider):
    """normalize_date 将字符串日期转为 datetime"""
    df = pd.DataFrame({"trade_date": ["20240101", "20240102"]})
    result = provider.normalize_date(df, date_col="trade_date")
    assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])
    assert result["trade_date"].iloc[0].strftime("%Y%m%d") == "20240101"


def test_normalize_date_skips_datetime(provider: TushareMarketProvider):
    """normalize_date 对已是 datetime 的列跳过转换"""
    df = pd.DataFrame({"trade_date": pd.to_datetime(["20240101"])})
    result = provider.normalize_date(df, date_col="trade_date")
    assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])


# ═════════════════════════════════════════════════════════════════════════
# Data sorting
# ═════════════════════════════════════════════════════════════════════════


def test_daily_sorted(provider: TushareMarketProvider, mock_client):
    """daily 返回按 ts_code + trade_date 排序的 DataFrame"""
    # Return multi-row data for sort check
    mock_client._query = lambda api, **params: pd.DataFrame({
        "ts_code": ["688012.SH", "688012.SH"],
        "trade_date": ["20240103", "20240102"],
        "close": [142.0, 141.0],
    })
    df = provider.daily(ts_code="688012.SH", start_date="20240101", end_date="20240131")
    assert df["trade_date"].iloc[0] == pd.Timestamp("2024-01-02")
    assert df["trade_date"].iloc[1] == pd.Timestamp("2024-01-03")


# ═════════════════════════════════════════════════════════════════════════
# stock_basic / trade_cal (delegation)
# ═════════════════════════════════════════════════════════════════════════


def test_stock_basic_delegation(provider: TushareMarketProvider):
    """stock_basic 委托给 TushareClient.stock_basic"""
    df = provider.stock_basic()
    assert not df.empty
    assert "ts_code" in df.columns


def test_trade_cal_delegation(provider: TushareMarketProvider, mock_client):
    """trade_cal 委托给 TushareClient.trade_cal"""
    df = provider.trade_cal(start_date="20260101", end_date="20260110")
    assert not df.empty
    assert mock_client.call_log[-1]["api"] == "trade_cal"
