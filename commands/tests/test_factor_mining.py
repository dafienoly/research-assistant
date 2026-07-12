"""V6.6 Factor Mining Agent — 因子挖掘 Agent 测试

测试覆盖:
  - FactorCandidate 数据结构
  - WindowVariationGenerator: 窗口变体生成
  - CrossSectionalGenerator: 横截面变体生成
  - CombinationGenerator: 组合变体生成
  - CandidateGenerator: 统一生成器
  - CandidateEvaluator: RankIC 计算、分层回测、评分
  - FactorMiningEngine: 完整挖掘流程
  - Built-in Skill: factor-mining 注册和执行
  - CLI 命令解析
  - 边界条件: 空注册表、空数据、缺失列
"""

import sys, os, json, tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
import pandas as pd

from factor_lab.factor_mining import (
    FactorMiningEngine,
    MiningConfig,
    MiningReport,
    FactorCandidate,
    CandidateGenerator,
    WindowVariationGenerator,
    CrossSectionalGenerator,
    CombinationGenerator,
    CandidateEvaluator,
    EvaluationResult,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def sample_registry() -> list[dict]:
    """模拟因子注册表"""
    return [
        {"name": "ret5", "category": "momentum", "description": "5日动量"},
        {"name": "ret10", "category": "momentum", "description": "10日动量"},
        {"name": "ret20", "category": "momentum", "description": "20日动量"},
        {"name": "vol_ratio20", "category": "volume", "description": "20日量比"},
        {"name": "vol_ratio60", "category": "volume", "description": "60日量比"},
        {"name": "ret_std20", "category": "volatility", "description": "20日波动"},
        {"name": "close_gt_ma20", "category": "trend", "description": "价格在MA20上"},
        {"name": "ma5_gt_ma10", "category": "trend", "description": "5/10均线比"},
        {"name": "ma10_gt_ma20", "category": "trend", "description": "10/20均线比"},
        {"name": "ma20_gt_ma60", "category": "trend", "description": "20/60均线比"},
    ]


@pytest.fixture()
def sample_kline() -> pd.DataFrame:
    """合成 K 线数据 (20只股票 x 120个交易日)"""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-01-02", periods=120, freq="B")
    symbols = [f"{i:06d}.SZ" for i in range(1, 21)]
    rows = []
    for sym in symbols:
        price = 100.0
        for d in dates:
            ret = rng.normal(0, 0.025)
            price *= (1 + ret)
            rows.append({
                "date": d, "symbol": sym,
                "close": price, "volume": max(1, int(rng.exponential(5e6))),
            })
    df = pd.DataFrame(rows)
    df["ret1"] = df.groupby("symbol")["close"].transform(
        lambda x: x.pct_change(-1)
    )
    return df


# ═══════════════════════════════════════════════════════════════════
# FactorCandidate Tests
# ═══════════════════════════════════════════════════════════════════

class TestFactorCandidate:

    def test_create_minimal(self):
        cand = FactorCandidate(
            name="test_factor",
            category="momentum",
            description="Test factor",
            generation_method="window_variation",
            source="ret5",
            expression="pct_change(8)",
        )
        assert cand.name == "test_factor"
        assert cand.category == "momentum"
        assert cand.generation_method == "window_variation"

    def test_create_with_func(self):
        cand = FactorCandidate(
            name="ret8",
            category="momentum",
            description="8日动量",
            generation_method="window_variation",
            source="ret5",
            expression="pct_change(8)",
            func=lambda df: df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(8)
            ),
            params={"window": 8},
        )
        assert cand.func is not None
        assert cand.params == {"window": 8}

    def test_to_dict(self):
        cand = FactorCandidate(
            name="test",
            category="volume",
            description="Test",
            generation_method="cross_sectional",
            source="vol_ratio20",
            expression="rank(vol_ratio20)",
        )
        d = cand.to_dict()
        assert d["name"] == "test"
        assert d["category"] == "volume"
        assert d["generation_method"] == "cross_sectional"


# ═══════════════════════════════════════════════════════════════════
# WindowVariationGenerator Tests
# ═══════════════════════════════════════════════════════════════════

