#!/usr/bin/env python3
"""
Tests for TushareFundFlowProvider — 资金流向 / 沪深港通 / 融资融券 / 龙虎榜

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
from commands.data_providers.tushare import TushareFundFlowProvider

CST = timezone(timedelta(hours=8))


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture()
def mock_ts_client(mocker):
    """Mock TushareClient 单例返回，避免真实 API 调用

    必须在 provider 实例化之前生效，所以 provider fixture 依赖本 fixture。
    """
    from factor_lab.data import tushare_client as tc_mod

    mock = mocker.patch.object(tc_mod, "get_ts_client", autospec=True)
    # mock.return_value._query 的默认行为：返回空 DataFrame
    mock.return_value._query.return_value = pd.DataFrame()
    return mock.return_value


@pytest.fixture()
def provider(mock_ts_client) -> TushareFundFlowProvider:
    """返回 TushareFundFlowProvider 实例（已 mock TushareClient）"""
    return TushareFundFlowProvider()


# =========================================================================
# Provider 基础
# =========================================================================


class TestProviderBasics:
    """Provider 基础能力验证"""

    def test_instantiation(self, provider: TushareFundFlowProvider):
        """确认可以实例化"""
        assert isinstance(provider, BaseProvider)
        assert isinstance(provider, TushareFundFlowProvider)

    def test_capability(self, provider: TushareFundFlowProvider):
        """确认能力声明正确"""
        cap = provider.capability
        assert isinstance(cap, ProviderCapability)
        assert cap.name == "tushare"
        assert cap.can_moneyflow is True
        assert cap.can_hs_const is True
        assert cap.can_moneyflow_hsgt is True
        assert cap.can_hsgt_top10 is True
        assert cap.can_margin is True
        assert cap.can_top_list is True
        assert cap.coverage_start == "20000101"

    def test_self_check_no_network(self, provider: TushareFundFlowProvider, mocker):
        """离线环境自检不应抛异常"""
        # 模拟 _query 网络错误（所有 API 查询均失败）
        provider._client._query.side_effect = ConnectionError("模拟网络不可达")
        health = provider.self_check()
        assert isinstance(health, ProviderHealth)
        assert health.status in ("error", "partial")
        assert len(health.errors) > 0


# =========================================================================
# moneyflow — 个股资金流向
# =========================================================================


class TestMoneyflow:
    """个股资金流向"""

    MONEYFLOW_COLS = [
        "ts_code", "trade_date", "buy_sm_vol", "buy_sm_amount",
        "sell_sm_vol", "sell_sm_amount", "buy_md_vol", "buy_md_amount",
        "sell_md_vol", "sell_md_amount", "buy_lg_vol", "buy_lg_amount",
        "sell_lg_vol", "sell_lg_amount", "buy_elg_vol", "buy_elg_amount",
        "sell_elg_vol", "sell_elg_amount", "net_mf_amount", "net_mf_vol",
    ]

    def _make_moneyflow_df(self, n: int = 3) -> pd.DataFrame:
        """构造模拟 moneyflow 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": "688012.SH",
                "trade_date": f"202601{7+i:02d}",
                "buy_sm_vol": 1000 + i * 10,
                "buy_sm_amount": 5000.0 + i * 50,
                "sell_sm_vol": 800 + i * 10,
                "sell_sm_amount": 4000.0 + i * 50,
                "buy_md_vol": 2000 + i * 20,
                "buy_md_amount": 10000.0 + i * 100,
                "sell_md_vol": 1800 + i * 20,
                "sell_md_amount": 9000.0 + i * 100,
                "buy_lg_vol": 3000 + i * 30,
                "buy_lg_amount": 15000.0 + i * 150,
                "sell_lg_vol": 2800 + i * 30,
                "sell_lg_amount": 14000.0 + i * 150,
                "buy_elg_vol": 1500 + i * 15,
                "buy_elg_amount": 7500.0 + i * 75,
                "sell_elg_vol": 1200 + i * 15,
                "sell_elg_amount": 6000.0 + i * 75,
                "net_mf_amount": 1000.0 + i * 10,
                "net_mf_vol": 200 + i * 5,
            })
        return pd.DataFrame(rows)

    def test_moneyflow_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回个股资金流向"""
        mock_df = self._make_moneyflow_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.moneyflow(
            ts_code="688012.SH",
            start_date="20260101",
            end_date="20260131",
        )

        mock_ts_client._query.assert_called_once_with(
            "moneyflow",
            ts_code="688012.SH",
            start_date="20260101",
            end_date="20260131",
        )
        assert not result.empty
        assert len(result) == 3
        for col in self.MONEYFLOW_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

        # 验证排序
        assert result["trade_date"].is_monotonic_increasing

    def test_moneyflow_without_code(self, provider: TushareFundFlowProvider, mock_ts_client):
        """不带 ts_code 时也应正常调用（Tushare 支持）"""
        mock_ts_client._query.return_value = self._make_moneyflow_df()
        result = provider.moneyflow(start_date="20260101", end_date="20260131")
        assert not result.empty
        call_kwargs = mock_ts_client._query.call_args[1]
        assert "ts_code" not in call_kwargs

    def test_moneyflow_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.moneyflow(ts_code="688012.SH")
        assert result.empty

    def test_moneyflow_no_params(self, provider: TushareFundFlowProvider, mock_ts_client):
        """无参数调用不应抛异常"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.moneyflow()
        assert result.empty


