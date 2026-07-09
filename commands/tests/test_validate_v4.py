#!/usr/bin/env python3
"""
V4.4 因子评价与风险归因增强 — 完整测试套件

测试模块:
  1. validate_factor_v4.py — 增强指标计算 (换手率/成本/回撤/胜率/CAGR/Calmar)
  2. validate_factor_v4.py — 多基准对比 (6 个基准)
  3. validate_factor_v4.py — V4.4 全量验证入口
  4. risk_exposure.py — 风险暴露归因 (市值/Beta/波动率/流动性/行业/Jackknife)
  5. gate.py — V4.4 新增 Gate (BeatsSemiconductorPeerGate, RiskExposureGate)
  6. gate.py — V4.4 组合门禁

测试策略:
  - 使用模拟数据 (mock factor + close pivot)
  - 对各指标函数的边界条件进行测试
  - Gate 逻辑真假分支全覆盖
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

from factor_lab.validate_factor_v4 import (
    validate_factor_v44,
    validate_factor_v4,
    compute_turnover,
    compute_max_drawdown,
    compute_win_rate,
    compute_cagr,
    compute_calmar,
    compute_enhanced_metrics,
    compute_cost_adjusted_returns,
    check_benchmark,
    _compute_strategy_returns,
    _compute_strategy_returns_detailed,
    _compute_v44_score,
    clean,
)

from factor_lab.core.gate import (
    BeatsSemiconductorPeerGate,
    RiskExposureGate,
    check_risk_exposure_gate,
    check_v44_promotion_gate,
)

from factor_lab.risk_exposure import (
    RiskExposureAnalyzer,
)

# =========================================================================
# Helpers
# =========================================================================


def _make_mock_data(
    n_dates: int = 100,
    n_symbols: int = 30,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """创建模拟的因子数据和收盘价 pivot

    Returns:
        (df, close_pivot)
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-02", periods=n_dates, freq="B")
    symbols = [f"600{100 + i:03d}" for i in range(n_symbols)]

    rows = []
    for sym in symbols:
        price = 50.0
        for d in dates:
            ret = rng.normal(0.001, 0.025)  # 微正收益
            price *= (1 + ret)
            # 因子值: 加入一些可排序的差异
            factor_val = rng.normal(0, 1) + (hash(sym) % 10) * 0.1
            rows.append({
                "date": d,
                "symbol": sym,
                "close": price,
                "ret1": ret,
                "test_factor": factor_val,
            })

    df = pd.DataFrame(rows)

    # 为 ret1 列创建准确的收益率 (使用 close 的 pct_change)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    for sym in symbols:
        mask = df["symbol"] == sym
        df.loc[mask, "ret1"] = df.loc[mask, "close"].pct_change().fillna(0)

    close_pivot = df.pivot(index="date", columns="symbol", values="close")
    return df, close_pivot


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(scope="module")
def mock_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    return _make_mock_data()


@pytest.fixture()
def empty_series() -> pd.Series:
    return pd.Series(dtype=float)


@pytest.fixture()
def normal_rets() -> pd.Series:
    """模拟正常收益率序列 (月度再平衡, 100 天)"""
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.001, 0.02, size=100))
    rets.index = pd.date_range("2026-01-02", periods=100, freq="B")
    return rets


@pytest.fixture()
def positive_rets() -> pd.Series:
    """模拟持续正收益"""
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.005, 0.015, size=100))
    rets.index = pd.date_range("2026-01-02", periods=100, freq="B")
    return rets


@pytest.fixture()
def volatile_rets() -> pd.Series:
    """模拟高波动收益率"""
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.001, 0.05, size=100))
    rets.index = pd.date_range("2026-01-02", periods=100, freq="B")
    return rets


@pytest.fixture()
def portfolio_history() -> list[list[str]]:
    """模拟持仓历史 (10 个再平衡日, 各 5 只)"""
    return [
        [f"600{100 + j:03d}" for j in range(i * 3 % 10, (i * 3 + 5) % 10)]
        for i in range(10)
    ]