class TestWindowVariationGenerator:

    def test_generate_from_empty_registry(self):
        gen = WindowVariationGenerator([])
        candidates = gen.generate()
        assert len(candidates) > 0

    def test_generate_skips_existing(self, sample_registry):
        gen = WindowVariationGenerator(sample_registry)
        candidates = gen.generate()
        names = {c.name for c in candidates}
        # ret5/10/20 exist — should not be generated
        assert "ret5" not in names
        assert "ret20" not in names
        # ret3, ret8 etc. should be generated
        assert "ret3" in names
        assert "ret8" in names

    def test_generate_trend_windows(self, sample_registry):
        gen = WindowVariationGenerator(sample_registry)
        candidates = gen.generate()
        trend = [c for c in candidates if c.category == "trend"]
        assert len(trend) > 0
        for c in trend:
            assert c.generation_method == "window_variation"

    def test_registry_with_missing_fields(self):
        gen = WindowVariationGenerator([{"name": "ret5"}])  # no category field
        candidates = gen.generate()
        assert len(candidates) > 0
        assert "ret5" not in {c.name for c in candidates}

    def test_generated_candidate_has_func(self):
        gen = WindowVariationGenerator()
        candidates = gen.generate()
        for c in candidates[:3]:
            assert c.func is not None, f"{c.name} missing func"


# ═══════════════════════════════════════════════════════════════════
# CrossSectionalGenerator Tests
# ═══════════════════════════════════════════════════════════════════

class TestCrossSectionalGenerator:

    def test_generates_rank_and_zscore(self, sample_registry):
        gen = CrossSectionalGenerator(sample_registry)
        candidates = gen.generate()
        cand_names = {c.name for c in candidates}
        assert any("_rank" in n for n in cand_names)
        assert any("_zscore" in n for n in cand_names)

    def test_generates_for_target_categories(self, sample_registry):
        gen = CrossSectionalGenerator(sample_registry)
        candidates = gen.generate()
        for c in candidates:
            assert c.category in CrossSectionalGenerator.TARGET_CATEGORIES

    def test_skips_untargeted_categories(self):
        registry = [{"name": "factor_x", "category": "quality"}]
        gen = CrossSectionalGenerator(registry)
        candidates = gen.generate()
        assert len(candidates) == 0

    def test_generated_has_func(self, sample_registry):
        gen = CrossSectionalGenerator(sample_registry)
        candidates = gen.generate()
        for c in candidates[:3]:
            assert c.func is not None, f"{c.name} missing func"

    def test_rank_variants(self, sample_registry, sample_kline):
        gen = CrossSectionalGenerator(sample_registry)
        candidates = gen.generate()
        rank_cands = [c for c in candidates if c.name.endswith("_rank")]
        if rank_cands:
            # Compute the base factor column needed by the rank function
            # rank_cands[0] references its source factor column name
            source = rank_cands[0].source  # e.g. "ret5"
            if source not in sample_kline.columns:
                sample_kline[source] = sample_kline.groupby("symbol")["close"].transform(
                    lambda x: x.pct_change(5)
                )
            result = rank_cands[0].func(sample_kline)
            assert len(result) == len(sample_kline)
            assert result.dtype in (np.float64, np.float32)
            assert len(result) == len(sample_kline)
            assert result.dtype in (np.float64, np.float32)


# ═══════════════════════════════════════════════════════════════════
# CombinationGenerator Tests
# ═══════════════════════════════════════════════════════════════════

class TestCombinationGenerator:

    def test_generates_combinations(self, sample_registry):
        gen = CombinationGenerator(sample_registry)
        candidates = gen.generate(max_combinations=10)
        assert len(candidates) > 0
        for c in candidates:
            assert c.generation_method == "combination"

    def test_combination_names(self, sample_registry):
        gen = CombinationGenerator(sample_registry)
        candidates = gen.generate(max_combinations=5)
        for c in candidates:
            assert "_plus_" in c.name or "_minus_" in c.name or "_mul_" in c.name

    def test_max_combinations(self, sample_registry):
        gen = CombinationGenerator(sample_registry)
        candidates = gen.generate(max_combinations=3)
        assert len(candidates) <= 9  # 3 combos per pair, max 3 pairs

    def test_generated_has_func(self, sample_registry):
        gen = CombinationGenerator(sample_registry)
        candidates = gen.generate(max_combinations=5)
        for c in candidates:
            assert c.func is not None, f"{c.name} missing func"


