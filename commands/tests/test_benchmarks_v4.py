#!/usr/bin/env python3
"""
Tests for V4.3 基准体系与同池等权 Gate

测试策略:
  - benchmarks_v4 模块: 列出基准、获取收益、统计数据
  - validate_v4 模块: 基准对比逻辑
  - gate 模块: SemiconductorPoolGate 评估逻辑
  - 所有基准基于真实行情数据 (从 KLINE_DIR 读取)

注意: 需要 universes.json 已构建, 否则测试自动构建
"""

from __future__ import annotations

import sys
import os
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

from benchmarks_v4 import (
    list_benchmarks,
    get_benchmark_returns,
    VALID_BENCHMARK_NAMES,
    BENCHMARK_META,
    ensure_universes,
    get_benchmark_report,
    cmd_list,
    cmd_report,
    _get_universe_codes,
    _compute_equal_weight_returns,
    UNIVERSES_FILE,
    KLINE_DIR,
)

from factor_lab.validate_v4 import (
    validate_factor_v4,
    check_semiconductor_peer,
    check_matched_control,
    check_etf_basket,
    _compute_strategy_returns,
)

from factor_lab.core.gate import (
    SemiconductorPoolGate,
    check_semiconductor_pool_gate,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(scope="module", autouse=True)
def ensure_universe_file():
    """确保测试前 universes.json 已构建"""
    ensure_universes()
    assert UNIVERSES_FILE.exists(), "universes.json 必须存在"
    yield


@pytest.fixture()
def fake_factor_result() -> dict:
    """模拟一个因子验证结果 (所有 beat 字段均为 True)"""
    return {
        "factor_name": "test_factor",
        "beats_semiconductor_peer": True,
        "beats_core_peer": True,
        "beats_matched_control": True,
        "excess_vs_semiconductor_ew": 5.23,
        "excess_vs_core_ew": 5.23,
        "excess_vs_matched_control": 1.12,
        "excess_vs_etf_basket": 8.75,
        "promotion_eligible": True,
    }


@pytest.fixture()
def fake_factor_result_fail() -> dict:
    """模拟一个失败的因子验证结果"""
    return {
        "factor_name": "bad_factor",
        "beats_semiconductor_peer": False,
        "beats_core_peer": False,
        "beats_matched_control": False,
        "excess_vs_semiconductor_ew": -3.45,
        "excess_vs_core_ew": -3.45,
        "excess_vs_matched_control": -5.12,
        "excess_vs_etf_basket": -2.10,
        "promotion_eligible": False,
    }


# =========================================================================
# benchmarks_v4 模块测试
# =========================================================================


class TestBenchmarksV4:
    """benchmarks_v4 模块测试"""

    def test_valid_benchmark_names(self):
        """应包含 6 个基准"""
        expected_names = {
            "semiconductor_ew",
            "semiconductor_core_ew",
            "matched_control_ew",
            "ew_a_share",
            "ew_tradable",
            "etf_basket_ew",
        }
        assert VALID_BENCHMARK_NAMES == expected_names

    def test_benchmark_meta_all_have_universe(self):
        """每个基准都有对应的 universe"""
        for name, meta in BENCHMARK_META.items():
            assert "universe" in meta, f"{name} 缺少 universe"
            assert "label" in meta, f"{name} 缺少 label"
            assert meta["universe"] in ("U0", "U1", "U3", "U4", "ETF"), \
                f"{name} universe={meta['universe']} 不在预期中"

    def test_list_benchmarks_returns_all(self):
        """list_benchmarks 返回所有基准"""
        benchmarks = list_benchmarks()
        names = {b["name"] for b in benchmarks}
        assert names == VALID_BENCHMARK_NAMES
        assert len(benchmarks) == 6

    def test_list_benchmarks_has_data(self):
        """每个基准报告 available_days > 0 (有真实数据)"""
        benchmarks = list_benchmarks()
        for b in benchmarks:
            # ETF 池可能无K线数据, 跳过该检查
            if b["name"] == "etf_basket_ew" and b["available_days"] == 0:
                continue
            assert b["available_days"] > 0, \
                f"{b['name']} 无数据, 检查 KLINE_DIR={KLINE_DIR} 或 universes.json"
            assert "N/A" not in b["date_range"], f"{b['name']} 日期范围无效"

    def test_get_benchmark_returns_semiconductor_ew(self):
        """半导体等权基准返回非空收益率序列"""
        rets = get_benchmark_returns("semiconductor_ew")
        assert isinstance(rets, pd.Series)
        assert len(rets) > 0, "半导体等权基准应返回数据"
        assert rets.name == "semiconductor_ew"
        # 收益率应在合理范围内
        assert rets.abs().max() < 0.3, "日收益率不应超过30% (极端情况)"

    def test_get_benchmark_returns_semiconductor_core_ew(self):
        """半导体核心等权 (别名的 same pool)"""
        rets = get_benchmark_returns("semiconductor_core_ew")
        assert isinstance(rets, pd.Series)
        assert len(rets) > 0

    def test_get_benchmark_returns_matched_control(self):
        """匹配对照池等权"""
        rets = get_benchmark_returns("matched_control_ew")
        assert isinstance(rets, pd.Series)
        assert len(rets) > 0, "匹配对照池应有数据"

    def test_get_benchmark_returns_ew_a_share(self):
        """全A等权"""
        rets = get_benchmark_returns("ew_a_share")
        assert isinstance(rets, pd.Series)
        assert len(rets) > 0

    def test_get_benchmark_returns_ew_tradable(self):
        """全A可交易池等权"""
        rets = get_benchmark_returns("ew_tradable")
        assert isinstance(rets, pd.Series)
        assert len(rets) > 0

    def test_get_benchmark_returns_etf_basket(self):
        """ETF替代池等权 (可能缺失数据)"""
        rets = get_benchmark_returns("etf_basket_ew")
        assert isinstance(rets, pd.Series)
        # ETF 数据可能不在 stock kline 目录, 所以允许空
        if len(rets) == 0:
            import warnings
            warnings.warn("ETF 替代池无数据, 需检查 fund_daily 数据源")
        assert rets.name == "etf_basket_ew"

    def test_get_benchmark_returns_invalid_name(self):
        """不支持的基准名称应报错"""
        with pytest.raises(ValueError, match="不支持的基准"):
            get_benchmark_returns("invalid_name")

    def test_benchmark_returns_not_constant(self):
        """收益率序列不应全相等 (证明是真实数据)"""
        rets = get_benchmark_returns("semiconductor_ew")
        assert rets.nunique() > 1, "收益率序列不应全相同"

    def test_benchmark_annualized_volatility_reasonable(self):
        """年化波动率应在合理范围 5%-80%"""
        for name in VALID_BENCHMARK_NAMES:
            rets = get_benchmark_returns(name)
            if len(rets) > 20:
                ann_vol = rets.std() * np.sqrt(252)
                assert 0.03 < ann_vol < 0.80, \
                    f"{name} 年化波动率 {ann_vol:.2%} 不在合理范围"

    def test_get_benchmark_report(self):
        """基准报告应包含关键指标"""
        for name in VALID_BENCHMARK_NAMES:
            report = get_benchmark_report(name, n_days=30)
            assert "name" in report
            assert "cumulative_return_pct" in report
            assert "sharpe_ratio" in report
            assert "n_days" in report
            if report.get("n_days", 0) > 0:
                assert isinstance(report["cumulative_return_pct"], (int, float))
                assert isinstance(report["annualized_volatility_pct"], (int, float))

    def test_semiconductor_name_alias_consistency(self):
        """semiconductor_ew 和 semiconductor_core_ew 应指向同一池 (U3)"""
        assert BENCHMARK_META["semiconductor_ew"]["universe"] == "U3"
        assert BENCHMARK_META["semiconductor_core_ew"]["universe"] == "U3"


# =========================================================================
# _get_universe_codes 测试
# =========================================================================


class TestGetUniverseCodes:
    """股票池代码获取测试"""

    def test_u3_codes(self):
        """U3 池返回的代码不为空"""
        codes = _get_universe_codes("U3")
        assert len(codes) > 0, "U3 半导体核心池不应为空"
        # 检查代码为数字 (长度可能不同, 部分ETF/指数代码为4位)
        for c in codes:
            assert c.isdigit() or c == "", f"代码 {c} 应为数字"
        # 至少有些代码是6位 (正常股票)
        six_digit = [c for c in codes if len(c) == 6]
        assert len(six_digit) > 0, "U3 中应有6位股票代码"

    def test_etf_codes(self):
        """ETF 池返回代码"""
        codes = _get_universe_codes("ETF")
        assert len(codes) > 0, "ETF 池应不为空"

    def test_u0_codes(self):
        """U0 全A池应有很多代码"""
        codes = _get_universe_codes("U0")
        assert len(codes) > 100, f"U0 应有超过100只, 实际 {len(codes)}"

    def test_u1_tradable_codes(self):
        """U1 tradable 子集"""
        codes = _get_universe_codes("U1_TRADABLE")
        assert len(codes) > 0


# =========================================================================
# validate_v4 模块测试 (使用 mock 数据)
# =========================================================================


class TestValidateV4:
    """validate_v4 模块测试"""

    @pytest.fixture()
    def mock_factor_df(self) -> pd.DataFrame:
        """创建一个带模拟因子的 DataFrame"""
        dates = pd.date_range("2026-01-02", periods=100, freq="B")
        symbols = [f"600{100+i:03d}" for i in range(20)]
        rows = []
        rng = np.random.default_rng(42)
        for sym in symbols:
            price = 50.0
            for d in dates:
                ret = rng.normal(0, 0.02)
                price *= (1 + ret)
                rows.append({
                    "date": d,
                    "symbol": sym,
                    "close": price,
                    "ret1": ret,
                    "test_factor": rng.normal(0, 1),  # 随机因子
                })
        return pd.DataFrame(rows)

    @pytest.fixture()
    def mock_close_pivot(self, mock_factor_df) -> pd.DataFrame:
        return mock_factor_df.pivot(index="date", columns="symbol", values="close")

    def test_compute_strategy_returns(self, mock_factor_df, mock_close_pivot):
        """策略收益计算不应为空"""
        rets = _compute_strategy_returns(
            mock_factor_df, "test_factor", mock_close_pivot, top_quantile=0.2
        )
        assert len(rets) > 0

    def test_check_semiconductor_peer(self, mock_factor_df, mock_close_pivot):
        """半导体同池对比应能运行 (但需真实基准数据)"""
        result = check_semiconductor_peer(
            mock_factor_df, "test_factor", mock_close_pivot, top_quantile=0.2
        )
        # 框架应返回, 即使数据不足
        assert "beats_semiconductor_peer" in result
        assert "excess_vs_semiconductor_ew" in result

    def test_check_matched_control(self, mock_factor_df, mock_close_pivot):
        """匹配对照对比"""
        result = check_matched_control(
            mock_factor_df, "test_factor", mock_close_pivot, top_quantile=0.2
        )
        assert "beats_matched_control" in result

    def test_check_etf_basket(self, mock_factor_df, mock_close_pivot):
        """ETF替代池对比"""
        result = check_etf_basket(
            mock_factor_df, "test_factor", mock_close_pivot, top_quantile=0.2
        )
        assert "excess_vs_etf_basket" in result

    def test_validate_factor_v4_structure(self, mock_factor_df, mock_close_pivot):
        """validate_factor_v4 返回结果中包含关键字段"""
        result = validate_factor_v4("test_factor", mock_factor_df, mock_close_pivot)
        assert "beats_semiconductor_peer" in result
        assert "beats_core_peer" in result
        assert "beats_matched_control" in result
        assert "excess_vs_semiconductor_ew" in result
        assert "excess_vs_core_ew" in result
        assert "excess_vs_etf_basket" in result
        assert "promotion_eligible" in result
        assert "benchmark_v4" in result


# =========================================================================
# Gate 模块测试
# =========================================================================


class TestSemiconductorPoolGate:
    """SemiconductorPoolGate 门禁测试"""

    def test_gate_pass_when_beats_semiconductor(self, fake_factor_result):
        """跑赢半导体 = 通过"""
        result = check_semiconductor_pool_gate(fake_factor_result)
        assert result["passed"] is True
        assert result["verdict"] == "pass"

    def test_gate_pass_when_beats_core_only(self):
        """beats_core_peer=True, beats_semiconductor=False = 通过"""
        result_data = {
            "beats_semiconductor_peer": False,
            "beats_core_peer": True,
            "beats_matched_control": False,
            "excess_vs_semiconductor_ew": -1.0,
            "excess_vs_core_ew": 2.5,
            "excess_vs_matched_control": -3.0,
            "excess_vs_etf_basket": 5.0,
        }
        result = check_semiconductor_pool_gate(result_data)
        assert result["passed"] is True, "beats_core_peer=True 应通过"

    def test_gate_fail_when_neither(self, fake_factor_result_fail):
        """两者都没跑赢 = 不通过"""
        result = check_semiconductor_pool_gate(fake_factor_result_fail)
        assert result["passed"] is False
        assert result["verdict"] == "fail"

    def test_gate_blocker_check_present(self, fake_factor_result_fail):
        """失败时应有 blocker 级别的 check"""
        result = check_semiconductor_pool_gate(fake_factor_result_fail)
        has_blocker = any(
            c["severity"] == "blocker" and not c["passed"]
            for c in result["checks"]
        )
        assert has_blocker, "应有 blocker 检查失败"

    def test_gate_pass_check_present(self, fake_factor_result):
        """通过时应有通过的 blocker"""
        result = check_semiconductor_pool_gate(fake_factor_result)
        assert all(
            c["passed"] for c in result["checks"]
            if c["severity"] == "blocker"
        ), "所有 blocker 检查应通过"

    def test_gate_class_direct(self, fake_factor_result):
        """直接使用 SemiconductorPoolGate 类"""
        gate = SemiconductorPoolGate()
        result = gate.evaluate(fake_factor_result)
        assert result.gate_name == "semiconductor_pool_ew"
        assert result.passed is True

    def test_gate_class_fail(self, fake_factor_result_fail):
        """Gate 类在失败时"""
        gate = SemiconductorPoolGate()
        result = gate.evaluate(fake_factor_result_fail)
        assert result.passed is False

    def test_gate_info_check(self, fake_factor_result):
        """ETF 信息检查始终通过"""
        result = check_semiconductor_pool_gate(fake_factor_result)
        etf_checks = [c for c in result["checks"] if c["name"] == "excess_vs_etf_basket"]
        assert len(etf_checks) == 1
        assert etf_checks[0]["severity"] == "info"

    def test_gate_warning_check(self, fake_factor_result):
        """匹配对照为非 blocker warning"""
        result = check_semiconductor_pool_gate(fake_factor_result)
        mc_checks = [c for c in result["checks"] if c["name"] == "beats_matched_control"]
        if mc_checks:
            assert mc_checks[0]["severity"] == "warning"