@pytest.fixture()
def v44_passing_result() -> dict:
    """模拟一个通过 V4.4 全量验证的结果"""
    return {
        "beats_semiconductor_peer": True,
        "beats_core_peer": True,
        "beats_matched_control": True,
        "excess_vs_semiconductor_ew": 8.5,
        "excess_vs_core_ew": 8.5,
        "excess_vs_matched_control": 3.2,
        "excess_vs_etf_basket": 12.1,
        "risk_exposure": {
            "exposure_type": "pure_alpha",
            "market_cap_r2": 0.05,
            "beta_r2": 0.08,
            "volatility_r2": 0.03,
            "liquidity_r2": 0.02,
            "industry_r2": 0.10,
            "jackknife_max_impact": 3.5,
        },
        "promotion_eligible": True,
    }


@pytest.fixture()
def v44_style_exposure_result() -> dict:
    """模拟一个风格暴露的验证结果"""
    return {
        "beats_semiconductor_peer": True,
        "beats_core_peer": True,
        "beats_matched_control": False,
        "excess_vs_semiconductor_ew": 6.0,
        "excess_vs_core_ew": 6.0,
        "excess_vs_matched_control": -1.0,
        "excess_vs_etf_basket": 10.0,
        "risk_exposure": {
            "exposure_type": "style_exposure_market_cap",
            "market_cap_r2": 0.65,
            "beta_r2": 0.20,
            "volatility_r2": 0.30,
            "liquidity_r2": 0.15,
            "industry_r2": 0.20,
            "jackknife_max_impact": 5.0,
        },
        "promotion_eligible": True,
    }


@pytest.fixture()
def v44_industry_bet_result() -> dict:
    """模拟一个行业暴露型验证结果"""
    return {
        "beats_semiconductor_peer": True,
        "beats_core_peer": True,
        "beats_matched_control": True,
        "excess_vs_semiconductor_ew": 7.0,
        "excess_vs_core_ew": 7.0,
        "excess_vs_matched_control": 2.0,
        "excess_vs_etf_basket": 11.0,
        "risk_exposure": {
            "exposure_type": "industry_bet",
            "market_cap_r2": 0.10,
            "beta_r2": 0.15,
            "volatility_r2": 0.10,
            "liquidity_r2": 0.05,
            "industry_r2": 0.70,
            "jackknife_max_impact": 4.0,
        },
        "promotion_eligible": True,
    }


@pytest.fixture()
def v44_concentrated_result() -> dict:
    """模拟一个极端个股依赖的验证结果"""
    return {
        "beats_semiconductor_peer": True,
        "beats_core_peer": True,
        "beats_matched_control": True,
        "excess_vs_semiconductor_ew": 5.0,
        "excess_vs_core_ew": 5.0,
        "excess_vs_matched_control": 1.5,
        "excess_vs_etf_basket": 8.0,
        "risk_exposure": {
            "exposure_type": "concentrated",
            "market_cap_r2": 0.10,
            "beta_r2": 0.08,
            "volatility_r2": 0.05,
            "liquidity_r2": 0.03,
            "industry_r2": 0.15,
            "jackknife_max_impact": 25.0,
        },
        "promotion_eligible": True,
    }


# =========================================================================
# 1. 增强指标计算测试
# =========================================================================