# =========================================================================
# hs_const — 沪深港通标的
# =========================================================================


class TestHsConst:
    """沪深港通标的列表"""

    HS_CONST_COLS = ["ts_code", "name", "holder", "in_date", "out_date", "is_valid"]

    def _make_hs_const_df(self, n: int = 5) -> pd.DataFrame:
        """构造模拟 hs_const 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": f"600{100+i:03d}.SH",
                "name": f"测试标的{i}",
                "holder": "S",
                "in_date": "20200101",
                "out_date": "",
                "is_valid": "Y",
            })
        return pd.DataFrame(rows)

    def test_hs_const_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回沪深港通标的列表"""
        mock_df = self._make_hs_const_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.hs_const()

        mock_ts_client._query.assert_called_once_with("hs_const")
        assert not result.empty
        assert len(result) == 5
        for col in self.HS_CONST_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["in_date"])

    def test_hs_const_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.hs_const()
        assert result.empty

    def test_hs_const_out_date_nat(self, provider: TushareFundFlowProvider, mock_ts_client):
        """out_date 为空的应为 NaT"""
        df = self._make_hs_const_df()
        mock_ts_client._query.return_value = df
        result = provider.hs_const()
        assert result["out_date"].isna().all()


# =========================================================================
# moneyflow_hsgt — 沪深港通资金流向
# =========================================================================


