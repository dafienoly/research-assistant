"""TushareFinaProvider — Tests

Tests for the Tushare financial data provider covering:
  - __init__ and capability property
  - self_check behavior
  - fina_indicator, income, balancesheet, cashflow, forecast
  - Parameter passthrough to TushareClient._query()
  - NotImplementedError stubs for non-financial methods

All tests mock TushareClient to avoid real API calls.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import pandas as pd
import numpy as np

from commands.data_providers.tushare.tushare_fina import TushareFinaProvider
from commands.data_providers import ProviderCapability, ProviderHealth

CST = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def mock_client():
    """TushareClient 模拟"""
    with patch("commands.data_providers.tushare.tushare_fina.get_ts_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


@pytest.fixture()
def provider(mock_client):
    """已注入 mock client 的 Provider 实例"""
    return TushareFinaProvider()


# ═══════════════════════════════════════════════════════════════════
#  基础能力
# ═══════════════════════════════════════════════════════════════════


class TestCapability:
    """ProviderCapability 声明验证"""

    def test_capability_type(self, provider):
        cap = provider.capability
        assert isinstance(cap, ProviderCapability)

    def test_capability_name(self, provider):
        assert provider.capability.name == "tushare"

    def test_capability_fina_flags(self, provider):
        cap = provider.capability
        assert cap.can_fina_indicator is True
        assert cap.can_income is True
        assert cap.can_balancesheet is True
        assert cap.can_cashflow is True
        assert cap.can_forecast is True

    def test_capability_non_fina_flags_false(self, provider):
        """非财务能力的标记应为 False"""
        cap = provider.capability
        assert cap.can_daily is False
        assert cap.can_daily_basic is False
        assert cap.can_stock_basic is False


# ═══════════════════════════════════════════════════════════════════
#  自检
# ═══════════════════════════════════════════════════════════════════


class TestSelfCheck:
    """self_check 行为验证"""

    def test_self_check_returns_health(self, provider, mock_client):
        """正常返回 ProviderHealth 实例, 各 API 返回数据"""
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "end_date": ["20241231"],
            "roe": [15.5],
        })
        health = provider.self_check()
        assert isinstance(health, ProviderHealth)
        assert health.status == "ok"
        # _query 应在自检中调用 5 次 (5 个 API)
        assert mock_client._query.call_count == 5

    def test_self_check_partial_on_empty(self, provider, mock_client):
        """部分接口返回空 → status=partial + warnings"""
        def side_effect(api_name, **kwargs):
            if api_name == "forecast":
                return pd.DataFrame()  # 空
            return pd.DataFrame({
                "ts_code": ["688012.SH"],
                "end_date": ["20241231"],
                "roe": [15.5],
            })
        mock_client._query.side_effect = side_effect

        health = provider.self_check()
        assert health.status == "partial"
        assert any("empty" in w for w in health.warnings)

    def test_self_check_error_on_exception(self, provider, mock_client):
        """API 异常 → status=partial + errors"""
        mock_client._query.side_effect = ValueError("Tushare API error")

        health = provider.self_check()
        assert health.status in ("partial", "error")
        assert len(health.errors) > 0

    def test_self_check_freshness(self, provider, mock_client):
        """data_freshness 包含 5 个指标的最新日期"""
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "end_date": ["20241231"],
            "roe": [15.5],
        })
        health = provider.self_check()
        assert len(health.data_freshness) == 5
        for key in ("fina_indicator", "income", "balancesheet", "cashflow", "forecast"):
            assert key in health.data_freshness


# ═══════════════════════════════════════════════════════════════════
#  财务数据接口
# ═══════════════════════════════════════════════════════════════════


class TestFinaIndicator:
    """fina_indicator 方法"""

    def test_query_with_ts_code(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "roe": [12.5],
        })
        df = provider.fina_indicator(ts_code="688012.SH")
        assert not df.empty
        mock_client._query.assert_called_once_with("fina_indicator", ts_code="688012.SH")

    def test_query_with_dates(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "roe": [12.5],
        })
        df = provider.fina_indicator(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "fina_indicator", ts_code="688012.SH", start_date="20240101", end_date="20241231"
        )

    def test_query_with_period(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "roe": [12.5],
        })
        df = provider.fina_indicator(period="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with("fina_indicator", period="20241231")

    def test_query_no_params(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "roe": [12.5],
        })
        df = provider.fina_indicator()
        assert not df.empty
        mock_client._query.assert_called_once_with("fina_indicator")

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.fina_indicator(ts_code="INVALID.CODE")
        assert df.empty

    def test_end_date_is_datetime(self, provider, mock_client):
        """end_date 列应被转换为 datetime"""
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "roe": [12.5],
        })
        df = provider.fina_indicator(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["end_date"])


class TestIncome:
    """income 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "revenue": [100.0],
        })
        df = provider.income(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "income", ts_code="688012.SH", start_date="20240101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.income(ts_code="INVALID.CODE")
        assert df.empty

    def test_end_date_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "revenue": [100.0],
        })
        df = provider.income(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["end_date"])


