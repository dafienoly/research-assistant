#!/usr/bin/env python3
"""
Tests for TushareStockProvider — 股票基础/指数/更名/停牌

测试策略:
  - 核心逻辑通过 mock TushareClient._query 验证参数传递、日期标准化、空值处理
  - 无需真实 Tushare Token，所有 API 调用均被 mock 拦截
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest
import pandas as pd
import numpy as np

# 确保能找到 commands 包
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)  # commands/
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from commands.data_providers import BaseProvider, ProviderCapability, ProviderHealth
from commands.data_providers.tushare import TushareStockProvider

CST = timezone(timedelta(hours=8))


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture()
def provider() -> TushareStockProvider:
    """返回 TushareStockProvider 实例"""
    return TushareStockProvider()


@pytest.fixture()
def mock_ts_client(mocker):
    """Mock TushareClient 单例返回，避免真实 API 调用"""
    from factor_lab.data import tushare_client as tc_mod

    mock = mocker.patch.object(tc_mod, "get_ts_client", autospec=True)
    # mock.return_value._query 的默认行为：返回空 DataFrame
    mock.return_value._query.return_value = pd.DataFrame()
    return mock.return_value


# =========================================================================
# Provider 基础
# =========================================================================


class TestProviderBasics:
    """Provider 基础能力验证"""

    def test_instantiation(self, provider: TushareStockProvider):
        """确认可以实例化"""
        assert isinstance(provider, BaseProvider)
        assert isinstance(provider, TushareStockProvider)

    def test_capability(self, provider: TushareStockProvider):
        """确认能力声明正确"""
        cap = provider.capability
        assert isinstance(cap, ProviderCapability)
        assert cap.name == "tushare_stock"
        assert cap.can_stock_basic is True
        assert cap.can_trade_cal is True
        assert cap.can_index_daily is True
        assert cap.can_suspend is True
        assert cap.can_namechange is True
        # 确认已有覆盖起止时间
        assert cap.coverage_start == "19901219"
        assert cap.stock_count > 0

    def test_self_check_no_network(self, provider: TushareStockProvider, mocker):
        """离线环境自检不应抛异常"""
        # 模拟网络错误
        from factor_lab.data import tushare_client as tc_mod
        mocker.patch.object(
            tc_mod, "get_ts_client",
            side_effect=ConnectionError("模拟网络不可达")
        )
        health = provider.self_check()
        assert isinstance(health, ProviderHealth)
        assert health.status == "error"
        assert len(health.errors) > 0


# =========================================================================
# stock_basic
# =========================================================================


class TestStockBasic:
    """股票基本信息"""

    STOCK_BASIC_COLS = [
        "ts_code", "name", "area", "industry",
        "market", "list_date", "delist_date", "is_hs",
    ]

    def _make_stock_df(
        self,
        n: int = 3,
        include_delist: bool = True,
    ) -> pd.DataFrame:
        """构造模拟 stock_basic 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": f"600{100+i:03d}.SH",
                "name": f"测试股票{i}",
                "area": "上海",
                "industry": "信息技术",
                "market": "主板",
                "list_date": "20100101",
                "delist_date": "" if not include_delist else "20990101",
                "is_hs": "S" if i % 2 == 0 else "",
            })
        return pd.DataFrame(rows)

    def test_stock_basic_normal(self, provider: TushareStockProvider, mock_ts_client):
        """正常返回上市股票列表"""
        mock_df = self._make_stock_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.stock_basic(list_status="L")

        # 验证调用参数
        mock_ts_client._query.assert_called_once_with(
            "stock_basic",
            fields="ts_code,name,area,industry,market,list_date,delist_date,is_hs",
            list_status="L",
        )

        # 验证结果
        assert not result.empty
        assert len(result) == 3
        for col in self.STOCK_BASIC_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["list_date"])
        assert pd.api.types.is_datetime64_any_dtype(result["delist_date"])

    def test_stock_basic_all_status(self, provider: TushareStockProvider, mock_ts_client):
        """支持不同上市状态查询"""
        mock_ts_client._query.return_value = self._make_stock_df()

        for status in ("L", "D", "P"):
            mock_ts_client._query.reset_mock()
            _ = provider.stock_basic(list_status=status)
            _, kwargs = mock_ts_client._query.call_args
            assert kwargs["list_status"] == status

    def test_stock_basic_empty(self, provider: TushareStockProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.stock_basic()
        assert result.empty

    def test_stock_basic_delist_date_nat(self, provider: TushareStockProvider, mock_ts_client):
        """上市股票 delist_date 应为 NaT"""
        df = self._make_stock_df(include_delist=False)
        mock_ts_client._query.return_value = df
        result = provider.stock_basic()
        assert result["delist_date"].isna().all()


# =========================================================================
# trade_cal
# =========================================================================


class TestTradeCal:
    """交易日历"""

    TRADE_CAL_COLS = ["exchange", "cal_date", "is_open", "pretrade_date"]

    def _make_cal_df(self, start: str = "20260101", days: int = 10) -> pd.DataFrame:
        """构造模拟 trade_cal 返回值"""
        dates = []
        base = datetime.strptime(start, "%Y%m%d")
        for i in range(days):
            d = base.replace(day=base.day + i)
            is_open = 0 if d.weekday() >= 5 else 1
            dates.append({
                "exchange": "SSE",
                "cal_date": d.strftime("%Y%m%d"),
                "is_open": is_open,
                "pretrade_date": (d.replace(day=d.day - 1)).strftime("%Y%m%d") if i > 0 else "",
            })
        return pd.DataFrame(dates)

    def test_trade_cal_normal(self, provider: TushareStockProvider, mock_ts_client):
        """正常返回交易日历"""
        mock_df = self._make_cal_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.trade_cal(start_date="20260101", end_date="20260110")

        mock_ts_client._query.assert_called_once_with(
            "trade_cal",
            start_date="20260101",
            end_date="20260110",
        )
        assert not result.empty
        for col in self.TRADE_CAL_COLS:
            assert col in result.columns

        # cal_date 应为 datetime
        assert pd.api.types.is_datetime64_any_dtype(result["cal_date"])

        # is_open 列必须存在
        assert "is_open" in result.columns

    def test_trade_cal_default_end_date(self, provider: TushareStockProvider, mock_ts_client):
        """end_date 默认为当天"""
        mock_ts_client._query.return_value = self._make_cal_df()
        result = provider.trade_cal(start_date="20260101")
        assert not result.empty
        # 验证 end_date 被设置
        call_kwargs = mock_ts_client._query.call_args[1]
        assert "end_date" in call_kwargs
        assert call_kwargs["end_date"] == datetime.now(CST).strftime("%Y%m%d")

    def test_trade_cal_empty(self, provider: TushareStockProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.trade_cal()
        assert result.empty

    def test_trade_cal_is_open_fallback(self, provider: TushareStockProvider, mock_ts_client):
        """Tushare 不返回 is_open 列时，自动补 1"""
        df = pd.DataFrame({"exchange": ["SSE"], "cal_date": ["20260101"]})
        mock_ts_client._query.return_value = df
        result = provider.trade_cal(start_date="20260101", end_date="20260101")
        assert "is_open" in result.columns
        assert result["is_open"].iloc[0] == 1


# =========================================================================
# index_daily
# =========================================================================


class TestIndexDaily:
    """指数日线行情"""

    INDEX_DAILY_COLS = [
        "ts_code", "trade_date", "open", "high", "low",
        "close", "pre_close", "change", "pct_chg", "vol", "amount",
    ]

    def _make_index_df(self, n: int = 5) -> pd.DataFrame:
        """构造模拟 index_daily 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": "000001.SH",
                "trade_date": f"202601{7+i:02d}",
                "open": 3200.0 + i,
                "high": 3210.0 + i,
                "low": 3190.0 + i,
                "close": 3205.0 + i,
                "pre_close": 3200.0 + i,
                "change": 5.0,
                "pct_chg": 0.16,
                "vol": 100000.0 + i * 1000,
                "amount": 1.5e10 + i * 1e8,
            })
        return pd.DataFrame(rows)

    def test_index_daily_normal(self, provider: TushareStockProvider, mock_ts_client):
        """正常返回指数日线"""
        mock_df = self._make_index_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.index_daily(
            ts_code="000001.SH",
            start_date="20260101",
            end_date="20260131",
        )

        mock_ts_client._query.assert_called_once_with(
            "index_daily",
            ts_code="000001.SH",
            start_date="20260101",
            end_date="20260131",
        )
        assert not result.empty
        for col in self.INDEX_DAILY_COLS:
            assert col in result.columns, f"缺少列: {col}"
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])
        # 验证排序
        assert result["trade_date"].is_monotonic_increasing

    def test_index_daily_without_code(self, provider: TushareStockProvider, mock_ts_client):
        """不传 ts_code 也能查询（全市场指数）"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.index_daily(start_date="20260101", end_date="20260105")
        assert result.empty  # 预期空（mock 默认）
        call_kwargs = mock_ts_client._query.call_args[1]
        assert "ts_code" not in call_kwargs

    def test_index_daily_empty(self, provider: TushareStockProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.index_daily(ts_code="000001.SH")
        assert result.empty


# =========================================================================
# namechange
# =========================================================================


class TestNameChange:
    """股票更名/ST 信息"""

    NAMECHANGE_COLS = ["ts_code", "name", "start_date", "end_date", "change_reason"]

    def _make_namechange_df(self, n: int = 3) -> pd.DataFrame:
        """构造模拟 namechange 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": "688012.SH",
                "name": f"中微公司" if i == 0 else f"*ST中微{i}",
                "start_date": f"20200{1+i:02d}01",
                "end_date": f"20200{1+i+1:02d}01",
                "change_reason": "ST" if i > 0 else "",
                "ann_date": f"20200{1+i:02d}01",
            })
        return pd.DataFrame(rows)

    def test_namechange_normal(self, provider: TushareStockProvider, mock_ts_client):
        """正常返回更名信息"""
        mock_df = self._make_namechange_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.namechange(
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )

        mock_ts_client._query.assert_called_once_with(
            "namechange",
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )
        assert not result.empty
        for col in self.NAMECHANGE_COLS:
            assert col in result.columns

        # 日期列标准化
        for col in ("start_date", "end_date", "ann_date"):
            assert pd.api.types.is_datetime64_any_dtype(result[col])

    def test_namechange_empty(self, provider: TushareStockProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.namechange(ts_code="000001.SZ")
        assert result.empty

    def test_namechange_no_params(self, provider: TushareStockProvider, mock_ts_client):
        """无参数时调用"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.namechange()
        assert result.empty


# =========================================================================
# suspend
# =========================================================================


class TestSuspend:
    """停复牌信息"""

    SUSPEND_COLS = ["ts_code", "trade_date", "suspend_timing", "suspend_type"]

    def _make_suspend_df(self, n: int = 2) -> pd.DataFrame:
        """构造模拟 suspend_d 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": "688012.SH",
                "trade_date": f"202603{10+i:02d}",
                "suspend_timing": "D" if i == 0 else "E",
                "suspend_type": "S" if i == 0 else "R",
            })
        return pd.DataFrame(rows)

    def test_suspend_normal(self, provider: TushareStockProvider, mock_ts_client):
        """正常返回停牌信息"""
        mock_df = self._make_suspend_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.suspend(
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )

        mock_ts_client._query.assert_called_once_with(
            "suspend_d",
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )
        assert not result.empty
        for col in self.SUSPEND_COLS:
            assert col in result.columns

        # trade_date 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

    def test_suspend_empty(self, provider: TushareStockProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.suspend(ts_code="000001.SZ")
        assert result.empty

    def test_suspend_no_params(self, provider: TushareStockProvider, mock_ts_client):
        """无参数时调用不应该抛异常"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.suspend()
        assert result.empty
        # 验证调用时未传额外参数
        _, kwargs = mock_ts_client._query.call_args
        assert "ts_code" not in kwargs
        assert "start_date" not in kwargs
        assert "end_date" not in kwargs


# =========================================================================
# Edge cases & data types
# =========================================================================


class TestEdgeCases:
    """边界情况"""

    def test_provider_is_subclass_of_base(self, provider: TushareStockProvider):
        """确认是 BaseProvider 的子类"""
        assert isinstance(provider, BaseProvider)

    def test_all_outputs_are_dataframe(self, provider: TushareStockProvider, mock_ts_client):
        """所有公开方法返回类型均为 DataFrame"""
        mock_ts_client._query.return_value = pd.DataFrame()

        methods = [
            ("stock_basic", {}),
            ("trade_cal", {}),
            ("index_daily", {}),
            ("namechange", {}),
            ("suspend", {}),
        ]
        for method_name, kwargs in methods:
            result = getattr(provider, method_name)(**kwargs)
            assert isinstance(result, pd.DataFrame), (
                f"{method_name} 返回值应为 DataFrame, 得到 {type(result)}"
            )

    def test_preserve_original_data(self, provider: TushareStockProvider, mock_ts_client):
        """返回的 DataFrame 不应修改原始 mock 数据（测试 copy 语义）"""
        orig_df = pd.DataFrame({
            "ts_code": ["600000.SH"],
            "name": ["浦发银行"],
            "area": ["上海"],
            "industry": ["银行"],
            "market": ["主板"],
            "list_date": ["19991110"],
            "delist_date": [""],
            "is_hs": ["S"],
        })
        mock_ts_client._query.return_value = orig_df
        result = provider.stock_basic()

        # 原始数据不应变成 datetime — 应保持字符/string 类型
        assert not pd.api.types.is_datetime64_any_dtype(orig_df["list_date"]), (
            "原始数据的 list_date 不应被修改为 datetime"
        )
        # 结果应是 datetime
        assert pd.api.types.is_datetime64_any_dtype(result["list_date"])

    @pytest.mark.parametrize("method_name", [
        "daily", "daily_basic", "adj_factor", "stk_limit",
        "fina_indicator", "income", "balancesheet", "cashflow",
        "forecast", "moneyflow", "hs_const", "moneyflow_hsgt",
        "hsgt_top10", "dividend", "stk_surv", "block_trade", "new_share",
    ])
    def test_not_implemented_methods_raise(self, provider: TushareStockProvider, method_name):
        """明确未实现的接口应抛 NotImplementedError"""
        method = getattr(provider, method_name)
        with pytest.raises(NotImplementedError):
            method()


# =========================================================================
# Integration / 冒烟测试 (需要真实 Tushare Token)
# =========================================================================


class TestSmokeIntegration:
    """冒烟测试 — 需要网络和有效 Tushare Token

    默认跳过。设环境变量 TUSHARE_SMOKE=1 启用。
    """

    SMOKE_ENABLED = os.environ.get("TUSHARE_SMOKE", "").strip() in ("1", "true", "yes")

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_stock_basic_live(self):
        """真实环境：获取上市股票列表"""
        prov = TushareStockProvider()
        df = prov.stock_basic(list_status="L")
        assert not df.empty
        assert len(df) > 1000  # 至少 1000 只股票
        assert "ts_code" in df.columns
        assert "list_date" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["list_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_trade_cal_live(self):
        """真实环境：获取交易日历"""
        prov = TushareStockProvider()
        df = prov.trade_cal(start_date="20260101", end_date="20260131")
        assert not df.empty
        assert "is_open" in df.columns
        assert "cal_date" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["cal_date"])
        # 至少有一个交易日
        assert df["is_open"].sum() >= 20

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_index_daily_live(self):
        """真实环境：获取指数日线"""
        prov = TushareStockProvider()
        df = prov.index_daily(
            ts_code="000001.SH",
            start_date="20260101",
            end_date="20260131",
        )
        assert not df.empty
        assert "pct_chg" in df.columns

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_namechange_live(self):
        """真实环境：获取更名信息"""
        prov = TushareStockProvider()
        df = prov.namechange(
            ts_code="688012.SH",
            start_date="20200101",
            end_date="20260708",
        )
        # 中微公司应该有更名记录
        assert not df.empty
        assert "start_date" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["start_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_self_check_live(self):
        """真实环境：自检"""
        prov = TushareStockProvider()
        health = prov.self_check()
        assert health.status in ("ok", "partial")
        assert health.last_check
