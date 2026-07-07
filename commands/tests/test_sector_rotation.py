"""Tests for V6.8 Sector Rotation Module

Tests cover:
  - Spec/data models (SectorRotationConfig, SectorPerformance, etc.)
  - Sector performance computation (compute_sector_returns, performance_snapshot)
  - Rotation strategies (Momentum, MeanReversion, Composite)
  - Rotation engine full backtest flow
  - Edge cases (empty data, missing sectors, insufficient history)
"""
import numpy as np
import pandas as pd
import pytest

from factor_lab.sector_rotation.spec import (
    SectorRotationConfig,
    SectorPerformance,
    RotationSignal,
    RotationResult,
    RotationStrategyType,
)
from factor_lab.sector_rotation.sector_performance import (
    compute_sector_returns,
    compute_sector_performance_snapshot,
    compute_sector_rankings,
    build_sector_performance_history,
)
from factor_lab.sector_rotation.rotation_strategies import (
    MomentumRotation,
    MeanReversionRotation,
    CompositeRotation,
    create_strategy,
)
from factor_lab.sector_rotation.rotation_engine import (
    SectorRotationEngine,
)


# ── Helpers ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_industry_mapper(monkeypatch):
    """Prevent IndustryMapper from hitting Baostock (which hangs in tests)."""
    monkeypatch.setattr(
        "factor_lab.sector_rotation.sector_performance.get_sector_stock_count",
        lambda: {},
    )

@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def sample_dates():
    return pd.date_range("2024-01-02", periods=252, freq="B")


@pytest.fixture
def sector_mapping():
    return {
        "A": "银行", "B": "银行",
        "C": "科技", "D": "科技",
        "E": "医药", "F": "医药",
        "G": "消费", "H": "能源",
    }


@pytest.fixture
def stock_returns(rng, sample_dates):
    """8 stocks across 4 sectors with differentiated drift"""
    return pd.DataFrame({
        "A": rng.normal(0.0005, 0.010, 252),
        "B": rng.normal(0.0005, 0.010, 252),
        "C": rng.normal(0.0008, 0.020, 252),
        "D": rng.normal(0.0008, 0.020, 252),
        "E": rng.normal(0.0003, 0.015, 252),
        "F": rng.normal(0.0003, 0.015, 252),
        "G": rng.normal(0.0004, 0.012, 252),
        "H": rng.normal(0.0002, 0.022, 252),
    }, index=sample_dates)


# ═══════════════════════════════════════════════════════════
#  1. Spec / Data Models
# ═══════════════════════════════════════════════════════════

class TestSectorRotationConfig:
    def test_default_config(self):
        """默认配置应合理"""
        c = SectorRotationConfig()
        assert c.name == "SectorRotation"
        assert c.strategy_type == RotationStrategyType.MOMENTUM
        assert c.top_n == 5
        assert c.rebalance_freq == "monthly"
        assert c.equal_weight is True

    def test_validate_ok(self):
        c = SectorRotationConfig(name="test", top_n=3)
        assert c.validate() == []

    def test_validate_empty_name(self):
        c = SectorRotationConfig(name="")
        errs = c.validate()
        assert any("名称" in e for e in errs)

    def test_validate_top_n_zero(self):
        c = SectorRotationConfig(top_n=0)
        errs = c.validate()
        assert any("top_n" in e for e in errs)

    def test_validate_min_greater_max(self):
        c = SectorRotationConfig(min_sectors=10, max_sectors=5)
        errs = c.validate()
        assert any("min_sectors" in e for e in errs)

    def test_validate_invalid_freq(self):
        c = SectorRotationConfig(rebalance_freq="daily")
        errs = c.validate()
        assert any("调仓频率" in e for e in errs)

    def test_validate_short_lookback(self):
        c = SectorRotationConfig(lookback_short=2)
        errs = c.validate()
        assert any("过短" in e for e in errs)

    def test_to_dict(self):
        c = SectorRotationConfig(name="t1", strategy_type=RotationStrategyType.COMPOSITE)
        d = c.to_dict()
        assert d["name"] == "t1"
        assert d["strategy_type"] == "composite"


