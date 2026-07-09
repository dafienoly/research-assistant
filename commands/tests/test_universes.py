#!/usr/bin/env python3
"""
Tests for V4.1 分层股票池 U0-U4 + ETF替代池

测试策略:
  - 核心逻辑通过 mock TushareClient._query 验证
  - 测试 ETF 替代池时无需 mock (纯逻辑)
  - U0-U4 构建逻辑验证参数和返回值
"""

from __future__ import annotations

import sys
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pytest
import pandas as pd
import numpy as np

# 确保能找到 commands 包
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)  # commands/
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from universes import (
    build_u0,
    build_u1,
    build_u2,
    build_u3,
    build_u4,
    build_etf_pool,
    build_all,
    list_universes,
    audit,
    get_universe,
    _ts_code_to_symbol,
    _symbol_to_ts_code,
    _parse_board,
    _is_st_from_name,
    _is_delisted,
    _is_delisted_from_name,
    _classify_semiconductor_subsector,
    _compute_core_score,
    _compute_domestic_substitution_score,
    _compute_supply_chain_position,
    ETF_REPLACEMENT_POOL,
    OUTPUT_FILE,
)

CST = timezone(timedelta(hours=8))


# =========================================================================
# Helpers
# =========================================================================


def _mock_stock_basic_df(n: int = 5, include_all_cols: bool = True) -> pd.DataFrame:
    """构造模拟 stock_basic 返回值"""
    rows = []
    for i in range(n):
        rows.append({
            "ts_code": f"600{100+i:03d}.SH",
            "name": f"测试股票{i}",
            "area": "上海",
            "industry": "信息技术" if i < 2 else "电子",
            "market": "主板",
            "list_date": "20100101",
            "delist_date": "" if i > 0 else "20990101",
            "is_hs": "S" if i % 2 == 0 else "",
        })
    return pd.DataFrame(rows)


def _mock_daily_basic_df(n: int = 5) -> pd.DataFrame:
    """构造模拟 daily_basic 返回值"""
    rows = []
    for i in range(n):
        rows.append({
            "ts_code": f"600{100+i:03d}.SH",
            "trade_date": "20260708",
            "total_mv": 100.0 * (i + 1) * 1e8,
            "circ_mv": 50.0 * (i + 1) * 1e8,
            "turnover_rate": 2.0 + i * 0.5,
            "amount": 1e8 * (i + 1),
        })
    return pd.DataFrame(rows)


def _mock_trade_cal_df() -> pd.DataFrame:
    """构造模拟 trade_cal 返回值"""
    rows = []
    for i in range(10):
        from datetime import datetime
        d = datetime(2026, 7, 1 + i)
        is_open = 0 if d.weekday() >= 5 else 1
        rows.append({
            "exchange": "SSE",
            "cal_date": d.strftime("%Y%m%d"),
            "is_open": is_open,
            "pretrade_date": (datetime(2026, 7, i)).strftime("%Y%m%d") if i > 0 else "",
        })
    return pd.DataFrame(rows)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def clear_universe_output():
    """清除缓存的 universes.json 保证每次测试重新构建"""
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    yield
    # 清理
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()


@pytest.fixture()
def mock_ts_client_minimal(mocker):
    """Mock TushareClient — 仅返回 stock_basic + trade_cal"""
    from universes import _ts_client_mod

    mock = mocker.patch.object(_ts_client_mod, "get_ts_client", autospec=True)
    client = mock.return_value

    # stock_basic 返回少量数据
    client.stock_basic.return_value = _mock_stock_basic_df(5)
    # trade_cal 返回数据
    client.trade_cal.return_value = _mock_trade_cal_df()
    # _query 默认返回空
    client._query.return_value = pd.DataFrame()
    return client


# =========================================================================
# 工具函数测试
# =========================================================================


class TestHelpers:
    """工具函数测试"""

    def test_ts_code_to_symbol(self):
        assert _ts_code_to_symbol("688012.SH") == "688012"
        assert _ts_code_to_symbol("000001.SZ") == "000001"
        assert _ts_code_to_symbol("830799.BJ") == "830799"

    def test_symbol_to_ts_code(self):
        assert _symbol_to_ts_code("688012", "SSE") == "688012.SH"
        assert _symbol_to_ts_code("000001", "SZSE") == "000001.SZ"
        assert _symbol_to_ts_code("830799") == "830799.BJ"
        assert _symbol_to_ts_code("600000") == "600000.SH"
        assert _symbol_to_ts_code("300000") == "300000.SZ"
        assert _symbol_to_ts_code("688012.SH") == "688012.SH"  # already full

    def test_parse_board(self):
        assert _parse_board("主板") == "主板"
        assert _parse_board("创业板") == "创业板"
        assert _parse_board("科创板") == "科创板"
        assert _parse_board("北交所") == "北交所"
        assert _parse_board("Main") == "主板"

    def test_is_st_from_name(self):
        assert _is_st_from_name("ST华仪")
        assert _is_st_from_name("*ST中微")
        assert _is_st_from_name("SST佳通")
        assert not _is_st_from_name("中微公司")
        assert not _is_st_from_name("贵州茅台")
        assert not _is_st_from_name("")


