"""Evolution Engine 单元测试"""

import os, sys, json, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np

from factor_lab.research_loop.trajectory import analyze_trajectory, TrajectoryMetrics
from factor_lab.research_loop.meta_evolution import select_strategy, EvolutionStrategy
from factor_lab.research_loop.mutation import MutationEngine, MutationStrategy
from factor_lab.research_loop.crossover import extract_top_segments, build_crossover_prompt


# ═══════════════════════════════════════════════════════
# Trajectory Analyzer Tests
# ═══════════════════════════════════════════════════════

class TestTrajectoryAnalyzer:
    def test_empty_trajectory(self):
        m = analyze_trajectory([])
        assert m.num_iterations == 0
        assert m.best_score == 0.0

    def test_single_iteration(self):
        m = analyze_trajectory([{"expression": "rank(close)", "score": 50}])
        assert m.num_iterations == 1
        assert m.best_score == 50.0
        assert m.best_expression == "rank(close)"

    def test_improving_trajectory(self):
        iters = [
            {"expression": "e1", "score": 30},
            {"expression": "e2", "score": 50},
            {"expression": "e3", "score": 70},
        ]
        m = analyze_trajectory(iters)
        assert m.num_iterations == 3
        assert m.best_score == 70.0
        assert m.best_expression == "e3"
        assert m.convergence_rate > 0  # upward slope

    def test_declining_trajectory(self):
        iters = [
            {"expression": "e1", "score": 80},
            {"expression": "e2", "score": 60},
            {"expression": "e3", "score": 40},
        ]
        m = analyze_trajectory(iters)
        assert m.best_score == 80.0
        assert m.consecutive_declines >= 1

    def test_volatility_reduces_stability(self):
        volatile = [
            {"expression": "e1", "score": 80},
            {"expression": "e2", "score": 20},
            {"expression": "e3", "score": 70},
        ]
        stable = [
            {"expression": "e1", "score": 55},
            {"expression": "e2", "score": 58},
            {"expression": "e3", "score": 62},
        ]
        m_v = analyze_trajectory(volatile)
        m_s = analyze_trajectory(stable)
        assert m_v.stability_score < m_s.stability_score

    def test_exploration_diversity(self):
        diverse = [
            {"expression": "e1", "score": 10},
            {"expression": "e2", "score": 90},
            {"expression": "e3", "score": 10},
        ]
        narrow = [
            {"expression": "e1", "score": 50},
            {"expression": "e2", "score": 52},
            {"expression": "e3", "score": 51},
        ]
        m_d = analyze_trajectory(diverse)
        m_n = analyze_trajectory(narrow)
        assert m_d.exploration_diversity > m_n.exploration_diversity

    def test_consecutive_declines(self):
        iters = [
            {"expression": "e1", "score": 80},
            {"expression": "e2", "score": 70},
            {"expression": "e3", "score": 60},
            {"expression": "e4", "score": 65},
        ]
        m = analyze_trajectory(iters)
        # last one went up, so consecutive declines from end = 0
        assert m.consecutive_declines == 0

    def test_recent_improvement(self):
        iters = [
            {"expression": "e1", "score": 30},
            {"expression": "e2", "score": 35},
            {"expression": "e3", "score": 40},
            {"expression": "e4", "score": 60},
        ]
        m = analyze_trajectory(iters)
        assert m.recent_improvement > 0


# ═══════════════════════════════════════════════════════
# Meta-Evolution Tests
# ═══════════════════════════════════════════════════════

class TestMetaEvolution:
    def test_simplify_on_deep_nesting(self):
        metrics = TrajectoryMetrics()
        strategy = select_strategy(metrics, current_score=50, nesting_depth=10)
        assert strategy == EvolutionStrategy.SIMPLIFY

    def test_exploit_on_high_score_low_diversity(self):
        metrics = TrajectoryMetrics(
            exploration_diversity=0.1,
            convergence_rate=0.5,
            stability_score=0.8,
            best_score=80,
            num_iterations=5,
        )
        strategy = select_strategy(metrics, current_score=65)
        assert strategy == EvolutionStrategy.EXPLOIT

    def test_recombine_on_plateau(self):
        metrics = TrajectoryMetrics(
            consecutive_declines=3,
            num_iterations=5,
            best_score=70,
            exploration_diversity=0.4,
        )
        strategy = select_strategy(metrics, current_score=40)
        assert strategy == EvolutionStrategy.RECOMBINE

    def test_explore_on_low_score_early(self):
        metrics = TrajectoryMetrics(num_iterations=2)
        strategy = select_strategy(metrics, current_score=20)
        assert strategy == EvolutionStrategy.EXPLORE

    def test_explore_on_high_diversity_low_convergence(self):
        metrics = TrajectoryMetrics(
            exploration_diversity=0.7,
            convergence_rate=0.2,
            num_iterations=5,
        )
        strategy = select_strategy(metrics, current_score=40)
        assert strategy == EvolutionStrategy.EXPLORE

    def test_exploit_on_medium_score_stable(self):
        metrics = TrajectoryMetrics(
            stability_score=0.8,
            exploration_diversity=0.4,
            convergence_rate=0.5,
            num_iterations=5,
        )
        strategy = select_strategy(metrics, current_score=45)
        assert strategy == EvolutionStrategy.EXPLOIT

    def test_recombine_on_large_gap(self):
        metrics = TrajectoryMetrics(
            best_score=90,
            num_iterations=3,
        )
        strategy = select_strategy(metrics, current_score=30)
        assert strategy == EvolutionStrategy.RECOMBINE

    def test_default_exploit(self):
        metrics = TrajectoryMetrics(num_iterations=1)
        strategy = select_strategy(metrics, current_score=50)
        assert strategy == EvolutionStrategy.EXPLOIT