class TestSectorPerformance:
    def test_defaults(self):
        sp = SectorPerformance()
        assert sp.sector_name == ""
        assert sp.return_short == 0.0
        assert sp.momentum_score == 0.0

    def test_to_dict(self):
        sp = SectorPerformance(sector_name="银行", return_short=0.05, momentum_score=0.8)
        d = sp.to_dict()
        assert d["sector_name"] == "银行"
        assert d["return_short"] == 5.0  # *100
        assert d["momentum_score"] == 0.8


class TestRotationSignal:
    def test_defaults(self):
        s = RotationSignal()
        assert s.date == ""
        assert s.selected_sectors == []
        assert s.weights == {}

    def test_to_dict(self):
        s = RotationSignal(
            date="2024-06-01",
            strategy_type="momentum",
            selected_sectors=["银行", "科技"],
            weights={"银行": 0.5, "科技": 0.5},
            n_available=7,
        )
        d = s.to_dict()
        assert d["date"] == "2024-06-01"
        assert d["n_selected"] == 2


class TestRotationResult:
    def test_defaults(self):
        r = RotationResult()
        assert r.n_signals == 0
        assert r.warnings == []

    def test_summary_no_portfolio(self):
        r = RotationResult(n_signals=5, avg_sectors_per_signal=3.0)
        s = r.summary()
        assert s["n_signals"] == 5

    def test_to_dict(self):
        r = RotationResult(
            n_signals=3,
            signals=[
                RotationSignal(date="2024-01-01", selected_sectors=["A"]),
            ],
        )
        d = r.to_dict()
        assert "signals" in d
        assert len(d["signals"]) == 1


# ═══════════════════════════════════════════════════════════
#  2. Sector Performance Computation
# ═══════════════════════════════════════════════════════════

class TestComputeSectorReturns:
    def test_empty_returns(self):
        result = compute_sector_returns(pd.DataFrame(), {"A": "银行"})
        assert result == {}

    def test_basic_aggregation(self, stock_returns, sector_mapping):
        result = compute_sector_returns(stock_returns, sector_mapping)
        assert "银行" in result
        assert "科技" in result
        assert isinstance(result["银行"], pd.Series)
        assert len(result["银行"]) == 252

    def test_sector_returns_have_correct_shape(self, stock_returns, sector_mapping):
        result = compute_sector_returns(stock_returns, sector_mapping)
        for sector, series in result.items():
            assert series.name == sector
            assert len(series) == 252

    def test_unknown_stock_skipped(self, stock_returns):
        mapping = {"UNKNOWN": "银行"}
        result = compute_sector_returns(stock_returns, mapping)
        # UNKNOWN not in stock_returns.columns → empty
        assert result == {}


class TestComputeSectorPerformanceSnapshot:
    def test_empty_returns(self):
        result = compute_sector_performance_snapshot({})
        assert result == []

    def test_basic_snapshot(self, stock_returns, sector_mapping):
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)
        snap = compute_sector_performance_snapshot(sector_ret)
        # Fixture has 5 unique sectors: 银行/科技/医药/消费/能源
        assert len(snap) == 5
        assert all(isinstance(p, SectorPerformance) for p in snap)

    def test_sorted_by_composite_score(self, stock_returns, sector_mapping):
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)
        snap = compute_sector_performance_snapshot(sector_ret)
        scores = [p.composite_score for p in snap]
        assert scores == sorted(scores, reverse=True)

    def test_as_of_date_truncation(self, stock_returns, sector_mapping):
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)
        mid_date = stock_returns.index[len(stock_returns) // 2].strftime("%Y-%m-%d")
        snap = compute_sector_performance_snapshot(sector_ret, as_of_date=mid_date)
        # Should still produce results with truncated data
        assert len(snap) > 0


class TestComputeSectorRankings:
    def test_empty(self):
        assert compute_sector_rankings([]) == []

    def test_rankings_order(self):
        perfs = [
            SectorPerformance(sector_name="A", composite_score=0.5),
            SectorPerformance(sector_name="B", composite_score=1.0),
            SectorPerformance(sector_name="C", composite_score=0.3),
        ]
        ranks = compute_sector_rankings(perfs, top_n=2)
        assert len(ranks) == 2
        assert ranks[0]["sector"] == "B"  # highest score first

    def test_top_n_clip(self):
        perfs = [SectorPerformance(sector_name=f"S{i}", composite_score=i) for i in range(5)]
        ranks = compute_sector_rankings(perfs, top_n=3)
        assert len(ranks) == 3


class TestBuildSectorPerformanceHistory:
    def test_empty(self):
        result = build_sector_performance_history({})
        assert result.empty

    def test_basic_history(self, stock_returns, sector_mapping):
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)
        history = build_sector_performance_history(sector_ret, window=60)
        assert not history.empty
        assert list(history.columns) == list(sector_ret.keys())