# =========================================================================
# ETF 替代池
# =========================================================================


class TestETFPool:
    """ETF 替代池测试"""

    def test_etf_pool_size(self):
        """ETF 替代池至少 10 只"""
        result = build_etf_pool()
        assert result["total_stocks"] >= 10
        assert result["name"] == "ETF"
        assert result["label"] == "ETF替代池"

    def test_etf_has_required_fields(self):
        """每条 ETF 记录有代码/名称/费率/跟踪指数"""
        result = build_etf_pool()
        for etf in result["stocks"]:
            assert "ts_code" in etf
            assert "name" in etf
            assert "management_fee_pct" in etf
            assert "track_index" in etf
            assert etf["ts_code"]  # 非空

    def test_etf_dedup(self):
        """ETF 替代池无重复 ts_code"""
        result = build_etf_pool()
        codes = [e["ts_code"] for e in result["stocks"]]
        assert len(codes) == len(set(codes)), f"发现重复代码: {codes}"


# =========================================================================
# U0 全A基础池
# =========================================================================


class TestU0:
    """U0 全A基础池测试"""

    def test_u0_build_fails_without_data(self, mocker):
        """无 Tushare 数据时应该报错"""
        from universes import _ts_client_mod
        mock = mocker.patch.object(_ts_client_mod, "get_ts_client", autospec=True)
        mock.return_value.stock_basic.return_value = pd.DataFrame()
        mock.return_value.trade_cal.return_value = pd.DataFrame()

        with pytest.raises(RuntimeError, match="stock_basic 返回空"):
            build_u0()

    def test_u0_basic_structure(self, mock_ts_client_minimal):
        """U0 基本结构验证"""
        # 配置 stock_basic 返回数据
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5),  # L
            pd.DataFrame(),  # D
            pd.DataFrame(),  # P
        ]

        result = build_u0()
        assert result["name"] == "U0"
        assert result["label"] == "全A基础池"
        assert result["total_stocks"] == 5
        assert "stocks" in result
        assert len(result["stocks"]) == 5

    def test_u0_fields(self, mock_ts_client_minimal):
        """U0 股票包含所有必需字段"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(3),
            pd.DataFrame(),
            pd.DataFrame(),
        ]

        result = build_u0()
        required_fields = [
            "ts_code", "symbol", "name", "exchange", "board",
            "list_date", "delist_date", "is_listed", "industry",
            "concepts", "total_mv", "float_mv",
        ]
        for s in result["stocks"]:
            for field in required_fields:
                assert field in s, f"缺少字段: {field}"

    def test_u0_data_sources(self, mock_ts_client_minimal):
        """U0 数据来源声明"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(3),
            pd.DataFrame(),
            pd.DataFrame(),
        ]

        result = build_u0()
        assert len(result["data_sources"]) >= 1
        assert "Tushare stock_basic" in result["data_sources"]


# =========================================================================
# U1 用户可交易池
# =========================================================================


class TestU1:
    """U1 用户可交易池测试"""

    def test_u1_basic_structure(self, mock_ts_client_minimal):
        """U1 基本结构与 U0 一致（过滤后 U1 ⊆ U0）"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(3),
            pd.DataFrame(),
            pd.DataFrame(),
        ]

        result = build_u1()
        assert result["name"] == "U1"
        assert result["label"] == "用户可交易池"
        assert "filtered_counts" in result
        # 第1只股票有 delist_date → 被过滤 → 剩2只
        assert result["total_stocks"] == 2

    def test_u1_fields(self, mock_ts_client_minimal):
        """U1 股票包含所有交易标记+扩展字段"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(2),
            pd.DataFrame(),
            pd.DataFrame(),
        ]

        result = build_u1()
        required_fields = [
            "ts_code", "symbol", "name", "board",
            "is_mainboard", "is_chinext", "is_star", "is_bse",
            "is_st", "is_suspended",
            "industry", "industry_missing_reason",
            "concepts", "concepts_lineage",
            "total_mv", "float_mv", "turnover_rate", "amount", "pe", "pb",
            "avg_amount_20d",
        ]
        for s in result["stocks"]:
            for field in required_fields:
                assert field in s, f"缺少字段: {field}"

    def test_u1_filter_delisted_stocks(self):
        """验证 U1 过滤退市股票 — 直接测试辅助函数"""
        assert _is_delisted_from_name("退市股票") is True
        assert _is_delisted_from_name("正常股票") is False
        assert _is_delisted_from_name("*ST中微") is False  # ST is not 退

        assert _is_delisted({"is_listed": False, "delist_date": ""}) is True
        assert _is_delisted({"is_listed": True, "delist_date": "NaT"}) is False
        assert _is_delisted({"is_listed": True, "delist_date": ""}) is False
        assert _is_delisted({"is_listed": True, "delist_date": "20250101"}) is True