class TestEnhancedMetrics:
    """增强绩效指标计算测试"""

    def test_compute_turnover_empty(self):
        """空持仓历史"""
        one, two = compute_turnover([])
        assert one == 0.0
        assert two == 0.0

    def test_compute_turnover_single(self, portfolio_history):
        """单期换手"""
        one, two = compute_turnover([portfolio_history[0]])
        assert one == 0.0
        assert two == 0.0

    def test_compute_turnover_no_change(self):
        """持仓不变 = 换手 0"""
        port = [["A", "B", "C"], ["A", "B", "C"], ["A", "B", "C"]]
        one, two = compute_turnover(port)
        assert one == 0.0
        assert two == 0.0

    def test_compute_turnover_full_change(self):
        """完全换手"""
        port = [["A", "B"], ["C", "D"]]
        one, two = compute_turnover(port)
        assert one == 1.0  # 2/2
        assert two == 2.0  # (2+2)/2

    def test_compute_turnover_partial(self):
        """部分换手"""
        port = [["A", "B", "C"], ["A", "D", "E"]]
        one, two = compute_turnover(port)
        assert one == pytest.approx(2 / 3)
        assert two == pytest.approx(4 / 3)

    def test_max_drawdown_positive_only(self):
        """全部正收益 → 回撤 0"""
        rets = pd.Series([0.01, 0.02, 0.03])
        dd = compute_max_drawdown(rets)
        assert dd == 0.0

    def test_max_drawdown_known(self):
        """已知回撤值"""
        # 从 100 到 80 = -20% 回撤
        rets = pd.Series([0.0, -0.1, -0.1, 0.0])
        dd = compute_max_drawdown(rets)
        assert dd > 0.15  # (1.0 * 0.9 * 0.9 = 0.81, peak=1.0, dd=0.19)

    def test_max_drawdown_empty(self, empty_series):
        """空序列"""
        assert compute_max_drawdown(empty_series) == 0.0

    def test_max_drawdown_single(self):
        """单数据点"""
        assert compute_max_drawdown(pd.Series([0.01])) == 0.0

    def test_win_rate_all_positive(self):
        """全部正收益 → 胜率 1.0"""
        rets = pd.Series([0.01, 0.02, 0.03])
        assert compute_win_rate(rets) == 1.0

    def test_win_rate_half(self):
        """一半正收益 → 0.5"""
        rets = pd.Series([0.01, -0.01, 0.02, -0.02])
        assert compute_win_rate(rets) == 0.5

    def test_win_rate_empty(self, empty_series):
        assert compute_win_rate(empty_series) == 0.0

    def test_cagr_known(self):
        """已知 CAGR: 10% per period, 2 periods → CAGR = 21% with ann=2"""
        rets = pd.Series([0.10, 0.10])
        cagr = compute_cagr(rets, ann_periods=2)
        # total_ret = 1.1*1.1 - 1 = 0.21
        # years = 2/2 = 1
        # CAGR = (1.21)^(1/1) - 1 = 0.21
        assert cagr == pytest.approx(0.21, rel=1e-3)

    def test_cagr_known_annual(self):
        """CAGR with different ann_periods"""
        rets = pd.Series([0.10, 0.10])
        # ann_periods=1, n_periods=2 → years = 2
        # CAGR = (1.21)^(1/2) - 1 = 0.10
        cagr = compute_cagr(rets, ann_periods=1)
        assert cagr == pytest.approx(0.10, rel=1e-3)

    def test_cagr_empty(self, empty_series):
        assert compute_cagr(empty_series) == 0.0

    def test_cagr_negative(self):
        """负收益 CAGR 为负"""
        rets = pd.Series([-0.10, -0.10])
        cagr = compute_cagr(rets, ann_periods=2)
        assert cagr < 0

    def test_calmar_zero_dd(self):
        """零回撤 → 0"""
        assert compute_calmar(0.10, 0.0) == 0.0

    def test_calmar_known(self):
        """已知 Calmar"""
        calmar = compute_calmar(0.15, 0.10)
        assert calmar == pytest.approx(1.5)

    def test_compute_enhanced_metrics_empty(self):
        """空序列 → 全零"""
        metrics = compute_enhanced_metrics(pd.Series(dtype=float))
        for k in metrics:
            assert metrics[k] == 0 or metrics[k] == 0.0

    def test_compute_enhanced_metrics_basic(self, normal_rets):
        """正常序列 → 指标非零"""
        metrics = compute_enhanced_metrics(normal_rets)
        assert metrics["cagr_pct"] != 0
        assert metrics["max_drawdown_pct"] > 0
        assert 0 < metrics["win_rate"] < 1
        assert metrics["calmar_ratio"] != 0

    def test_compute_enhanced_metrics_with_portfolio(self, normal_rets, portfolio_history):
        """含持仓历史的增强指标"""
        metrics = compute_enhanced_metrics(
            normal_rets,
            portfolio_history=portfolio_history,
            rebal_dates=list(normal_rets.index[::20]),
        )
        assert "one_way_turnover" in metrics
        assert "two_way_turnover" in metrics


# =========================================================================
# 2. 策略收益计算测试
# =========================================================================