# ═══════════════════════════════════════════════════════
# Mutation Engine Tests
# ═══════════════════════════════════════════════════════

class TestMutationEngine:
    def test_regenerate_on_low_score(self):
        engine = MutationEngine("rank(close)", {"backtest_summary": {}}, score=10)
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.REGENERATE_FULL

    def test_mutate_operator_on_zero_ic(self):
        engine = MutationEngine(
            "rank(close)",
            {"backtest_summary": {"ic_mean": 0.001}},
            score=50,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.MUTATE_OPERATOR

    def test_signal_type_on_negative_ic(self):
        engine = MutationEngine(
            "rank(close)",
            {"backtest_summary": {"ic_mean": -0.05}},
            score=50,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.MUTATE_SIGNAL_TYPE

    def test_simplify_on_deep_nesting(self):
        # Deep nesting > 8, multi-signal, good metrics
        expr = "rank(ts_mean(ts_mean(ts_mean(ts_mean(ts_mean(ts_mean(ts_mean(ts_mean(ts_mean(close * volume,5),10),5),10),5),10),5),10),20))"
        assert MutationEngine(expr, {}, 0)._count_nesting(expr) > 8, "need nesting > 8"
        engine = MutationEngine(
            expr,
            {"backtest_summary": {"ic_mean": 0.03, "ic_ir": 0.8}},
            score=60,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.SIMPLIFY

    def test_nonlinear_on_medium_score(self):
        engine = MutationEngine(
            "close / ts_mean(close, 20)",
            {"backtest_summary": {"ic_mean": 0.02, "ic_ir": 0.3}},
            score=35,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.MUTATE_NONLINEAR

    def test_normalization_on_low_ir(self):
        engine = MutationEngine(
            "close / ts_mean(close, 20)",
            {"backtest_summary": {"ic_mean": 0.03, "ic_ir": 0.3}},
            score=55,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.MUTATE_NORMALIZATION

    def test_interaction_on_single_signal(self):
        engine = MutationEngine(
            "rank(close)",
            {"backtest_summary": {"ic_mean": 0.03, "ic_ir": 0.8}},
            score=60,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.MUTATE_INTERACTION

    def test_window_on_default(self):
        engine = MutationEngine(
            "rank(ts_corr(close, volume, 20))",  # multi-signal
            {"backtest_summary": {"ic_mean": 0.03, "ic_ir": 0.8, "turnover": 0.1}},
            score=60,
        )
        d = engine.diagnose_failure()
        assert d.strategy == MutationStrategy.MUTATE_WINDOW

    def test_build_prompt(self):
        engine = MutationEngine("rank(close)", {"backtest_summary": {}}, score=50)
        prompt = engine.build_mutation_prompt()
        assert "当前因子" in prompt
        assert "评分" in prompt

    def test_count_nesting(self):
        engine = MutationEngine("rank(ts_mean(close, 20))", {}, 0)
        assert engine._count_nesting(engine.expression) == 2
        assert engine._count_nesting("rank(ts_mean(ts_std(close, 20), 20))") == 3

    def test_has_normalization(self):
        assert MutationEngine("rank(close)", {}, 0)._has_normalization("rank(close)")
        assert not MutationEngine("close", {}, 0)._has_normalization("close")

    def test_is_single_signal(self):
        assert MutationEngine("rank(close)", {}, 0)._is_single_signal()
        assert not MutationEngine("close * volume", {}, 0)._is_single_signal()


# ═══════════════════════════════════════════════════════
# Crossover Engine Tests
# ═══════════════════════════════════════════════════════

class TestCrossoverEngine:
    def test_empty_segments(self):
        assert extract_top_segments([]) == []

    def test_extract_top(self):
        iters = [
            {"expression": "rank(a)", "score": 80},
            {"expression": "rank(b)", "score": 60},
            {"expression": "rank(c)", "score": 39},  # below 80*0.5=40
        ]
        segments = extract_top_segments(iters)
        assert len(segments) == 2
        assert segments[0]["score"] == 80
        assert segments[1]["score"] == 60

    def test_min_score_ratio_filter(self):
        iters = [
            {"expression": "rank(a)", "score": 100},
            {"expression": "rank(b)", "score": 30},
        ]
        segments = extract_top_segments(iters, min_score_ratio=0.8)
        assert len(segments) == 1  # only 80+ qualifies
        assert segments[0]["score"] == 100

    def test_max_segments_limit(self):
        iters = [{"expression": f"e{i}", "score": 90 - i} for i in range(10)]
        segments = extract_top_segments(iters, max_segments=3)
        assert len(segments) == 3

    def test_build_crossover_prompt(self):
        iters = [
            {"expression": "rank(ts_delta(close,5))", "score": 80, "hypothesis": "5日动量"},
            {"expression": "rank(volume/ts_mean(volume,20))", "score": 70},
        ]
        segments = extract_top_segments(iters)
        prompt = build_crossover_prompt(segments, "rank(close)", 50)
        assert "当前因子" in prompt
        assert "历史高分片段" in prompt
        assert "5日动量" in prompt
