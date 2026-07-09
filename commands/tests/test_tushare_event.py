"""TushareEventProvider — Tests

Tests for the Tushare event / corporate actions provider covering:
  - __init__ and capability property
  - self_check behavior
  - dividend, stk_surv, block_trade, new_share (required abstract methods)
  - repurchase, share_float, stk_holdertrade, stk_holdernumber, stk_rewards (extra)
  - Parameter passthrough to TushareClient._query()
  - NotImplementedError stubs for non-event methods

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

from commands.data_providers.tushare.tushare_event import TushareEventProvider
from commands.data_providers import ProviderCapability, ProviderHealth

CST = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def mock_client():
    """TushareClient 模拟"""
    with patch("commands.data_providers.tushare.tushare_event.get_ts_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


@pytest.fixture()
def provider(mock_client):
    """已注入 mock client 的 Provider 实例"""
    return TushareEventProvider()


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

    def test_capability_event_flags(self, provider):
        cap = provider.capability
        assert cap.can_dividend is True
        assert cap.can_stk_surv is True
        assert cap.can_block_trade is True
        assert cap.can_new_share is True
        assert cap.can_repurchase is True
        assert cap.can_share_float is True
        assert cap.can_stk_holdertrade is True
        assert cap.can_stk_holdernumber is True
        assert cap.can_stk_rewards is True

    def test_capability_non_event_flags_false(self, provider):
        """非事件能力的标记应为 False"""
        cap = provider.capability
        assert cap.can_daily is False
        assert cap.can_daily_basic is False
        assert cap.can_stock_basic is False
        assert cap.can_fina_indicator is False
        assert cap.can_moneyflow is False


# ═══════════════════════════════════════════════════════════════════
#  自检
# ═══════════════════════════════════════════════════════════════════


class TestSelfCheck:
    """self_check 行为验证"""

    def test_self_check_returns_health(self, provider, mock_client):
        """正常返回 ProviderHealth 实例, 各 API 返回数据"""
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "ann_date": ["20241231"],
        })
        health = provider.self_check()
        assert isinstance(health, ProviderHealth)
        assert health.status == "ok"
        # _query 应在自检中调用 9 次 (9 个 API)
        assert mock_client._query.call_count == 9

    def test_self_check_partial_on_empty(self, provider, mock_client):
        """部分接口返回空 → status=partial + warnings"""
        call_count = [0]

        def side_effect(api_name, **kwargs):
            call_count[0] += 1
            if api_name == "stk_rewards":
                return pd.DataFrame()  # 空
            return pd.DataFrame({
                "ts_code": ["688012.SH"],
                "ann_date": ["20241231"],
            })

        mock_client._query.side_effect = side_effect

        health = provider.self_check()
        assert health.status == "partial"
        assert any("empty" in w for w in health.warnings)

    def test_self_check_partial_on_exception(self, provider, mock_client):
        """API 异常 → status=partial + errors"""
        mock_client._query.side_effect = ValueError("Tushare API error")

        health = provider.self_check()
        assert health.status in ("partial", "error")
        assert len(health.errors) > 0

    def test_self_check_freshness(self, provider, mock_client):
        """data_freshness 包含 9 个指标的最新日期"""
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "ann_date": ["20241231"],
        })
        health = provider.self_check()
        assert len(health.data_freshness) == 9
        for key in (
            "dividend", "stk_surv", "block_trade", "new_share",
            "repurchase", "share_float", "stk_holdertrade",
            "stk_holdernumber", "stk_rewards",
        ):
            assert key in health.data_freshness


# ═══════════════════════════════════════════════════════════════════
#  事件/公司行为接口
# ═══════════════════════════════════════════════════════════════════


class TestDividend:
    """dividend 方法"""

    def test_query_with_ts_code(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "stk_div": [0.5],
        })
        df = provider.dividend(ts_code="688012.SH")
        assert not df.empty
        mock_client._query.assert_called_once_with("dividend", ts_code="688012.SH")

    def test_query_with_dates(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "stk_div": [0.5],
        })
        df = provider.dividend(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "dividend", ts_code="688012.SH", start_date="20240101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.dividend(ts_code="INVALID.CODE")
        assert df.empty

    def test_ann_date_is_datetime(self, provider, mock_client):
        """ann_date 列应被转换为 datetime"""
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "stk_div": [0.5],
        })
        df = provider.dividend(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["ann_date"])


class TestStkSurv:
    """stk_surv 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "surv_date": ["20241231"], "fund_name": ["某基金"],
        })
        df = provider.stk_surv(ts_code="688012.SH", start_date="20230101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "stk_surv", ts_code="688012.SH", start_date="20230101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.stk_surv(ts_code="INVALID.CODE")
        assert df.empty

    def test_surv_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "surv_date": ["20241231"], "fund_name": ["某基金"],
        })
        df = provider.stk_surv(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["surv_date"])