# ═══════════════════════════════════════════════════════════════════
# CandidateGenerator (Unified) Tests
# ═══════════════════════════════════════════════════════════════════

class TestCandidateGenerator:

    def test_generate_all(self, sample_registry):
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all()
        assert len(candidates) > 0

    def test_generate_without_window(self, sample_registry):
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all(include_window=False)
        # Without window variations, should have cross-sectional + combinations
        types = {c.generation_method for c in candidates}
        assert "window_variation" not in types

    def test_generate_without_combinations(self, sample_registry):
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all(include_combinations=False)
        types = {c.generation_method for c in candidates}
        assert "combination" not in types

    def test_no_duplicate_names(self, sample_registry):
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all()
        names = [c.name for c in candidates]
        assert len(names) == len(set(names))

    def test_empty_registry(self):
        gen = CandidateGenerator([])
        candidates = gen.generate_all()
        assert len(candidates) > 0  # window variations don't need existing factors

    def test_all_candidates_have_func(self, sample_registry):
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all(max_combinations=5)
        for c in candidates:
            assert c.func is not None, f"{c.name} missing func"


# ═══════════════════════════════════════════════════════════════════
# CandidateEvaluator Tests
# ═══════════════════════════════════════════════════════════════════

class TestCandidateEvaluator:

    def test_evaluate_single_candidate(self, sample_kline):
        evaluator = CandidateEvaluator()
        candidate = FactorCandidate(
            name="ret3",
            category="momentum",
            description="3日动量",
            generation_method="window_variation",
            source="ret5",
            expression="pct_change(3)",
            func=lambda df: df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(3)
            ),
        )
        results = evaluator.evaluate(sample_kline, [candidate])
        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].n_dates > 0
        assert isinstance(results[0].ic_mean, float)
        assert isinstance(results[0].ic_ir, float)

    def test_evaluate_multiple(self, sample_kline):
        evaluator = CandidateEvaluator()
        candidates = [
            FactorCandidate(
                name="ret3",
                category="momentum",
                description="3日动量",
                generation_method="window_variation",
                source="ret5",
                expression="pct_change(3)",
                func=lambda df: df.groupby("symbol")["close"].transform(
                    lambda x: x.pct_change(3)
                ),
            ),
            FactorCandidate(
                name="ret8",
                category="momentum",
                description="8日动量",
                generation_method="window_variation",
                source="ret10",
                expression="pct_change(8)",
                func=lambda df: df.groupby("symbol")["close"].transform(
                    lambda x: x.pct_change(8)
                ),
            ),
        ]
        results = evaluator.evaluate(sample_kline, candidates)
        assert len(results) == 2
        # Results should be sorted by score descending
        assert abs(results[0].score) >= abs(results[1].score)

    def test_evaluate_candidate_no_func(self, sample_kline):
        evaluator = CandidateEvaluator()
        candidate = FactorCandidate(
            name="no_func",
            category="momentum",
            description="No func",
            generation_method="window_variation",
            source="none",
            expression="none",
        )
        results = evaluator.evaluate(sample_kline, [candidate])
        assert len(results) == 1
        assert results[0].status == "error"

    def test_evaluate_with_rank_candidate(self, sample_kline):
        """横截面排名候选的评估"""
        sample_kline["ret5"] = sample_kline.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(5)
        )
        evaluator = CandidateEvaluator()
        candidate = FactorCandidate(
            name="ret5_rank",
            category="momentum",
            description="ret5 rank",
            generation_method="cross_sectional",
            source="ret5",
            expression="rank(ret5)",
            func=lambda df: df.groupby("date")["ret5"].rank(pct=True),
        )
        results = evaluator.evaluate(sample_kline, [candidate])
        assert len(results) == 1
        assert results[0].status == "ok"

    def test_evaluation_results_detailed(self, sample_kline):
        evaluator = CandidateEvaluator()
        candidate = FactorCandidate(
            name="ret3",
            category="momentum",
            description="3日动量",
            generation_method="window_variation",
            source="ret5",
            expression="pct_change(3)",
            func=lambda df: df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(3)
            ),
        )
        results = evaluator.evaluate(sample_kline, [candidate])
        r = results[0]
        assert isinstance(r.layer1_ret, float)
        assert isinstance(r.layer5_ret, float)
        assert isinstance(r.spread_ret, float)
        assert isinstance(r.ic_positive_ratio, float)
        assert 0 <= r.ic_positive_ratio <= 1

    def test_empty_dataframe(self):
        evaluator = CandidateEvaluator()
        empty_df = pd.DataFrame(columns=["date", "symbol", "close", "ret1"])
        candidate = FactorCandidate(
            name="ret3", category="momentum", description="3日",
            generation_method="window_variation", source="ret5",
            expression="pct_change(3)",
            func=lambda df: df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(3)
            ),
        )
        results = evaluator.evaluate(empty_df, [candidate])
        assert len(results) == 1
        assert results[0].status == "error"

    def test_insufficient_data(self):
        """Fewer than 100 rows should be rejected"""
        evaluator = CandidateEvaluator()
        small = pd.DataFrame({
            "date": pd.date_range("2025-01-02", periods=5, freq="B"),
            "symbol": "000001.SZ",
            "close": [100, 101, 102, 103, 104],
            "ret1": [0.01, 0.01, 0.01, 0.01, 0.01],
        })
        candidate = FactorCandidate(
            name="test", category="momentum", description="Test",
            generation_method="window_variation", source="none",
            expression="none",
            func=lambda df: df["close"].pct_change(1),
        )
        results = evaluator.evaluate(small, [candidate])
        assert len(results) == 1
        assert results[0].status == "error"

    def test_rank_ic_computation(self, sample_kline):
        evaluator = CandidateEvaluator()
        sample_kline["ret5"] = sample_kline.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(5)
        )
        ic_result = evaluator._compute_rank_ic(sample_kline, "ret5", "ret1")
        assert "ic_mean" in ic_result
        assert "ic_std" in ic_result
        assert "ic_ir" in ic_result
        assert "n_dates" in ic_result
        if ic_result["n_dates"] > 0:
            assert ic_result["n_dates"] <= sample_kline["date"].nunique()

    def test_layer_returns(self, sample_kline):
        evaluator = CandidateEvaluator(n_layers=5)
        sample_kline["ret5"] = sample_kline.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(5)
        )
        layers = evaluator._compute_layer_returns(sample_kline, "ret5", "ret1")
        assert "layer_1" in layers
        assert "layer_5" in layers
        assert "spread" in layers

    def test_compute_score(self):
        evaluator = CandidateEvaluator()
        ic_result = {"ic_mean": 0.03, "ic_std": 0.15, "ic_ir": 0.20}
        layers = {"layer_1": 0.001, "layer_5": -0.001, "spread": 0.002}
        score = evaluator._compute_score(ic_result, layers)
        assert score > 0
        assert isinstance(score, float)