# =========================================================================
# U2 AI/半导体广义池
# =========================================================================


class TestU2:
    """U2 AI/半导体广义池测试"""

    def test_u2_basic_structure(self, mock_ts_client_minimal):
        """U2 基本结构"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5),
            pd.DataFrame(),
            pd.DataFrame(),
        ]

        result = build_u2()
        assert result["name"] == "U2"
        assert result["label"] == "AI/半导体广义池"
        assert "total_stocks" in result

    def test_u2_fields(self, mock_ts_client_minimal):
        """U2 股票包含所有必需字段"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(3),
            pd.DataFrame(),
            pd.DataFrame(),
        ]

        result = build_u2()
        required_fields = [
            "ts_code", "symbol",
            "source_atlas", "source_concept", "source_etf_holding",
            "source_industry", "source_manual",
            "source_confidence", "ai_chain_layer",
            "theme_tags", "is_broad_ai_semiconductor",
        ]
        for s in result["stocks"]:
            for field in required_fields:
                assert field in s, f"缺少字段: {field}"


# =========================================================================
# U3 半导体核心池
# =========================================================================


class TestU3:
    """U3 半导体核心池测试"""

    def test_subsector_classification(self):
        """细分方向分类测试"""
        subsectors = _classify_semiconductor_subsector(
            "中微公司", "半导体", ["芯片", "国产替代"], "刻蚀设备", "L2"
        )
        assert "设备" in subsectors  # 刻蚀设备匹配设备

        # 制造类
        subsectors2 = _classify_semiconductor_subsector(
            "中芯国际", "半导体", ["芯片"], "晶圆代工", "L1"
        )
        assert "制造" in subsectors2

    def test_core_score_range(self):
        """核心度评分在 0.0-1.0 范围内"""
        assert 0.0 <= _compute_core_score(["设备"], "L2", "high") <= 1.0
        assert 0.0 <= _compute_core_score([], "", "low") <= 1.0
        # 有细分+L1/L2+high → 高核心度
        high = _compute_core_score(["设备", "设计"], "L1", "high")
        low = _compute_core_score([], "L5", "low")
        assert high > low

    def test_domestic_substitution_score(self):
        """国产替代评分"""
        score = _compute_domestic_substitution_score(
            "中微公司", "半导体", ["芯片", "国产替代"]
        )
        assert score > 0

        score2 = _compute_domestic_substitution_score(
            "招商银行", "银行", []
        )
        assert score2 == 0

    def test_supply_chain_position(self):
        """供应链位置推断"""
        pos = _compute_supply_chain_position(["设备", "材料"], "", "")
        assert "上游" in pos

        pos2 = _compute_supply_chain_position(["设计", "制造"], "", "")
        assert "中游" in pos2

    def test_u3_basic_structure(self, mock_ts_client_minimal):
        """U3 基本结构"""
        # return_value to avoid side_effect exhaustion across nested build_u0 calls
        mock_ts_client_minimal.stock_basic.return_value = _mock_stock_basic_df(10)

        result = build_u3()
        assert result["name"] == "U3"
        assert result["label"] == "半导体核心池"
        assert "total_stocks" in result

    def test_u3_fields(self, mock_ts_client_minimal):
        """U3 股票字段验证"""
        mock_ts_client_minimal.stock_basic.return_value = _mock_stock_basic_df(10)

        result = build_u3()
        if result["stocks"]:
            s = result["stocks"][0]
            assert "ts_code" in s
            assert "symbol" in s
            assert "semiconductor_subsector" in s
            assert "core_score" in s
            assert "domestic_substitution_score" in s
            assert "supply_chain_position" in s


# =========================================================================
# U4 匹配对照池
# =========================================================================