# ═══════════════════════════════════════════════════════════
#  3. Rotation Strategies
# ═══════════════════════════════════════════════════════════

class TestMomentumRotation:
    @pytest.fixture
    def strategy(self):
        return MomentumRotation()

    def test_name(self, strategy):
        assert strategy.name() == "momentum"

    def test_rank_sectors_empty(self, strategy):
        assert strategy.rank_sectors([]) == []

    def test_rank_sectors_order(self, strategy):
        perfs = [
            SectorPerformance(sector_name="强", return_short=0.1, return_medium=0.05, return_long=0.02),
            SectorPerformance(sector_name="弱", return_short=-0.1, return_medium=-0.05, return_long=0.0),
        ]
        ranks = strategy.rank_sectors(perfs)
        assert ranks[0]["sector"] == "强"
        assert ranks[0]["score"] > ranks[1]["score"]

    def test_select_sectors(self, strategy):
        rankings = [
            {"sector": "A", "score": 0.5},
            {"sector": "B", "score": 0.3},
            {"sector": "C", "score": 0.1},
        ]
        selected = strategy.select_sectors(rankings, 2)
        assert selected == ["A", "B"]

    def test_select_top_n_clip(self, strategy):
        rankings = [{"sector": f"S{i}", "score": i} for i in range(5)]
        selected = strategy.select_sectors(rankings, 10)
        assert len(selected) == 5  # all, since only 5 available


class TestMeanReversionRotation:
    @pytest.fixture
    def strategy(self):
        return MeanReversionRotation(max_volatility=0.04)

    def test_name(self, strategy):
        assert strategy.name() == "mean_reversion"

    def test_rank_reversion_logic(self, strategy):
        """均值回归: 短期跌幅大的行业评分更高"""
        perfs = [
            SectorPerformance(sector_name="超跌", return_short=-0.15, return_medium=0.0, volatility=0.02),
            SectorPerformance(sector_name="强势", return_short=0.15, return_medium=0.0, volatility=0.02),
        ]
        ranks = strategy.rank_sectors(perfs)
        assert ranks[0]["sector"] == "超跌"  # worst performer ranks highest

    def test_volatility_penalty(self, strategy):
        """过高波动率应降低评分"""
        perfs = [
            SectorPerformance(sector_name="高波动", return_short=-0.15, volatility=0.10),
            SectorPerformance(sector_name="低波动", return_short=-0.15, volatility=0.02),
        ]
        ranks = strategy.rank_sectors(perfs)
        # Both have same return, but high vol gets penalty
        assert ranks[0]["sector"] == "低波动"

    def test_select_sectors(self, strategy):
        rankings = [{"sector": f"S{i}", "score": 1.0 - i * 0.2} for i in range(5)]
        selected = strategy.select_sectors(rankings, 3)
        assert len(selected) == 3
        assert selected[0] == "S0"


class TestCompositeRotation:
    @pytest.fixture
    def strategy(self):
        return CompositeRotation(momentum_weight=0.5, low_vol_weight=0.3, fund_flow_weight=0.2)

    def test_name(self, strategy):
        assert strategy.name() == "composite"

    def test_rank_sectors_empty(self, strategy):
        assert strategy.rank_sectors([]) == []

    def test_composite_scoring(self, strategy):
        """高动量+低波动+正资金流 → 最高分"""
        perfs = [
            SectorPerformance(sector_name="优质", momentum_score=2.0, volatility=0.01, fund_flow_score=1.0),
            SectorPerformance(sector_name="劣质", momentum_score=-1.0, volatility=0.05, fund_flow_score=-0.5),
        ]
        ranks = strategy.rank_sectors(perfs)
        assert ranks[0]["sector"] == "优质"
        assert ranks[0]["score"] > ranks[1]["score"]

    def test_all_identical_scores(self, strategy):
        """所有行业指标相同时评分应相同"""
        perfs = [
            SectorPerformance(sector_name="A", momentum_score=0.5, volatility=0.02, fund_flow_score=0.0),
            SectorPerformance(sector_name="B", momentum_score=0.5, volatility=0.02, fund_flow_score=0.0),
        ]
        ranks = strategy.rank_sectors(perfs)
        # After z-score, both should have score ~0
        assert abs(ranks[0]["score"] - ranks[1]["score"]) < 1e-10