class TestBlockTrade:
    """block_trade 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "trade_date": ["20241231"], "price": [50.0], "vol": [100.0],
        })
        df = provider.block_trade(ts_code="688012.SH", start_date="20240101", end_date="20240630")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "block_trade", ts_code="688012.SH", start_date="20240101", end_date="20240630"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.block_trade(ts_code="INVALID.CODE")
        assert df.empty

    def test_trade_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "trade_date": ["20241231"], "price": [50.0],
        })
        df = provider.block_trade(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])


class TestNewShare:
    """new_share 方法"""

    def test_query_with_dates(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ipo_date": ["20240101"], "issue_price": [50.0],
        })
        df = provider.new_share(start_date="20240101", end_date="20240630")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "new_share", start_date="20240101", end_date="20240630"
        )

    def test_query_no_params(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ipo_date": ["20240101"], "issue_price": [50.0],
        })
        df = provider.new_share()
        assert not df.empty
        mock_client._query.assert_called_once_with("new_share")

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.new_share(start_date="20240101", end_date="20240630")
        assert df.empty


class TestRepurchase:
    """repurchase 方法"""

    def test_query_with_ts_code(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "amount": [1000000.0],
        })
        df = provider.repurchase(ts_code="688012.SH")
        assert not df.empty
        mock_client._query.assert_called_once_with("repurchase", ts_code="688012.SH")

    def test_query_with_ann_date(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20240601"], "amount": [1000000.0],
        })
        df = provider.repurchase(ts_code="688012.SH", ann_date="20240601")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "repurchase", ts_code="688012.SH", ann_date="20240601"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.repurchase(ts_code="INVALID.CODE")
        assert df.empty

    def test_ann_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20240601"], "amount": [1000000.0],
        })
        df = provider.repurchase(ts_code="688012.SH", ann_date="20240601")
        assert pd.api.types.is_datetime64_any_dtype(df["ann_date"])


class TestShareFloat:
    """share_float 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "float_date": ["20241231"], "vol": [1000000.0],
        })
        df = provider.share_float(ts_code="688012.SH", start_date="20230101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "share_float", ts_code="688012.SH", start_date="20230101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.share_float(ts_code="INVALID.CODE")
        assert df.empty

    def test_float_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "float_date": ["20241231"], "vol": [1000000.0],
        })
        df = provider.share_float(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["float_date"])


class TestStkHoldertrade:
    """stk_holdertrade 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "change_date": ["20241231"], "vol": [10000.0], "trade_type": ["买入"],
        })
        df = provider.stk_holdertrade(ts_code="688012.SH", start_date="20230101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "stk_holdertrade", ts_code="688012.SH", start_date="20230101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.stk_holdertrade(ts_code="INVALID.CODE")
        assert df.empty

    def test_change_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "change_date": ["20241231"], "vol": [10000.0],
        })
        df = provider.stk_holdertrade(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["change_date"])


class TestStkHoldernumber:
    """stk_holdernumber 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "holder_number": [50000],
        })
        df = provider.stk_holdernumber(ts_code="688012.SH", start_date="20230101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "stk_holdernumber", ts_code="688012.SH", start_date="20230101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.stk_holdernumber(ts_code="INVALID.CODE")
        assert df.empty

    def test_ann_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "holder_number": [50000],
        })
        df = provider.stk_holdernumber(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["ann_date"])