class TestU4:
    """U4 匹配对照池测试"""

    def test_u4_basic_structure(self, mock_ts_client_minimal):
        """U4 基本结构"""
        mock_ts_client_minimal.stock_basic.return_value = _mock_stock_basic_df(20)

        result = build_u4(min_matches=1, max_matches=2)
        assert result["name"] == "U4"
        assert result["label"] == "匹配对照池"
        assert "total_stocks" in result
        assert "matched_total" in result

    def test_u4_stock_structure(self, mock_ts_client_minimal):
        """U4 每条匹配记录结构"""
        mock_ts_client_minimal.stock_basic.return_value = _mock_stock_basic_df(20)

        result = build_u4(min_matches=1, max_matches=2)
        if result["stocks"]:
            s = result["stocks"][0]
            assert "u3_ts_code" in s
            assert "u3_symbol" in s
            assert "matched_stocks" in s
            assert "match_count" in s


# =========================================================================
# 统一构建与审计
# =========================================================================


class TestBuildAll:
    """统一构建测试"""

    def test_build_all_creates_output(self, mock_ts_client_minimal):
        """build_all 创建 universes.json"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5),  # U0 - L
            pd.DataFrame(),           # U0 - D
            pd.DataFrame(),           # U0 - P
            _mock_stock_basic_df(5),  # U1 - L
            pd.DataFrame(),           # U1 - D
            pd.DataFrame(),           # U1 - P
            _mock_stock_basic_df(5),  # U2 - L
            pd.DataFrame(),           # U2 - D
            pd.DataFrame(),           # U2 - P
            _mock_stock_basic_df(5),  # U3 - L
            pd.DataFrame(),           # U3 - D
            pd.DataFrame(),           # U3 - P
            _mock_stock_basic_df(10), # U4 - L
            pd.DataFrame(),           # U4 - D
            pd.DataFrame(),           # U4 - P
        ]
        result = build_all()
        assert OUTPUT_FILE.exists()
        assert "meta" in result
        assert result["meta"]["version"] == "4.1"
        assert "universes" in result

    def test_list_universes(self, mock_ts_client_minimal):
        """列出所有股票池"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(10), pd.DataFrame(), pd.DataFrame(),
        ]
        names = list_universes()
        assert "U0" in names
        assert "U1" in names
        assert "U2" in names
        assert "U3" in names
        assert "U4" in names
        assert "ETF" in names

    def test_get_universe(self, mock_ts_client_minimal):
        """获取指定股票池"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(10), pd.DataFrame(), pd.DataFrame(),
        ]
        u0 = get_universe("U0")
        assert u0["name"] == "U0"

        etf = get_universe("ETF")
        assert etf["name"] == "ETF"

    def test_get_universe_invalid(self, mock_ts_client_minimal):
        """获取不存在的股票池报错"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(10), pd.DataFrame(), pd.DataFrame(),
        ]
        with pytest.raises(KeyError, match="U99"):
            get_universe("U99")

    def test_audit(self, mock_ts_client_minimal):
        """审计报告基本结构"""
        mock_ts_client_minimal.stock_basic.side_effect = [
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(5), pd.DataFrame(), pd.DataFrame(),
            _mock_stock_basic_df(10), pd.DataFrame(), pd.DataFrame(),
        ]
        report = audit()
        assert "audited_at" in report
        assert "summary" in report
        assert "details" in report
        for name in ("U0", "U1", "U2", "U3", "U4", "ETF"):
            assert name in report["details"]
        assert report["summary"]["total_universes"] == 6


# =========================================================================
# Edge Cases
# =========================================================================


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_stock_basic_all_status(self, mock_ts_client_minimal):
        """所有 stock_basic 状态返回空应报错"""
        mock_ts_client_minimal.stock_basic.return_value = pd.DataFrame()
        with pytest.raises(RuntimeError):
            build_u0()

    def test_etf_pool_no_mock_needed(self):
        """ETF 替代池不需要任何 mock"""
        result = build_etf_pool()
        assert result["total_stocks"] >= 10

    def test_subsector_classification_fallback(self):
        """无明确细分方向时的兜底分类"""
        subsectors = _classify_semiconductor_subsector(
            "某某通用公司", "未知行业", [], "", ""
        )
        assert isinstance(subsectors, list)

    def test_core_score_low(self):
        """空输入时的最低核心度"""
        score = _compute_core_score([], "", "low")
        assert score >= 0.1  # low confidence 至少 0.1

    def test_supply_chain_default(self):
        """默认供应链位置"""
        pos = _compute_supply_chain_position([], "", "")
        assert "中游" in pos