# ═══════════════════════════════════════════════════════════════════
# FactorMiningEngine Tests
# ═══════════════════════════════════════════════════════════════════

class TestFactorMiningEngine:

    def test_engine_create(self):
        engine = FactorMiningEngine()
        assert engine.config is not None
        assert engine.config.top_n == 10

    def test_engine_with_custom_config(self):
        config = MiningConfig(top_n=5, max_candidates=20, include_combinations=False)
        engine = FactorMiningEngine(config=config)
        assert engine.config.top_n == 5
        assert engine.config.max_candidates == 20

    def test_mine_basic(self, sample_kline):
        engine = FactorMiningEngine(
            config=MiningConfig(top_n=3, max_candidates=10, include_combinations=False),
            registry=[{"name": "ret5", "category": "momentum"}],
        )
        report = engine.mine(sample_kline)
        assert isinstance(report, MiningReport)
        assert report.existing_factor_count >= 1
        assert report.candidates_generated > 0
        assert report.timestamp

    def test_mine_report_top_candidates(self, sample_kline):
        engine = FactorMiningEngine(
            config=MiningConfig(top_n=3, max_candidates=10, include_combinations=False),
            registry=[{"name": "ret5", "category": "momentum"}],
        )
        report = engine.mine(sample_kline)
        assert len(report.top_candidates) <= 3
        if report.top_candidates:
            first = report.top_candidates[0]
            assert "candidate" in first
            assert "ic_mean" in first
            assert "ic_ir" in first
            assert "score" in first

    def test_mine_report_summary_counts(self, sample_kline):
        engine = FactorMiningEngine(
            config=MiningConfig(top_n=5, max_candidates=20, include_combinations=False),
            registry=[
                {"name": "ret5", "category": "momentum"},
                {"name": "vol_ratio20", "category": "volume"},
            ],
        )
        report = engine.mine(sample_kline)
        assert report.candidates_generated > 0
        assert report.existing_factor_count == 2
        assert "momentum" in report.registry_summary
        assert "volume" in report.registry_summary

    def test_mine_prints_summary(self, sample_kline, capsys):
        engine = FactorMiningEngine(
            config=MiningConfig(top_n=3, max_candidates=5, include_combinations=False),
            registry=[{"name": "ret5", "category": "momentum"}],
        )
        report = engine.mine(sample_kline)
        report.print_summary()
        captured = capsys.readouterr()
        assert "因子挖掘报告" in captured.out
        assert "Top 候选因子" in captured.out

    def test_mine_with_empty_dataframe(self):
        engine = FactorMiningEngine(
            config=MiningConfig(top_n=3, max_candidates=5),
        )
        empty_df = pd.DataFrame(columns=["date", "symbol", "close"])
        report = engine.mine(empty_df)
        assert report.candidates_generated > 0
        assert report.candidates_evaluated == 0  # no rows to evaluate

    def test_load_registry_from_factor_base(self):
        """Should load from factor_base.list_factors() without error"""
        engine = FactorMiningEngine()
        assert len(engine.registry) > 0
        for f in engine.registry:
            assert "name" in f
            assert "category" in f

    def test_mine_with_different_configs(self, sample_kline):
        """Test that different configs produce different candidate counts"""
        engine_window = FactorMiningEngine(
            config=MiningConfig(top_n=5, max_candidates=50,
                                include_window=True, include_cross_sectional=False,
                                include_combinations=False),
        )
        report_w = engine_window.mine(sample_kline)

        engine_cs = FactorMiningEngine(
            config=MiningConfig(top_n=5, max_candidates=50,
                                include_window=False, include_cross_sectional=True,
                                include_combinations=False),
        )
        report_cs = engine_cs.mine(sample_kline)
        # Window + cross-sectional should have unique counts
        assert report_w.candidates_generated != report_cs.candidates_generated