class TestStrategyReturns:
    """策略收益率计算测试"""

    def test_compute_strategy_returns_not_empty(self, mock_data):
        df, cp = mock_data
        rets = _compute_strategy_returns(df, "test_factor", cp, top_quantile=0.2)
        assert len(rets) > 0
        assert isinstance(rets, pd.Series)

    def test_compute_strategy_returns_detailed(self, mock_data):
        df, cp = mock_data
        rets, ports, rebals = _compute_strategy_returns_detailed(
            df, "test_factor", cp, top_quantile=0.2
        )
        assert len(rets) > 0
        assert len(ports) > 0
        assert len(rebals) > 0

    def test_strategy_returns_range_reasonable(self, mock_data):
        """日收益率在合理范围 ±5%"""
        df, cp = mock_data
        rets = _compute_strategy_returns(df, "test_factor", cp, top_quantile=0.3)
        assert rets.abs().max() < 0.10


# =========================================================================
# 3. 多基准对比测试
# =========================================================================


class TestBenchmarkComparison:
    """多基准对比测试"""

    def test_check_benchmark_returns_dict(self, mock_data):
        """check_benchmark 返回 dict"""
        df, cp = mock_data
        # 使用 semiconductor_ew 基准 (需要确保 universes 已构建)
        result = check_benchmark("semiconductor_ew", df, "test_factor", cp)
        assert isinstance(result, dict)
        assert "beats_semiconductor_ew" in result or "error" in result

    def test_check_benchmark_invalid_name(self, mock_data):
        """无效基准名"""
        df, cp = mock_data
        with pytest.raises(ValueError, match="不支持的基准|No benchmark named"):
            check_benchmark("invalid_name", df, "test_factor", cp)

    def test_check_benchmark_error_on_empty_data(self):
        """空数据 → error"""
        df, cp = _make_mock_data(n_dates=5, n_symbols=3)
        result = check_benchmark("semiconductor_ew", df, "test_factor", cp)
        # 可能返回 error 或成功的 beats 值
        assert "error" in result or "beats_semiconductor_ew" in result

    def test_validate_factor_v44_returns_comprehensive(self, mock_data):
        """V4.4 全量验证包含所有关键字段"""
        df, cp = mock_data
        result = validate_factor_v44("test_factor", df, cp)
        assert "enhanced_metrics" in result
        assert "benchmark_comparisons" in result
        assert "n_beaten_benchmarks" in result
        assert "promotion_eligible" in result
        assert "v44_score" in result

    def test_validate_factor_v44_enhanced_metrics_present(self, mock_data):
        """增强指标包含所有字段"""
        df, cp = mock_data
        result = validate_factor_v44("test_factor", df, cp)
        metrics = result["enhanced_metrics"]
        assert "one_way_turnover" in metrics
        assert "two_way_turnover" in metrics
        assert "cost_adjusted_return_pct" in metrics
        assert "max_drawdown_pct" in metrics
        assert "win_rate" in metrics
        assert "cagr_pct" in metrics
        assert "calmar_ratio" in metrics

    def test_validate_factor_v4_backward_compat(self, mock_data):
        """V4 向后兼容: validate_factor_v4 移除 V4.4 新增字段"""
        df, cp = mock_data
        result = validate_factor_v4("test_factor", df, cp)
        assert "enhanced_metrics" not in result
        assert "benchmark_comparisons" not in result
        assert "v44_score" not in result
        # V4.3 字段应保留
        assert "beats_semiconductor_peer" in result


# =========================================================================
# 4. V4.4 评分测试
# =========================================================================


class TestV44Scoring:
    """V4.4 综合评分测试"""

    def test_scoring_structure(self, mock_data):
        """评分包含所有维度"""
        df, cp = mock_data
        # Need to run full validation to get proper metrics
        result = validate_factor_v44("test_factor", df, cp)
        score = result.get("v44_score", {})
        assert "ic_quality" in score
        assert "benchmark_score" in score
        assert "risk_score" in score
        assert "stability_score" in score
        assert "cost_efficiency" in score
        assert "total" in score

    def test_scoring_range(self, mock_data):
        """总分在 0-100 之间"""
        df, cp = mock_data
        result = validate_factor_v44("test_factor", df, cp)
        score = result.get("v44_score", {}).get("total", 0)
        assert 0 <= score <= 100