class TestMoneyflowHsgt:
    """沪深港通资金流向"""

    MONEYFLOW_HSGT_COLS = [
        "trade_date", "ggt_ss", "ggt_sz", "ggt_amount",
        "hgt_sh", "hgt_sz",
    ]

    def _make_hsgt_df(self, n: int = 5) -> pd.DataFrame:
        """构造模拟 moneyflow_hsgt 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "trade_date": f"202601{7+i:02d}",
                "ggt_ss": 10.0 + i,
                "ggt_sz": 5.0 + i * 0.5,
                "ggt_amount": 15.0 + i * 1.5,
                "hgt_sh": 8.0 + i,
                "hgt_sz": 3.0 + i * 0.3,
            })
        return pd.DataFrame(rows)

    def test_moneyflow_hsgt_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回沪深港通资金流向"""
        mock_df = self._make_hsgt_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.moneyflow_hsgt(
            start_date="20260101",
            end_date="20260131",
        )

        mock_ts_client._query.assert_called_once_with(
            "moneyflow_hsgt",
            start_date="20260101",
            end_date="20260131",
        )
        assert not result.empty
        assert len(result) == 5
        for col in self.MONEYFLOW_HSGT_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化并按日期排序
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])
        assert result["trade_date"].is_monotonic_increasing

    def test_moneyflow_hsgt_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.moneyflow_hsgt(start_date="20260101", end_date="20260110")
        assert result.empty

    def test_moneyflow_hsgt_no_params(self, provider: TushareFundFlowProvider, mock_ts_client):
        """无参数调用应返回空（默认无参数时返回全部）"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.moneyflow_hsgt()
        assert result.empty


# =========================================================================
# hsgt_top10 — 沪深港通十大成交股
# =========================================================================


class TestHsgtTop10:
    """沪深港通十大成交股"""

    HSGT_TOP10_COLS = [
        "trade_date", "ts_code", "name", "close",
        "pct_change", "amount", "net_amount",
    ]

    def _make_hsgt_top10_df(self, n: int = 10) -> pd.DataFrame:
        """构造模拟 hsgt_top10 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "trade_date": "20260708",
                "ts_code": f"600{100+i:03d}.SH",
                "name": f"测试股{i}",
                "close": 50.0 + i,
                "pct_change": 2.0 + i * 0.1,
                "amount": 10000.0 - i * 500,
                "net_amount": 1000.0 - i * 100,
            })
        return pd.DataFrame(rows)

    def test_hsgt_top10_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回沪深港通十大成交股"""
        mock_df = self._make_hsgt_top10_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.hsgt_top10(trade_date="20260708", market_type="1")

        mock_ts_client._query.assert_called_once_with(
            "hsgt_top10",
            trade_date="20260708",
            market_type="1",
        )
        assert not result.empty
        assert len(result) == 10
        for col in self.HSGT_TOP10_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

        # 验证按成交额降序排列
        assert result["amount"].is_monotonic_decreasing

    def test_hsgt_top10_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.hsgt_top10(trade_date="99999999", market_type="1")
        assert result.empty

    def test_hsgt_top10_default_market_type(self, provider: TushareFundFlowProvider, mock_ts_client):
        """market_type 默认应该为 '1'"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.hsgt_top10(trade_date="20260708")
        assert result.empty  # mock 返回空，但参数验证通过
        _, kwargs = mock_ts_client._query.call_args
        assert kwargs["market_type"] == "1"

    def test_hsgt_top10_missing_trade_date(self, provider: TushareFundFlowProvider):
        """缺少 trade_date 应抛 ValueError"""
        with pytest.raises(ValueError, match="hsgt_top10 需要提供 trade_date"):
            provider.hsgt_top10()


# =========================================================================
# margin — 融资融券
# =========================================================================