class TestStkRewards:
    """stk_rewards 方法"""

    def test_query(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "granted_qty": [500000.0],
        })
        df = provider.stk_rewards(ts_code="688012.SH", start_date="20200101", end_date="20241231")
        assert not df.empty
        mock_client._query.assert_called_once_with(
            "stk_rewards", ts_code="688012.SH", start_date="20200101", end_date="20241231"
        )

    def test_empty_result(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame()
        df = provider.stk_rewards(ts_code="INVALID.CODE")
        assert df.empty

    def test_ann_date_is_datetime(self, provider, mock_client):
        mock_client._query.return_value = pd.DataFrame({
            "ts_code": ["688012.SH"], "ann_date": ["20241231"], "granted_qty": [500000.0],
        })
        df = provider.stk_rewards(ts_code="688012.SH")
        assert pd.api.types.is_datetime64_any_dtype(df["ann_date"])


# ═══════════════════════════════════════════════════════════════════
#  NotImplementedError stubs
# ═══════════════════════════════════════════════════════════════════


class TestNotImplementedMethods:
    """事件 Provider 不支持的抽象方法应抛 NotImplementedError"""

    @pytest.mark.parametrize("method_name,args", [
        ("stock_basic", {}),
        ("trade_cal", {}),
        ("daily", {}),
        ("daily_basic", {}),
        ("adj_factor", {}),
        ("stk_limit", {}),
        ("suspend", {}),
        ("namechange", {}),
        ("fina_indicator", {}),
        ("income", {}),
        ("balancesheet", {}),
        ("cashflow", {}),
        ("forecast", {}),
        ("moneyflow", {}),
        ("index_daily", {}),
        ("hs_const", {}),
        ("moneyflow_hsgt", {}),
        ("hsgt_top10", {}),
    ])
    def test_not_implemented(self, provider, method_name, args):
        with pytest.raises(NotImplementedError):
            getattr(provider, method_name)(**args)


# ═══════════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界条件"""

    def test_normalize_dates_empty(self, provider):
        """空 DataFrame 不报错"""
        df = provider._normalize_dates(pd.DataFrame())
        assert df.empty

    def test_normalize_dates_no_date_cols(self, provider):
        """无日期列的 DataFrame 不受影响"""
        df = pd.DataFrame({"a": [1], "b": [2]})
        result = provider._normalize_dates(df)
        assert list(result.columns) == ["a", "b"]
        assert result["a"].iloc[0] == 1

    def test_normalize_dates_mixed_cols(self, provider):
        """同时包含 ann_date 和其他列"""
        df = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "ann_date": ["20241231"],
            "trade_date": ["20241230"],
            "value": [100.0],
        })
        result = provider._normalize_dates(df)
        assert pd.api.types.is_datetime64_any_dtype(result["ann_date"])
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

    def test_normalize_dates_custom_cols(self, provider):
        """自定义 date_cols 参数"""
        df = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "my_date": ["20241231"],
            "value": [100.0],
        })
        result = provider._normalize_dates(df, date_cols=["my_date"])
        assert pd.api.types.is_datetime64_any_dtype(result["my_date"])

    @pytest.mark.parametrize("api_name", [
        "dividend", "stk_surv", "block_trade", "new_share",
        "repurchase", "share_float", "stk_holdertrade",
        "stk_holdernumber", "stk_rewards",
    ])
    def test_api_returns_none(self, provider, mock_client, api_name):
        """_query 返回 None 时降级为空 DataFrame"""
        mock_client._query.return_value = pd.DataFrame()

        # 通过反射调用
        method = getattr(provider, api_name)
        if api_name == "new_share":
            df = method(start_date="20240101", end_date="20240630")
        elif api_name == "repurchase":
            df = method(ts_code="688012.SH", ann_date="20240601")
        else:
            df = method(ts_code="688012.SH")
        assert df.empty