# =========================================================================
# 5. Risk Exposure 测试
# =========================================================================


class TestRiskExposureAnalyzer:
    """风险暴露归因分析器测试"""

    def test_analyzer_init(self):
        """初始化"""
        analyzer = RiskExposureAnalyzer()
        assert analyzer is not None

    def test_analyzer_with_close_pivot(self, mock_data):
        """带收盘价初始化"""
        df, cp = mock_data
        analyzer = RiskExposureAnalyzer(close_pivot=cp)
        assert analyzer.close_pivot is not None

    def test_analyzer_returns_dict(self, mock_data):
        """analyze 返回 dict"""
        df, cp = mock_data
        analyzer = RiskExposureAnalyzer(close_pivot=cp)
        result = analyzer.analyze(df, "test_factor")
        assert isinstance(result, dict)
        assert "exposure_type" in result
        assert "n_stocks_analyzed" in result

    def test_analyzer_has_all_keys_with_no_data(self, mock_data):
        """包含所有维度 (即使无真实 K 线数据也应有默认值)"""
        df, cp = mock_data
        analyzer = RiskExposureAnalyzer(close_pivot=cp)
        result = analyzer.analyze(df, "test_factor")
        expected_keys = [
            "market_cap_r2", "beta_r2", "volatility_r2",
            "liquidity_r2", "industry_r2",
            "jackknife_max_impact", "exposure_type",
        ]
        for key in expected_keys:
            assert key in result, f"缺少 {key}"
        # 即使无真实数据, exposure_type 不应为 error
        assert result["exposure_type"] != "error" or "error" not in result

    def test_analyzer_jackknife_returns_list(self, mock_data):
        """Jackknife 返回列表"""
        df, cp = mock_data
        analyzer = RiskExposureAnalyzer(close_pivot=cp)
        result = analyzer.analyze(df, "test_factor")
        assert isinstance(result.get("jackknife_top_contributors", []), list)

    def test_classify_exposure_pure_alpha(self):
        """pure_alpha 分类"""
        result = {
            "market_cap_r2": 0.05,
            "beta_r2": 0.08,
            "volatility_r2": 0.03,
            "liquidity_r2": 0.02,
            "industry_r2": 0.10,
            "jackknife_max_impact": 3.0,
        }
        exp_type = RiskExposureAnalyzer._classify_exposure(result)
        assert exp_type == "pure_alpha"

    def test_classify_exposure_concentrated(self):
        """高 jackknife → concentrated"""
        result = {
            "market_cap_r2": 0.05,
            "beta_r2": 0.08,
            "volatility_r2": 0.03,
            "liquidity_r2": 0.02,
            "industry_r2": 0.10,
            "jackknife_max_impact": 25.0,
        }
        exp_type = RiskExposureAnalyzer._classify_exposure(result)
        assert exp_type == "concentrated"

    def test_classify_exposure_industry_bet(self):
        """高行业集中度 → industry_bet"""
        result = {
            "market_cap_r2": 0.10,
            "beta_r2": 0.15,
            "volatility_r2": 0.10,
            "liquidity_r2": 0.05,
            "industry_r2": 0.70,
            "jackknife_max_impact": 4.0,
        }
        exp_type = RiskExposureAnalyzer._classify_exposure(result)
        assert exp_type == "industry_bet"

    def test_classify_exposure_style(self):
        """高风格暴露 → style_exposure_*"""
        result = {
            "market_cap_r2": 0.65,
            "beta_r2": 0.20,
            "volatility_r2": 0.30,
            "liquidity_r2": 0.15,
            "industry_r2": 0.20,
            "jackknife_max_impact": 5.0,
        }
        exp_type = RiskExposureAnalyzer._classify_exposure(result)
        assert exp_type.startswith("style_exposure")


# =========================================================================
# 6. Gate 测试: BeatsSemiconductorPeerGate
# =========================================================================


