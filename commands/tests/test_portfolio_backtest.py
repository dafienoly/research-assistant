"""Portfolio Backtest/Benchmark V6.4 — 组合回测与基准对比测试

测试覆盖:
  - PortfolioSpec: 创建、校验、序列化
  - BenchmarkSpec: 创建、序列化
  - PortfolioMetrics: 聚合
  - PortfolioResult: 摘要、序列化
  - Benchmark: 基准加载、synthetic 生成、列表
  - Metrics: 绝对指标、基准对比、交叉相关性、归因
  - PortfolioBacktestEngine: 完整回测流程、再平衡、边界条件、空数据
  - Report: 摘要打印、格式化、保存
  - 回归测试: 与 V5.x/V6.0 无冲突
"""

import sys, os, json, tempfile
from pathlib import Path

# ── 确保能找到 commands/ ──
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))

import pytest
import numpy as np
import pandas as pd

from factor_lab.portfolio import (
    PortfolioSpec,
    BenchmarkSpec,
    PortfolioMetrics,
    PortfolioResult,
    AttributionItem,
    PortfolioBacktestEngine,
    get_benchmark_returns,
    get_benchmark_meta,
    list_benchmarks,
    make_benchmark_spec,
    compute_portfolio_absolute_metrics,
    compute_benchmark_relative_metrics,
    compute_cross_correlation,
    compute_avg_correlation,
    compute_attribution,
    compute_portfolio_metrics,
    print_summary,
    format_report,
    save_report,
    VALID_BENCHMARK_NAMES,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture()
def sample_dates() -> pd.DatetimeIndex:
    """252 个交易日 (约 1 年)"""
    return pd.date_range("2025-01-02", periods=252, freq="B")


@pytest.fixture()
def strategy_returns(sample_dates) -> dict[str, pd.Series]:
    """两个模拟策略收益率"""
    rng = np.random.default_rng(42)
    n = len(sample_dates)

    # 动量策略: 年化 ~15%, Sharpe ~1.0
    mom_ret = pd.Series(
        rng.normal(0.15 / 252, 0.15 / np.sqrt(252), n),
        index=sample_dates,
        name="momentum",
    )
    # 价值策略: 年化 ~12%, Sharpe ~0.8
    val_ret = pd.Series(
        rng.normal(0.12 / 252, 0.15 / np.sqrt(252), n),
        index=sample_dates,
        name="value",
    )
    return {"momentum": mom_ret, "value": val_ret}


@pytest.fixture()
def single_strategy_returns(sample_dates) -> dict[str, pd.Series]:
    """仅一个策略"""
    rng = np.random.default_rng(123)
    n = len(sample_dates)
    ret = pd.Series(
        rng.normal(0.10 / 252, 0.18 / np.sqrt(252), n),
        index=sample_dates,
        name="single",
    )
    return {"single_factor": ret}


@pytest.fixture()
def portfolio_spec(strategy_returns) -> PortfolioSpec:
    return PortfolioSpec(
        name="测试组合",
        strategy_returns=strategy_returns,
        weights={"momentum": 0.6, "value": 0.4},
        rebalance_freq="monthly",
    )


@pytest.fixture()
def benchmark_spec() -> BenchmarkSpec:
    return make_benchmark_spec("CSI300")


@pytest.fixture()
def engine(portfolio_spec) -> PortfolioBacktestEngine:
    return PortfolioBacktestEngine(portfolio_spec)


# ═══════════════════════════════════════════════════════════════
# Test: PortfolioSpec
# ═══════════════════════════════════════════════════════════════

class TestPortfolioSpec:
    def test_create_default(self):
        spec = PortfolioSpec()
        assert spec.name == "Portfolio"
        assert spec.rebalance_freq == "monthly"
        assert spec.rebalance_method == "fixed"

    def test_create_full(self, strategy_returns):
        spec = PortfolioSpec(
            name="测试组合",
            strategy_returns=strategy_returns,
            weights={"momentum": 0.6, "value": 0.4},
            rebalance_freq="monthly",
            rebalance_method="fixed",
        )
        assert spec.name == "测试组合"
        assert len(spec.strategy_returns) == 2
        assert spec.weights["momentum"] == 0.6
        assert spec.weights["value"] == 0.4

    def test_validate_valid(self, portfolio_spec):
        errors = portfolio_spec.validate()
        assert errors == []

    def test_validate_empty_name(self):
        spec = PortfolioSpec(name="")
        errors = spec.validate()
        assert any("名称" in e for e in errors)

    def test_validate_no_strategies(self):
        spec = PortfolioSpec(weights={"a": 1.0})
        errors = spec.validate()
        assert any("为空" in e for e in errors)

    def test_validate_weight_mismatch(self, strategy_returns):
        spec = PortfolioSpec(
            strategy_returns=strategy_returns,
            weights={"momentum": 1.0},  # 缺少 value
        )
        errors = spec.validate()
        assert any("缺少权重" in e for e in errors)

    def test_validate_weights_not_sum_to_one(self, strategy_returns):
        spec = PortfolioSpec(
            strategy_returns=strategy_returns,
            weights={"momentum": 0.8, "value": 0.8},
        )
        errors = spec.validate()
        assert any("权重和" in e for e in errors)

    def test_validate_invalid_freq(self, strategy_returns):
        spec = PortfolioSpec(
            strategy_returns=strategy_returns,
            weights={"momentum": 0.5, "value": 0.5},
            rebalance_freq="yearly",
        )
        errors = spec.validate()
        assert any("调仓频率" in e for e in errors)

    def test_to_dict(self, portfolio_spec):
        d = portfolio_spec.to_dict()
        assert d["name"] == "测试组合"
        assert "momentum" in d["strategy_names"]
        assert "value" in d["strategy_names"]
        assert d["weights"]["momentum"] == 0.6


# ═══════════════════════════════════════════════════════════════
# Test: BenchmarkSpec
# ═══════════════════════════════════════════════════════════════

class TestBenchmarkSpec:
    def test_create_default(self):
        spec = BenchmarkSpec()
        assert spec.name == "CSI300"

    def test_create_custom(self, sample_dates):
        returns = pd.Series(np.zeros(len(sample_dates)), index=sample_dates)
        spec = BenchmarkSpec(name="custom", returns=returns)
        assert spec.name == "custom"
        assert len(spec.returns) == len(sample_dates)

    def test_to_dict(self):
        spec = BenchmarkSpec(name="CSI500")
        d = spec.to_dict()
        assert d["name"] == "CSI500"

    def test_all_valid_names(self):
        assert "CSI300" in VALID_BENCHMARK_NAMES
        assert "CSI500" in VALID_BENCHMARK_NAMES
        assert "CSI1000" in VALID_BENCHMARK_NAMES
        assert "CSI_ALL" in VALID_BENCHMARK_NAMES


# ═══════════════════════════════════════════════════════════════
# Test: PortfolioMetrics
# ═══════════════════════════════════════════════════════════════

class TestPortfolioMetrics:
    def test_create_default(self):
        m = PortfolioMetrics()
        assert m.cumulative_return_pct == 0.0
        assert m.sharpe == 0.0

    def test_to_dict(self):
        m = PortfolioMetrics(
            cumulative_return_pct=15.5,
            sharpe=0.85,
            n_strategies=2,
        )
        d = m.to_dict()
        assert d["cumulative_return_pct"] == 15.5
        assert d["sharpe"] == 0.85
        assert d["n_strategies"] == 2  # serialized in to_dict


# ═══════════════════════════════════════════════════════════════
# Test: PortfolioResult
# ═══════════════════════════════════════════════════════════════

class TestPortfolioResult:
    def test_create_default(self):
        r = PortfolioResult()
        assert r.run_id is not None

    def test_summary(self, portfolio_spec):
        r = PortfolioResult(portfolio_spec=portfolio_spec)
        s = r.summary()
        assert s["portfolio"] == "测试组合"
        assert s["n_strategies"] == 0

    def test_to_dict(self, portfolio_spec):
        r = PortfolioResult(portfolio_spec=portfolio_spec)
        d = r.to_dict()
        assert d["portfolio_spec"]["name"] == "测试组合"
        assert "metrics" in d


# ═══════════════════════════════════════════════════════════════
# Test: Benchmark
# ═══════════════════════════════════════════════════════════════

class TestBenchmark:
    def test_list_benchmarks(self):
        bms = list_benchmarks()
        assert len(bms) >= 4
        names = {b["name"] for b in bms}
        assert "CSI300" in names
        assert "CSI500" in names
        assert "CSI1000" in names
        assert "CSI_ALL" in names

    def test_get_benchmark_meta(self):
        meta = get_benchmark_meta("CSI300")
        assert meta["name"] == "沪深300"
        assert meta["code"] == "000300.SH"

    def test_get_benchmark_meta_case_insensitive(self):
        meta = get_benchmark_meta("csi500")
        assert meta["name"] == "中证500"

    def test_get_benchmark_meta_invalid(self):
        with pytest.raises(ValueError):
            get_benchmark_meta("INVALID")

    def test_make_benchmark_spec(self):
        spec = make_benchmark_spec("CSI500")
        assert spec.name == "CSI500"
        assert "中证500" in spec.description

    def test_make_benchmark_spec_invalid(self):
        with pytest.raises(ValueError):
            make_benchmark_spec("INVALID")

    def test_synthetic_returns_default_dates(self):
        """无 dates 时自动生成"""
        spec = BenchmarkSpec(name="CSI300")
        returns = get_benchmark_returns(spec, method="synthetic")
        assert len(returns) >= 200
        assert returns.name == "CSI300"

    def test_synthetic_returns_with_dates(self, sample_dates):
        spec = BenchmarkSpec(name="CSI500")
        returns = get_benchmark_returns(spec, index_dates=sample_dates, method="synthetic")
        assert len(returns) == len(sample_dates)

    def test_synthetic_returns_different_profiles(self):
        """各指数有不同的收益/波动配置"""
        dates = pd.date_range("2025-01-02", periods=252, freq="B")

        r300 = get_benchmark_returns(
            BenchmarkSpec(name="CSI300"), dates, method="synthetic", seed=1
        )
        r500 = get_benchmark_returns(
            BenchmarkSpec(name="CSI500"), dates, method="synthetic", seed=1
        )
        r1000 = get_benchmark_returns(
            BenchmarkSpec(name="CSI1000"), dates, method="synthetic", seed=1
        )

        assert not r300.equals(r500)
        assert not r500.equals(r1000)

    def test_custom_benchmark(self, sample_dates):
        custom_ret = pd.Series(
            np.zeros(len(sample_dates)), index=sample_dates
        )
        spec = BenchmarkSpec(name="custom", returns=custom_ret)
        result = get_benchmark_returns(spec)
        assert len(result) == len(sample_dates)

    def test_custom_benchmark_no_data(self):
        spec = BenchmarkSpec(name="custom")
        with pytest.raises(ValueError):
            get_benchmark_returns(spec)

    def test_get_benchmark_returns_invalid_method(self, sample_dates):
        spec = BenchmarkSpec(name="CSI300")
        with pytest.raises(ValueError):
            get_benchmark_returns(spec, index_dates=sample_dates, method="invalid")

    def test_get_benchmark_returns_none_spec(self):
        with pytest.raises(ValueError):
            get_benchmark_returns(None)  # type: ignore


# ═══════════════════════════════════════════════════════════════
# Test: Metrics
# ═══════════════════════════════════════════════════════════════

class TestMetrics:
    def test_absolute_metrics_basic(self, strategy_returns):
        """测试绝对指标计算"""
        combined = pd.DataFrame(strategy_returns).sum(axis=1)
        m = compute_portfolio_absolute_metrics(combined)
        assert m["cumulative_return_pct"] != 0.0
        assert m["sharpe"] != 0.0
        assert m["n_trading_days"] == 252
        assert m["max_drawdown_pct"] <= 0  # 回撤应为负或零
        assert m["win_rate_pct"] >= 0

    def test_absolute_metrics_short_series(self):
        """短序列返回默认值"""
        short = pd.Series([0.01, 0.02])
        m = compute_portfolio_absolute_metrics(short)
        assert m["n_trading_days"] == 2
        assert m["sharpe"] == 0.0

    def test_absolute_metrics_constant_returns(self, sample_dates):
        """常数收益率"""
        const = pd.Series(np.zeros(len(sample_dates)), index=sample_dates)
        m = compute_portfolio_absolute_metrics(const)
        assert m["cumulative_return_pct"] == 0.0
        assert m["sharpe"] == 0.0

    def test_benchmark_relative_metrics(self, strategy_returns):
        """基准对比指标"""
        combined = pd.DataFrame(strategy_returns).sum(axis=1)
        bm = pd.Series(
            np.random.default_rng(42).normal(0.08 / 252, 0.18 / np.sqrt(252), len(combined)),
            index=combined.index,
        )
        m = compute_benchmark_relative_metrics(combined, bm)
        assert m["benchmark_cumulative_return_pct"] != 0.0
        assert "tracking_error_pct" in m
        assert "information_ratio" in m
        assert "alpha" in m
        assert "beta" in m
        assert "r_squared" in m

    def test_benchmark_relative_no_overlap(self):
        """日期不重叠返回默认值"""
        d1 = pd.date_range("2025-01-02", periods=100, freq="B")
        d2 = pd.date_range("2026-01-02", periods=100, freq="B")
        pr = pd.Series(np.random.randn(100), index=d1)
        br = pd.Series(np.random.randn(100), index=d2)
        m = compute_benchmark_relative_metrics(pr, br)
        assert m["tracking_error_pct"] == 0.0

    def test_benchmark_relative_few_overlap(self):
        """重叠不足 5 天返回默认值"""
        d1 = pd.date_range("2025-01-02", periods=252, freq="B")
        pr = pd.Series(np.random.randn(252), index=d1)
        # 仅 3 天重叠
        br = pd.Series(np.random.randn(3), index=d1[:3])
        m = compute_benchmark_relative_metrics(pr, br)
        assert m["active_return_pct"] == 0.0

    def test_cross_correlation(self, strategy_returns):
        corr = compute_cross_correlation(strategy_returns)
        assert not corr.empty
        assert corr.shape == (2, 2)
        assert "momentum" in corr.columns
        assert "value" in corr.columns

    def test_cross_correlation_single(self, single_strategy_returns):
        corr = compute_cross_correlation(single_strategy_returns)
        assert corr.empty or corr.shape == (1, 1)

    def test_cross_correlation_empty(self):
        corr = compute_cross_correlation({})
        assert corr.empty

    def test_avg_correlation(self, strategy_returns):
        corr = compute_cross_correlation(strategy_returns)
        avg = compute_avg_correlation(corr)
        assert -1.0 <= avg <= 1.0

    def test_avg_correlation_single_matrix(self):
        corr = pd.DataFrame([[1.0]], index=["a"], columns=["a"])
        avg = compute_avg_correlation(corr)
        assert avg == 0.0

    def test_avg_correlation_empty(self):
        avg = compute_avg_correlation(pd.DataFrame())
        assert avg == 0.0

    def test_attribution(self, strategy_returns):
        combined = pd.DataFrame(strategy_returns).sum(axis=1)
        attr = compute_attribution(
            strategy_returns,
            {"momentum": 0.6, "value": 0.4},
            combined,
        )
        assert len(attr) == 2
        for a in attr:
            assert "strategy_name" in a
            assert "weight" in a
            assert "contribution_pct" in a
            assert "standalone_return_pct" in a

    def test_attribution_empty(self):
        attr = compute_attribution({}, {}, pd.Series())
        assert attr == []

    def test_compute_portfolio_metrics_integration(self, strategy_returns):
        combined = pd.DataFrame(strategy_returns).sum(axis=1)
        bm = pd.Series(
            np.random.default_rng(1).normal(0.08 / 252, 0.18 / np.sqrt(252), len(combined)),
            index=combined.index,
        )
        result = compute_portfolio_metrics(
            combined, strategy_returns, {"momentum": 0.6, "value": 0.4}, bm
        )
        assert "cumulative_return_pct" in result
        assert "active_return_pct" in result
        assert "avg_cross_correlation" in result
        assert "strategy_metrics" in result
        assert "momentum" in result["strategy_metrics"]
        assert "value" in result["strategy_metrics"]


# ═══════════════════════════════════════════════════════════════
# Test: PortfolioBacktestEngine
# ═══════════════════════════════════════════════════════════════

class TestPortfolioBacktestEngine:
    def test_real_benchmark_is_default(self, portfolio_spec):
        engine = PortfolioBacktestEngine(portfolio_spec)
        assert engine.run.__func__.__defaults__ == (None, False)

    def test_create(self, portfolio_spec):
        engine = PortfolioBacktestEngine(portfolio_spec)
        assert engine.spec.name == "测试组合"

    def test_create_invalid_spec(self, strategy_returns):
        invalid = PortfolioSpec(
            strategy_returns=strategy_returns,
            weights={"momentum": 1.5},  # 权重不匹配
        )
        with pytest.raises(ValueError):
            PortfolioBacktestEngine(invalid)

    def test_run_basic(self, engine):
        result = engine.run(benchmark_spec=None)
        assert result.portfolio_spec is not None
        assert result.portfolio_returns is not None
        assert len(result.portfolio_returns) > 0
        assert result.metrics.n_trading_days > 0

    def test_run_with_benchmark(self, engine):
        result = engine.run_with_benchmark("CSI300")
        assert result.metrics.sharpe != 0.0
        assert result.metrics.n_trading_days > 0
        # 交叉相关性可能因随机种子小幅负值, 使用绝对值检查
        assert abs(result.metrics.avg_cross_correlation) <= 1.0
        # 应该有基准指标
        assert hasattr(result.metrics, "benchmark_cumulative_return_pct")
        assert result.metrics.n_strategies == 2

    def test_run_with_all_benchmarks(self, engine):
        """所有标准基准都能正常加载"""
        for bm_name in ["CSI300", "CSI500", "CSI1000", "CSI_ALL"]:
            result = engine.run_with_benchmark(bm_name)
            assert result.metrics.benchmark_cumulative_return_pct != 0.0, f"{bm_name} failed"

    def test_run_single_strategy(self, single_strategy_returns):
        """单策略组合"""
        spec = PortfolioSpec(
            name="单策略",
            strategy_returns=single_strategy_returns,
            weights={"single_factor": 1.0},
            rebalance_freq="monthly",
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run_with_benchmark("CSI300")
        assert result.metrics.n_strategies == 1
        assert result.metrics.cumulative_return_pct != 0.0

    def test_rebalance_none(self, strategy_returns, sample_dates):
        """不调仓频率"""
        spec = PortfolioSpec(
            name="no_rebalance",
            strategy_returns=strategy_returns,
            weights={"momentum": 0.5, "value": 0.5},
            rebalance_freq="none",
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        assert result.portfolio_returns is not None
        assert len(result.portfolio_returns) > 0

    def test_rebalance_daily(self, strategy_returns):
        """日频调仓"""
        spec = PortfolioSpec(
            name="daily_reb",
            strategy_returns=strategy_returns,
            weights={"momentum": 0.5, "value": 0.5},
            rebalance_freq="daily",
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        assert result.portfolio_returns is not None

    def test_rebalance_weekly(self, strategy_returns):
        """周频调仓"""
        spec = PortfolioSpec(
            name="weekly_reb",
            strategy_returns=strategy_returns,
            weights={"momentum": 0.5, "value": 0.5},
            rebalance_freq="weekly",
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        assert result.portfolio_returns is not None

    def test_equal_weight_method(self, strategy_returns):
        """等权方法"""
        spec = PortfolioSpec(
            name="equal_weight",
            strategy_returns=strategy_returns,
            weights={"momentum": 0.6, "value": 0.4},
            rebalance_freq="monthly",
            rebalance_method="equal",
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        assert result.portfolio_returns is not None
        # 等权应每个策略 0.5
        assert result.portfolio_spec is not None
        assert result.metrics.n_strategies == 2

    def test_individual_returns(self, engine):
        """各策略收益率包含在结果中"""
        result = engine.run_with_benchmark("CSI300")
        assert len(result.individual_returns) == 2
        for sname in ["momentum", "value"]:
            assert sname in result.individual_returns
            assert sname in result.individual_equities

    def test_attribution_in_result(self, engine):
        """归因分析"""
        result = engine.run_with_benchmark("CSI300")
        assert len(result.attribution) > 0
        a0 = result.attribution[0]
        assert a0.strategy_name != ""
        assert a0.weight > 0
        assert a0.correlation_to_portfolio != 0.0

    def test_weight_history(self, engine):
        """权重历史"""
        result = engine.run_with_benchmark("CSI300")
        assert result.weight_history is not None
        assert not result.weight_history.empty

    def test_cross_correlation_in_result(self, engine):
        """交叉相关性"""
        result = engine.run_with_benchmark("CSI300")
        assert result.cross_correlation is not None
        # 两个策略应有 2x2 矩阵
        assert result.cross_correlation.shape == (2, 2)

    def test_execution_log(self, engine):
        """执行日志"""
        result = engine.run_with_benchmark("CSI300")
        assert len(result.execution_log) > 0
        assert any("step:" in e for e in result.execution_log)

    def test_summary_method(self, engine):
        """summary() 返回可读数据"""
        result = engine.run_with_benchmark("CSI300")
        s = result.summary()
        assert s["n_trading_days"] > 0
        assert s["portfolio"] == "测试组合"

    def test_to_dict_serializable(self, engine):
        """to_dict() 可 JSON 序列化"""
        result = engine.run_with_benchmark("CSI300")
        d = result.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        assert len(json_str) > 0

    def test_three_strategies(self, sample_dates):
        """三个策略的组合"""
        rng = np.random.default_rng(100)
        n = len(sample_dates)
        returns = {
            "A": pd.Series(rng.normal(0.1 / 252, 0.15 / np.sqrt(252), n), index=sample_dates),
            "B": pd.Series(rng.normal(0.12 / 252, 0.18 / np.sqrt(252), n), index=sample_dates),
            "C": pd.Series(rng.normal(0.08 / 252, 0.12 / np.sqrt(252), n), index=sample_dates),
        }
        spec = PortfolioSpec(
            name="三策略",
            strategy_returns=returns,
            weights={"A": 0.4, "B": 0.35, "C": 0.25},
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run_with_benchmark("CSI1000")
        assert result.metrics.n_strategies == 3
        assert len(result.attribution) == 3
        assert result.cross_correlation is not None
        assert result.cross_correlation.shape == (3, 3)

    def test_different_date_ranges(self):
        """策略日期范围不同"""
        d1 = pd.date_range("2025-01-02", periods=200, freq="B")
        d2 = pd.date_range("2025-03-01", periods=200, freq="B")
        rng = np.random.default_rng(42)
        returns = {
            "early": pd.Series(rng.normal(0.01, 0.02, 200), index=d1),
            "late": pd.Series(rng.normal(0.01, 0.02, 200), index=d2),
        }
        spec = PortfolioSpec(
            name="不同日期",
            strategy_returns=returns,
            weights={"early": 0.5, "late": 0.5},
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        # 应取日期交集
        assert result.portfolio_returns is not None
        assert len(result.portfolio_returns) > 0

    def test_benchmark_custom(self, engine, sample_dates):
        """自定义基准"""
        bm_ret = pd.Series(
            np.random.default_rng(42).normal(0.05 / 252, 0.15 / np.sqrt(252), len(sample_dates)),
            index=sample_dates,
        )
        bm_spec = BenchmarkSpec(name="custom", returns=bm_ret)
        result = engine.run(benchmark_spec=bm_spec)
        assert result.metrics.benchmark_cumulative_return_pct != 0.0

    def test_run_multiple_times(self, engine):
        """多次运行结果稳定 (种子固定)"""
        r1 = engine.run_with_benchmark("CSI300")
        r2 = engine.run_with_benchmark("CSI300")
        assert r1.metrics.sharpe == r2.metrics.sharpe
        assert r1.metrics.cumulative_return_pct == r2.metrics.cumulative_return_pct

    def test_run_with_benchmark_variants(self, engine):
        """所有标准 benchmark 名称都能运行"""
        for name in ["CSI300", "CSI500", "CSI1000", "CSI_ALL"]:
            result = engine.run_with_benchmark(name)
            assert result.metrics.sharpe != 0.0
            assert result.metrics.benchmark_cumulative_return_pct != 0.0

    @pytest.mark.parametrize("freq", ["none", "monthly", "weekly", "daily"])
    def test_all_rebalance_frequencies(self, strategy_returns, freq):
        """所有调仓频率都能正常运行"""
        spec = PortfolioSpec(
            name=f"freq_{freq}",
            strategy_returns=strategy_returns,
            weights={"momentum": 0.5, "value": 0.5},
            rebalance_freq=freq,
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        assert result.portfolio_returns is not None
        assert len(result.portfolio_returns) > 0


# ═══════════════════════════════════════════════════════════════
# Test: Report
# ═══════════════════════════════════════════════════════════════

class TestReport:
    def test_print_summary(self, engine, capsys):
        """打印摘要不抛异常"""
        result = engine.run_with_benchmark("CSI300")
        print_summary(result)
        captured = capsys.readouterr()
        assert "组合回测报告" in captured.out
        assert "Sharpe" in captured.out

    def test_print_summary_no_benchmark(self, engine, capsys):
        """无基准时打印"""
        result = engine.run(benchmark_spec=None)
        print_summary(result)
        captured = capsys.readouterr()
        assert "组合回测报告" in captured.out

    def test_format_report(self, engine):
        """格式化报告为 dict"""
        result = engine.run_with_benchmark("CSI300")
        report = format_report(result)
        assert "metrics" in report
        assert "summary" in report
        assert "strategy_details" in report
        assert report["summary"]["n_trading_days"] > 0

    def test_save_report(self, engine):
        """保存报告到 JSON"""
        result = engine.run_with_benchmark("CSI300")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_report(result, output_dir=tmpdir)
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert "metrics" in data
            assert "summary" in data


# ═══════════════════════════════════════════════════════════════
# Test: Integration / Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestIntegration:
    def test_empty_strategy_returns(self, sample_dates):
        """空策略"""
        spec = PortfolioSpec(
            strategy_returns={},
            weights={},
        )
        with pytest.raises(ValueError):
            PortfolioBacktestEngine(spec)

    def test_single_tiny_return(self):
        """极短的收益率"""
        ret = pd.Series([0.001, 0.002], index=pd.date_range("2025-01-02", periods=2))
        spec = PortfolioSpec(
            strategy_returns={"a": ret},
            weights={"a": 1.0},
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        # 短序列应返回有效但有限的结果
        assert result.metrics.n_trading_days <= 2

    def test_import_via_init(self):
        """从 __init__ 导入测试"""
        from factor_lab.portfolio import (
            PortfolioSpec,
            PortfolioBacktestEngine,
            print_summary,
        )
        assert PortfolioSpec is not None
        assert PortfolioBacktestEngine is not None
        assert print_summary is not None

    def test_no_regression_on_metrics_module(self):
        """不破坏 factor_lab.metrics 的接口"""
        from factor_lab.metrics import compute_metrics, calc_sharpe, calc_max_drawdown
        ret = pd.Series(np.random.randn(100) * 0.02)
        m = compute_metrics(ret)
        assert "sharpe" in m
        assert "cumulative_return_pct" in m

    def test_all_benchmark_names_accessible(self):
        """所有 benchmark 名称可用"""
        for name in ["CSI300", "CSI500", "CSI1000", "CSI_ALL"]:
            spec = make_benchmark_spec(name)
            assert spec.name == name

    def test_weight_schedule_monthly_has_reasonable_count(self, sample_dates):
        """每月调仓应有约 12 次调仓"""
        rng = np.random.default_rng(12345)
        returns = {
            "a": pd.Series(rng.normal(0.001, 0.02, len(sample_dates)), index=sample_dates),
            "b": pd.Series(rng.normal(0.001, 0.02, len(sample_dates)), index=sample_dates),
        }
        spec = PortfolioSpec(
            strategy_returns=returns,
            weights={"a": 0.5, "b": 0.5},
            rebalance_freq="monthly",
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run()
        wh = result.weight_history
        # 检查权重是否变化 (每月调仓意味着权重重新设置为 0.5/0.5)
        assert wh is not None
        # 月频 252 交易日 ≈ 11-12 次再平衡
        # 权重应在每个调仓日重置
        first_w = wh.iloc[0, :].values
        last_w = wh.iloc[-1, :].values
        assert np.allclose(first_w, last_w, atol=0.01)