class TestMargin:
    """融资融券交易汇总"""

    MARGIN_COLS = [
        "ts_code", "trade_date", "rzye", "rzmre", "rqye", "rqmcl",
    ]

    def _make_margin_df(self, n: int = 3) -> pd.DataFrame:
        """构造模拟 margin 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "ts_code": "688012.SH",
                "trade_date": f"202601{7+i:02d}",
                "rzye": 100000.0 + i * 1000,
                "rzmre": 5000.0 + i * 100,
                "rqye": 1000.0 + i * 10,
                "rqmcl": 100.0 + i * 5,
            })
        return pd.DataFrame(rows)

    def test_margin_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回融资融券数据"""
        mock_df = self._make_margin_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.margin(
            ts_code="688012.SH",
            start_date="20260101",
            end_date="20260131",
        )

        mock_ts_client._query.assert_called_once_with(
            "margin",
            ts_code="688012.SH",
            start_date="20260101",
            end_date="20260131",
        )
        assert not result.empty
        assert len(result) == 3
        for col in self.MARGIN_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

        # 验证排序
        assert result["trade_date"].is_monotonic_increasing

    def test_margin_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.margin(ts_code="688012.SH")
        assert result.empty

    def test_margin_no_params(self, provider: TushareFundFlowProvider, mock_ts_client):
        """无参数调用不应抛异常"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.margin()
        assert result.empty


# =========================================================================
# top_list — 龙虎榜
# =========================================================================


class TestTopList:
    """龙虎榜榜单"""

    TOP_LIST_COLS = [
        "trade_date", "ts_code", "name", "close",
        "pct_chg", "amount", "buy", "buy_rate",
        "sell", "sell_rate", "net_amount",
    ]

    def _make_top_list_df(self, n: int = 5) -> pd.DataFrame:
        """构造模拟 top_list 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "trade_date": "20260708",
                "ts_code": f"600{100+i:03d}.SH",
                "name": f"龙虎榜股{i}",
                "close": 30.0 + i * 2,
                "pct_chg": 10.0 + i,
                "amount": 20000.0 - i * 1000,
                "buy": 5000.0 - i * 200,
                "buy_rate": 25.0 - i,
                "sell": 3000.0 - i * 150,
                "sell_rate": 15.0 - i * 0.5,
                "net_amount": 2000.0 - i * 50,
            })
        return pd.DataFrame(rows)

    def test_top_list_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回龙虎榜榜单"""
        mock_df = self._make_top_list_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.top_list(trade_date="20260708")

        mock_ts_client._query.assert_called_once_with(
            "top_list",
            trade_date="20260708",
        )
        assert not result.empty
        assert len(result) == 5
        for col in self.TOP_LIST_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

    def test_top_list_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.top_list(trade_date="99999999")
        assert result.empty

    def test_top_list_missing_trade_date(self, provider: TushareFundFlowProvider):
        """缺少 trade_date 应抛 ValueError"""
        with pytest.raises(ValueError, match="top_list 需要提供 trade_date"):
            provider.top_list()


# =========================================================================
# top_inst — 龙虎榜机构交易明细
# =========================================================================


class TestTopInst:
    """龙虎榜机构交易明细"""

    TOP_INST_COLS = [
        "trade_date", "ts_code", "name",
        "buy", "buy_rate", "sell", "sell_rate", "net_buy",
    ]

    def _make_top_inst_df(self, n: int = 3) -> pd.DataFrame:
        """构造模拟 top_inst 返回值"""
        rows = []
        for i in range(n):
            rows.append({
                "trade_date": "20260708",
                "ts_code": f"600{100+i:03d}.SH",
                "name": f"机构股{i}",
                "buy": 3000.0 - i * 200,
                "buy_rate": 20.0 - i,
                "sell": 1000.0 - i * 100,
                "sell_rate": 8.0 - i * 0.5,
                "net_buy": 2000.0 - i * 100,
            })
        return pd.DataFrame(rows)

    def test_top_inst_normal(self, provider: TushareFundFlowProvider, mock_ts_client):
        """正常返回龙虎榜机构交易明细"""
        mock_df = self._make_top_inst_df()
        mock_ts_client._query.return_value = mock_df

        result = provider.top_inst(trade_date="20260708")

        mock_ts_client._query.assert_called_once_with(
            "top_inst",
            trade_date="20260708",
        )
        assert not result.empty
        assert len(result) == 3
        for col in self.TOP_INST_COLS:
            assert col in result.columns, f"缺少列: {col}"

        # 日期标准化
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

    def test_top_inst_empty(self, provider: TushareFundFlowProvider, mock_ts_client):
        """空返回处理"""
        mock_ts_client._query.return_value = pd.DataFrame()
        result = provider.top_inst(trade_date="99999999")
        assert result.empty

    def test_top_inst_missing_trade_date(self, provider: TushareFundFlowProvider):
        """缺少 trade_date 应抛 ValueError"""
        with pytest.raises(ValueError, match="top_inst 需要提供 trade_date"):
            provider.top_inst()


# =========================================================================
# Edge cases & data types
# =========================================================================


class TestEdgeCases:
    """边界情况"""

    def test_provider_is_subclass_of_base(self, provider: TushareFundFlowProvider):
        """确认是 BaseProvider 的子类"""
        assert isinstance(provider, BaseProvider)

    def test_all_implemented_outputs_are_dataframe(self, provider: TushareFundFlowProvider, mock_ts_client):
        """所有已实现方法返回类型均为 DataFrame"""
        mock_ts_client._query.return_value = pd.DataFrame()

        # 构造一个带 trade_date 的 mock DataFrame 给 hs_const
        def _side_effect(api_name, **kwargs):
            if api_name == "hs_const":
                return pd.DataFrame({"ts_code": [], "name": [], "holder": [],
                                     "in_date": [], "out_date": [], "is_valid": []})
            return pd.DataFrame()

        mock_ts_client._query.side_effect = _side_effect

        methods = [
            ("moneyflow", {}),
            ("hs_const", {}),
            ("moneyflow_hsgt", {}),
        ]
        for method_name, kwargs in methods:
            result = getattr(provider, method_name)(**kwargs)
            assert isinstance(result, pd.DataFrame), (
                f"{method_name} 返回值应为 DataFrame, 得到 {type(result)}"
            )

    def test_moneyflow_preserve_original_data(self, provider: TushareFundFlowProvider, mock_ts_client):
        """返回的 DataFrame 不应修改原始 mock 数据（测试 copy 语义）"""
        orig_df = pd.DataFrame({
            "ts_code": ["688012.SH"],
            "trade_date": ["20260107"],
            "buy_sm_vol": [1000],
            "buy_sm_amount": [5000.0],
            "sell_sm_vol": [800],
            "sell_sm_amount": [4000.0],
            "net_mf_amount": [1000.0],
        })
        mock_ts_client._query.return_value = orig_df
        result = provider.moneyflow(ts_code="688012.SH")

        # 原始数据的 trade_date 不应变成 datetime
        assert not pd.api.types.is_datetime64_any_dtype(orig_df["trade_date"]), (
            "原始数据的 trade_date 不应被修改为 datetime"
        )
        # 结果应是 datetime
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

    @pytest.mark.parametrize("method_name", [
        "stock_basic", "trade_cal", "daily", "daily_basic", "adj_factor",
        "stk_limit", "suspend", "namechange", "fina_indicator", "income",
        "balancesheet", "cashflow", "forecast", "index_daily",
        "dividend", "stk_surv", "block_trade", "new_share",
    ])
    def test_not_implemented_methods_raise(self, provider: TushareFundFlowProvider, method_name):
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
    def test_moneyflow_live(self):
        """真实环境：获取个股资金流向"""
        prov = TushareFundFlowProvider()
        df = prov.moneyflow(
            ts_code="688012.SH",
            start_date="20260701",
            end_date="20260708",
        )
        assert not df.empty
        assert "ts_code" in df.columns
        assert "trade_date" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])
        assert "net_mf_amount" in df.columns

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_hs_const_live(self):
        """真实环境：获取沪深港通标的列表"""
        prov = TushareFundFlowProvider()
        df = prov.hs_const()
        assert not df.empty
        assert "ts_code" in df.columns
        assert "in_date" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["in_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_moneyflow_hsgt_live(self):
        """真实环境：获取沪深港通资金流向"""
        prov = TushareFundFlowProvider()
        df = prov.moneyflow_hsgt(
            start_date="20260701",
            end_date="20260708",
        )
        assert not df.empty
        assert "trade_date" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])
        assert "ggt_amount" in df.columns

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_hsgt_top10_live(self):
        """真实环境：获取沪深港通十大成交股"""
        prov = TushareFundFlowProvider()
        df = prov.hsgt_top10(trade_date="20260708", market_type="1")
        if not df.empty:
            assert "ts_code" in df.columns
            assert "amount" in df.columns
            assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_margin_live(self):
        """真实环境：获取融资融券数据"""
        prov = TushareFundFlowProvider()
        df = prov.margin(
            ts_code="688012.SH",
            start_date="20260701",
            end_date="20260708",
        )
        if not df.empty:
            assert "rzye" in df.columns
            assert "rzmre" in df.columns
            assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_top_list_live(self):
        """真实环境：获取龙虎榜榜单"""
        prov = TushareFundFlowProvider()
        df = prov.top_list(trade_date="20260708")
        if not df.empty:
            assert "ts_code" in df.columns
            assert "amount" in df.columns
            assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_top_inst_live(self):
        """真实环境：获取龙虎榜机构交易明细"""
        prov = TushareFundFlowProvider()
        df = prov.top_inst(trade_date="20260708")
        if not df.empty:
            assert "ts_code" in df.columns
            assert "buy" in df.columns
            assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    @pytest.mark.skipif(not SMOKE_ENABLED, reason="需要 TUSHARE_SMOKE=1 环境变量启用")
    def test_self_check_live(self):
        """真实环境：自检"""
        prov = TushareFundFlowProvider()
        health = prov.self_check()
        assert health.status in ("ok", "partial")
        assert health.last_check