# ═══════════════════════════════════════════════════════════════════
# MiningReport Tests
# ═══════════════════════════════════════════════════════════════════

class TestMiningReport:

    def test_report_create(self):
        report = MiningReport(timestamp="2026-01-01T00:00:00")
        assert report.timestamp == "2026-01-01T00:00:00"
        assert report.existing_factor_count == 0

    def test_report_to_dict(self):
        report = MiningReport(
            timestamp="2026-01-01T00:00:00",
            existing_factor_count=5,
            candidates_generated=20,
            candidates_evaluated=15,
            duration_ms=1234.5,
        )
        d = report.to_dict()
        assert d["existing_factor_count"] == 5
        assert d["candidates_generated"] == 20
        assert d["duration_ms"] == 1234.5

    def test_report_with_top_candidates(self):
        report = MiningReport(
            timestamp="2026-01-01T00:00:00",
            top_candidates=[
                {"candidate": {"name": "ret3"}, "ic_mean": 0.02, "ic_ir": 0.15, "score": 0.5},
            ],
        )
        assert len(report.top_candidates) == 1
        assert report.top_candidates[0]["candidate"]["name"] == "ret3"


# ═══════════════════════════════════════════════════════════════════
# Built-in Skill Tests
# ═══════════════════════════════════════════════════════════════════