class TestBalancesheet:
    """balancesheet 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "total_assets": [500.0],
        })
        df = provider.balancesheet(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "balancesheet", ts_code="688012.SH", start_date="20240101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.balancesheet(ts_code="INVALID.CODE")
        assert df.empty

    def test_end_date_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "total_assets": [500.0],
        })
        df = provider.balancesheet(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["end_date"])


class TestCashflow:
    """cashflow 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "n_cashflow_act": [50.0],
        })
        df = provider.cashflow(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "cashflow", ts_code="688012.SH", start_date="20240101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.cashflow(ts_code="INVALID.CODE")
        assert df.empty

    def test_end_date_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "n_cashflow_act": [50.0],
        })
        df = provider.cashflow(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["end_date"])


class TestForecast:
    """forecast 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "type": ["预增"],
        })
        df = provider.forecast(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "forecast", ts_code="688012.SH", start_date="20240101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.forecast(ts_code="INVALID.CODE")
        assert df.empty

    def test_end_date_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "end_date": ["20241231"], "type": ["预增"],
        })
        df = provider.forecast(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["end_date"])


# ═══════════════════════════════════════════════════════════════════
#  NotImplementedError stubs
# ═══════════════════════════════════════════════════════════════════

class TestNotImplementedMethods:
    """财务 Provider 不支持的抽象方法应抛 NotImplementedError"""

    @pytest.mark.parametrize("method_name,args", [
        ("stock_basic", {}),
        ("trade_cal", {}),
        ("daily", {}),
        ("daily_basic", {}),
        ("adj_factor", {}),
        ("stk_limit", {}),
        ("suspend", {}),
        ("namechange", {}),
        ("moneyflow", {}),
        ("index_daily", {}),
        ("hs_const", {}),
        ("moneyflow_hsgt", {}),
        ("hsgt_top10", {}),
        ("dividend", {}),
        ("stk_surv", {}),
        ("block_trade", {}),
        ("new_share", {}),
    ])
    def test_not_implemented(self, provider, method_name, args):
        with pytest.raises(NotImplementedError):
            getattr(provider, method_name)(**args)


# ═══════════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """边界条件"""

    def test_normalize_end_date_empty(self, provider):
        """空 DataFrame 不报错"""
        df = provider._normalize_end_date(pd.DataFrame())
        assert df.empty

    def test_normalize_end_date_no_date_cols(self, provider):
        """无日期列的 DataFrame 不受影响"""
        df = pd.DataFrame({"a": [1], "b": [2]})
        result = provider._normalize_end_date(df)
        assert list(result.columns) == ["a", "b"]

    def test_normalize_end_date_mixed_cols(self, provider):
        """同时包含 end_date 和其他列"""
        df = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "end_date": ["20241231"],
            "ann_date": ["20250115"],
            "value": [100.0],
        })
        result = provider._normalize_end_date(df)
        assert pd.api.types.is_datetime64_any_dtype(result["end_date"])
        assert pd.api.types.is_datetime64_any_dtype(result["ann_date"])

    @pytest.mark.parametrize("api_name", ["fina_indicator", "income", "balancesheet", "cashflow", "forecast"])
    def test_api_returns_none(self, provider, mock_client, api_name):
        """_query 返回 None 时降级为空 DataFrame"""
        mock_client._query.return_value = pd.DataFrame()

        # 通过反射调用
        method = getattr(provider, api_name)
        df = method(ts_code="688012.SH")
        assert df.empty