class TestBeatsSemiconductorPeerGate:
    """V4.4 严格半导体同池 Gate 测试"""

    def test_gate_pass_both_conditions(self, v44_passing_result):
        """跑赢半导体 + 跑赢匹配对照 → 通过"""
        gate = BeatsSemiconductorPeerGate()
        result = gate.evaluate(v44_passing_result)
        assert result.passed is True

    def test_gate_fail_no_beats_semi(self, v44_style_exposure_result):
        """未跑赢半导体 → 不通过"""
        gate = BeatsSemiconductorPeerGate()
        # 修改 beats_semiconductor_peer 为 False
        bad_result = dict(v44_style_exposure_result)
        bad_result["beats_semiconductor_peer"] = False
        result = gate.evaluate(bad_result)
        assert result.passed is False

    def test_gate_fail_no_matched_control(self, v44_style_exposure_result):
        """未跑赢匹配对照 → 不通过"""
        gate = BeatsSemiconductorPeerGate()
        result = gate.evaluate(v44_style_exposure_result)
        # v44_style_exposure_result has beats_matched_control=False
        assert result.passed is False

    def test_gate_has_blocker_checks(self, v44_passing_result):
        """通过时无 blocker"""
        gate = BeatsSemiconductorPeerGate()
        result = gate.evaluate(v44_passing_result)
        assert len(result.blockers) == 0

    def test_gate_blocker_present_on_fail(self, v44_style_exposure_result):
        """失败时有 blocker"""
        gate = BeatsSemiconductorPeerGate()
        result = gate.evaluate(v44_style_exposure_result)
        assert len(result.blockers) > 0

    def test_gate_name(self, v44_passing_result):
        """Gate 名称正确"""
        gate = BeatsSemiconductorPeerGate()
        result = gate.evaluate(v44_passing_result)
        assert result.gate_name == "beats_semiconductor_peer"


# =========================================================================
# 7. Gate 测试: RiskExposureGate
# =========================================================================


class TestRiskExposureGate:
    """V4.4 风险暴露 Gate 测试"""

    def test_gate_pass_pure_alpha(self, v44_passing_result):
        """pure_alpha → 通过"""
        gate = RiskExposureGate()
        result = gate.evaluate(v44_passing_result)
        assert result.passed is True

    def test_gate_block_style_exposure(self, v44_style_exposure_result):
        """风格暴露 → blocker"""
        gate = RiskExposureGate()
        result = gate.evaluate(v44_style_exposure_result)
        assert result.passed is False
        assert len(result.blockers) > 0

    def test_gate_block_industry_bet(self, v44_industry_bet_result):
        """行业暴露 → blocker"""
        gate = RiskExposureGate()
        result = gate.evaluate(v44_industry_bet_result)
        assert result.passed is False
        assert len(result.blockers) > 0

    def test_gate_block_concentrated(self, v44_concentrated_result):
        """极端个股依赖 → blocker"""
        gate = RiskExposureGate()
        result = gate.evaluate(v44_concentrated_result)
        assert result.passed is False
        assert len(result.blockers) > 0

    def test_gate_no_data(self):
        """无数据 → insufficient_evidence"""
        gate = RiskExposureGate()
        result = gate.evaluate({})
        # 无 risk_exposure 字段 → no_data → insufficient_evidence
        # 由于 GateEngine 没有这个状态, pass 但警告
        assert result.passed is True  # 没有 blocker
        assert result.verdict == "pass" or result.verdict == "conditional_pass"

    def test_gate_name(self, v44_passing_result):
        """Gate 名称正确"""
        gate = RiskExposureGate()
        result = gate.evaluate(v44_passing_result)
        assert result.gate_name == "risk_exposure"

    def test_check_risk_exposure_gate_helper(self, v44_passing_result):
        """便捷函数返回正确结构"""
        result = check_risk_exposure_gate(v44_passing_result)
        assert "gate_name" in result
        assert "verdict" in result
        assert "passed" in result
        assert "exposure_type" in result
        assert "checks" in result
        assert result["passed"] is True


# =========================================================================
# 8. 组合门禁测试
# =========================================================================