class TestFactorMiningSkill:

    def test_skill_in_builtins(self):
        from factor_lab.research_skill.builtins import BUILTIN_SKILLS, FACTOR_MINING_SKILL
        assert FACTOR_MINING_SKILL.skill_id == "factor-mining"
        assert FACTOR_MINING_SKILL in BUILTIN_SKILLS

    def test_skill_spec_valid(self):
        from factor_lab.research_skill.builtins import FACTOR_MINING_SKILL
        from factor_lab.research_skill.skill_spec import validate_spec, SkillCategory, VALID_CATEGORIES
        errors = validate_spec(FACTOR_MINING_SKILL)
        assert errors == [], f"Validation errors: {errors}"
        assert FACTOR_MINING_SKILL.category in VALID_CATEGORIES

    def test_skill_has_params(self):
        from factor_lab.research_skill.builtins import FACTOR_MINING_SKILL
        param_names = {p.name for p in FACTOR_MINING_SKILL.params}
        assert "top_n" in param_names
        assert "include_window" in param_names
        assert "include_cross_sectional" in param_names
        assert "include_combinations" in param_names
        assert "generate_demo" in param_names

    def test_skill_execute_with_demo_data_is_blocked(self, tmp_path, monkeypatch):
        from factor_lab.research_skill import SkillRegistry, SkillRuntime
        from factor_lab.research_skill.builtins import FACTOR_MINING_SKILL
        from factor_lab.research_skill.skill_runtime import RUNTIME_ROOT

        monkeypatch.setattr(
            "factor_lab.research_skill.skill_runtime.RUNTIME_ROOT",
            tmp_path / "skill_runs",
        )

        registry = SkillRegistry(root=tmp_path / "skill_registry")
        runtime = SkillRuntime(registry=registry, runtime_root=tmp_path / "skill_runs")

        registry.register(FACTOR_MINING_SKILL)
        result = runtime.run("factor-mining", {"top_n": 5, "generate_demo": True})

        assert result.status == "completed"
        assert result.data["status"] == "BLOCKED"
        assert "禁止 demo/random" in result.data["error"]

    def test_skill_execute_minimal_params(self, tmp_path, monkeypatch):
        """Run with minimal params (defaults)"""
        from factor_lab.research_skill import SkillRegistry, SkillRuntime
        from factor_lab.research_skill.builtins import FACTOR_MINING_SKILL
        from factor_lab.research_skill.skill_runtime import RUNTIME_ROOT

        monkeypatch.setattr(
            "factor_lab.research_skill.skill_runtime.RUNTIME_ROOT",
            tmp_path / "skill_runs",
        )

        registry = SkillRegistry(root=tmp_path / "skill_registry")
        runtime = SkillRuntime(registry=registry, runtime_root=tmp_path / "skill_runs")
        registry.register(FACTOR_MINING_SKILL)

        # No params should use defaults
        result = runtime.run("factor-mining", {})
        assert result.status == "completed"
        assert result.data["status"] == "BLOCKED"


# ═══════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestMiningIntegration:

    def test_full_mining_pipeline(self, sample_kline):
        """完整挖掘流程: 配置 → 生成 → 评估 → 报告"""
        config = MiningConfig(
            top_n=3,
            max_candidates=15,
            include_window=True,
            include_cross_sectional=True,
            include_combinations=False,
        )
        engine = FactorMiningEngine(config=config)
        report = engine.mine(sample_kline)

        assert report.candidates_generated > 0
        assert report.duration_ms > 0

        if report.top_candidates:
            top = report.top_candidates[0]
            assert "candidate" in top
            assert "ic_mean" in top
            assert "score" in top

    def test_candidate_generator_produces_evaluable_factors(self, sample_kline, sample_registry):
        """Generated candidates can actually compute factor values"""
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all(max_combinations=5)

        for cand in candidates[:5]:
            if cand.func is not None:
                try:
                    result = cand.func(sample_kline)
                    assert len(result) == len(sample_kline) or cand.generation_method == "cross_sectional"
                except Exception as e:
                    pytest.fail(f"Candidate {cand.name} compute failed: {e}")

    def test_evaluator_handles_all_generator_types(self, sample_kline, sample_registry):
        """评估器能处理所有类型的候选"""
        gen = CandidateGenerator(sample_registry)
        candidates = gen.generate_all(max_combinations=5)

        evaluator = CandidateEvaluator()
        results = evaluator.evaluate(sample_kline, candidates)

        assert len(results) > 0
        # At least some should succeed
        ok_count = sum(1 for r in results if r.status == "ok")
        assert ok_count > 0