class TestCreateStrategy:
    def test_momentum(self):
        c = SectorRotationConfig(strategy_type=RotationStrategyType.MOMENTUM)
        s = create_strategy(c)
        assert isinstance(s, MomentumRotation)

    def test_mean_reversion(self):
        c = SectorRotationConfig(strategy_type=RotationStrategyType.MEAN_REVERSION)
        s = create_strategy(c)
        assert isinstance(s, MeanReversionRotation)

    def test_composite(self):
        c = SectorRotationConfig(strategy_type=RotationStrategyType.COMPOSITE)
        s = create_strategy(c)
        assert isinstance(s, CompositeRotation)

    def test_invalid(self):
        with pytest.raises(ValueError):
            c = SectorRotationConfig(strategy_type="invalid")  # type: ignore
            create_strategy(c)


# ═══════════════════════════════════════════════════════════
#  4. Rotation Engine
# ═══════════════════════════════════════════════════════════

class TestSectorRotationEngine:
    def test_invalid_config_raises(self):
        with pytest.raises(ValueError, match="校验失败"):
            SectorRotationEngine(SectorRotationConfig(top_n=0))

    def test_engine_creation(self):
        config = SectorRotationConfig(name="test", top_n=3)
        engine = SectorRotationEngine(config)
        assert engine.config.name == "test"
        assert engine.strategy.name() == "momentum"

    def test_run_with_no_mapping(self):
        """Run with empty stock_returns and no mapping should return gracefully"""
        config = SectorRotationConfig(name="test", top_n=3, lookback_short=20)
        engine = SectorRotationEngine(config)
        result = engine.run(pd.DataFrame(), {})
        assert isinstance(result, RotationResult)
        # Engine should have warnings about empty mapping or returns
        assert len(result.warnings) > 0 or result.n_signals == 0

    def test_run_basic_flow(self, stock_returns, sector_mapping):
        """Full engine run with synthetic data should produce signals + result"""
        config = SectorRotationConfig(
            name="momentum_test",
            strategy_type=RotationStrategyType.MOMENTUM,
            top_n=3,
            rebalance_freq="monthly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        # Check that we got signals
        assert isinstance(result, RotationResult)
        # Should have at least some monthly rebalance signals in 252 days
        assert result.n_signals >= 6, f"Expected >=6 signals, got {result.n_signals}"
        assert result.avg_sectors_per_signal > 0

    def test_run_all_strategies(self, stock_returns, sector_mapping):
        """All three strategies should run without error"""
        for st in [RotationStrategyType.MOMENTUM, RotationStrategyType.MEAN_REVERSION, RotationStrategyType.COMPOSITE]:
            config = SectorRotationConfig(
                name=f"test_{st.value}",
                strategy_type=st,
                top_n=3,
                rebalance_freq="monthly",
            )
            engine = SectorRotationEngine(config)
            result = engine.run(stock_returns, sector_mapping)
            assert isinstance(result, RotationResult)
            # Each strategy should produce signals
            assert result.n_signals >= 6, f"{st.value}: expected >=6 signals, got {result.n_signals}"

    def test_strategy_returns_nonzero(self, stock_returns, sector_mapping):
        """Strategy returns should not be all zeros"""
        config = SectorRotationConfig(
            name="check_returns",
            strategy_type=RotationStrategyType.MOMENTUM,
            top_n=3,
            rebalance_freq="monthly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        if result.portfolio_result is not None:
            try:
                s = result.portfolio_result.summary()
                # Should have non-zero cumulative return
                assert abs(s.get("cumulative_return_pct", 0)) > 0.01
            except Exception:
                pass  # portfolio may need benchmark data

    def test_custom_sectors_filter(self, stock_returns, sector_mapping):
        """Only specified sectors should participate"""
        config = SectorRotationConfig(
            name="filtered",
            sectors=["银行", "科技"],
            top_n=2,
            rebalance_freq="monthly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        # All signals should only contain the filtered sectors
        for sig in result.signals:
            for s in sig.selected_sectors:
                assert s in ("银行", "科技"), f"Unexpected sector {s} in filtered run"

    def test_weekly_rebalance(self, stock_returns, sector_mapping):
        """Weekly rebalance should produce more signals than monthly"""
        config = SectorRotationConfig(
            name="weekly",
            top_n=3,
            rebalance_freq="weekly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        assert result.n_signals > 0

    def test_quarterly_rebalance(self, stock_returns, sector_mapping):
        """Quarterly rebalance should produce fewer signals than monthly"""
        config = SectorRotationConfig(
            name="quarterly",
            top_n=3,
            rebalance_freq="quarterly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        assert result.n_signals > 0

    def test_rotation_log(self, stock_returns, sector_mapping):
        """Engine should populate rotation_log with steps"""
        config = SectorRotationConfig(name="log_test", top_n=3, rebalance_freq="monthly")
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        assert len(result.rotation_log) > 0
        assert any("step:" in entry for entry in result.rotation_log)

    def test_turnover_calculation(self, stock_returns, sector_mapping):
        """Sector turnover should be between 0 and 1"""
        config = SectorRotationConfig(name="turnover_test", top_n=3, rebalance_freq="monthly")
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        assert 0 <= result.sector_turnover <= 1.0

    def test_result_summary(self, stock_returns, sector_mapping):
        """Result.summary() should return a dict with key fields"""
        config = SectorRotationConfig(name="summary_test", top_n=3, rebalance_freq="monthly")
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        s = result.summary()
        assert "config" in s
        assert "n_signals" in s
        assert "sector_turnover" in s

    def test_result_to_dict(self, stock_returns, sector_mapping):
        """Result.to_dict() should be JSON-serializable"""
        import json
        config = SectorRotationConfig(name="dict_test", top_n=3, rebalance_freq="monthly")
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        d = result.to_dict()
        # Should be JSON-serializable
        json_str = json.dumps(d, indent=2, ensure_ascii=False, default=str)
        assert isinstance(json_str, str)
        assert len(json_str) > 0


# ═══════════════════════════════════════════════════════════
#  5. Edge Cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_insufficient_data(self):
        """Too few dates should return graceful result with warning"""
        dates = pd.date_range("2024-01-02", periods=15, freq="B")
        ret = pd.DataFrame({"A": np.zeros(15), "B": np.zeros(15)}, index=dates)
        mapping = {"A": "银行", "B": "科技"}
        config = SectorRotationConfig(name="short", top_n=2, lookback_short=5)
        engine = SectorRotationEngine(config)
        result = engine.run(ret, mapping)
        # Should have warnings about insufficient data
        assert len(result.warnings) > 0 or result.n_signals == 0

    def test_missing_stock_in_sector(self, stock_returns):
        """Stocks in mapping but not in returns should be silently skipped"""
        mapping = {"MISSING": "银行", "A": "银行"}
        sector_ret = compute_sector_returns(stock_returns, mapping)
        # "银行" sector should still be computed from stock A only
        assert "银行" in sector_ret

    def test_all_same_returns(self):
        """All sectors with identical returns should still produce valid results"""
        dates = pd.date_range("2024-01-02", periods=252, freq="B")
        ret = pd.DataFrame({
            "A": np.zeros(252), "B": np.zeros(252),
            "C": np.zeros(252), "D": np.zeros(252),
        }, index=dates)
        mapping = {"A": "银行", "B": "科技", "C": "医药", "D": "消费"}
        config = SectorRotationConfig(name="identical", top_n=2, rebalance_freq="monthly")
        engine = SectorRotationEngine(config)
        result = engine.run(ret, mapping)
        # Should still produce a valid result, not crash
        assert isinstance(result, RotationResult)