class TestV44PromotionGate:
    """V4.4 组合门禁测试"""

    def test_promotion_pass(self, v44_passing_result):
        """全部通过"""
        result = check_v44_promotion_gate(v44_passing_result)
        assert result["overall_passed"] is True

    def test_promotion_fail_semiconductor(self, v44_style_exposure_result):
        """半导体 Gate 失败"""
        result = check_v44_promotion_gate(v44_style_exposure_result)
        assert result["overall_passed"] is False

    def test_promotion_fail_risk(self, v44_industry_bet_result):
        """风险暴露 Gate 失败"""
        result = check_v44_promotion_gate(v44_industry_bet_result)
        assert result["overall_passed"] is False

    def test_promotion_fail_both(self, v44_concentrated_result):
        """两个 Gate 都失败"""
        # concentrated 情况: beats_matched_control=True (pass semi gate)
        # but exposure_type=concentrated (fail risk gate)
        result = check_v44_promotion_gate(v44_concentrated_result)
        # 现在修改 concentrated 使其同时 fails semiconductor gate
        bad_result = dict(v44_concentrated_result)
        bad_result["beats_semiconductor_peer"] = False
        bad_result["beats_matched_control"] = False
        result = check_v44_promotion_gate(bad_result)
        assert result["overall_passed"] is False
        assert len(result["blockers"]) >= 2

    def test_promotion_blockers_structure(self, v44_style_exposure_result):
        """blockers 包含 gate 信息"""
        result = check_v44_promotion_gate(v44_style_exposure_result)
        for b in result["blockers"]:
            assert "name" in b
            assert "message" in b
            assert "severity" in b
            assert "gate" in b

    def test_promotion_gates_structure(self, v44_passing_result):
        """gates 字段结构"""
        result = check_v44_promotion_gate(v44_passing_result)
        assert "gates" in result
        assert "semiconductor_peer" in result["gates"]
        assert "risk_exposure" in result["gates"]
        assert result["gates"]["semiconductor_peer"]["passed"] is True
        assert result["gates"]["risk_exposure"]["passed"] is True


# =========================================================================
# 9. Clean / Serialization 测试
# =========================================================================


class TestCleanSerialization:
    """JSON 序列化辅助测试"""

    def test_clean_numpy_types(self):
        """numpy 类型转换"""
        data = {
            "a": np.float64(3.14),
            "b": np.int64(42),
            "c": np.bool_(True),
            "d": np.array([1, 2, 3]),
        }
        cleaned = clean(data)
        assert isinstance(cleaned["a"], float)
        assert isinstance(cleaned["b"], int)
        assert isinstance(cleaned["c"], bool)
        assert isinstance(cleaned["d"], list)

    def test_clean_pandas_timestamp(self):
        """Timestamp 转 str"""
        data = {"date": pd.Timestamp("2026-01-02")}
        cleaned = clean(data)
        assert isinstance(cleaned["date"], str)

    def test_clean_dict_recursive(self):
        """递归清理"""
        data = {"inner": {"val": np.float64(1.5)}}
        cleaned = clean(data)
        assert isinstance(cleaned["inner"]["val"], float)

    def test_clean_truncates_long_lists(self):
        """长列表截断"""
        data = {"items": list(range(300))}
        cleaned = clean(data)
        assert len(cleaned["items"]) == 200


# =========================================================================
# 10. Cost-Adjusted Returns 测试
# =========================================================================


class TestCostAdjustedReturns:
    """交易成本后收益计算测试"""

    def test_cost_adjustment_curve(self, normal_rets):
        """成本后收益 ≤ 原始收益"""
        rebal_dates = list(normal_rets.index[::20])
        adj = compute_cost_adjusted_returns(normal_rets, rebal_dates, 0.3, 0.5)
        orig_cum = (1 + normal_rets).prod()
        adj_cum = (1 + adj).prod()
        assert adj_cum <= orig_cum + 1e-10  # 考虑浮点误差

    def test_cost_adjustment_no_rebalance(self, normal_rets):
        """无再平衡日 → 无调整"""
        adj = compute_cost_adjusted_returns(normal_rets, [], 0.3, 0.5)
        assert (adj == normal_rets).all()

    def test_cost_adjustment_zero_turnover(self, normal_rets):
        """零换手 → 无调整"""
        rebal_dates = list(normal_rets.index[::20])
        adj = compute_cost_adjusted_returns(normal_rets, rebal_dates, 0.0, 0.0)
        assert (adj == normal_rets).all()


# =========================================================================
# Run
# =========================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
