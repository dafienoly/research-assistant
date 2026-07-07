"""Research Loop 单元测试"""

import os, sys, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from factor_lab.research_loop import (
    ResearchConfig, ResearchNotebook, ResearchLoop, FactorCandidate, ResearchReport,
    _validate_expression, _normalize_expr,
)


class TestResearchNotebook:
    @pytest.fixture
    def nb(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "test_notebook.md")
        nb = ResearchNotebook(path)
        yield nb
        shutil.rmtree(tmp)

    def test_initialization(self, nb):
        assert nb.path.exists()
        content = nb.path.read_text()
        assert "当前 Baseline" in content
        assert "已完成实验" in content

    def test_get_baseline_default(self, nb):
        bl = nb.get_baseline()
        assert isinstance(bl, dict)

    def test_update_baseline(self, nb):
        nb.update_baseline("rank(close)", 85.5, 0.045)
        bl = nb.get_baseline()
        assert bl.get("expression") == "rank(close)"
        assert bl.get("score") == "85.5"

    def test_append_and_get_experiments(self, nb):
        nb.append_experiment("- test_expr | 评分=50 | IC=0.02")
        exps = nb.get_completed_experiments()
        assert len(exps) >= 1
        assert "test_expr" in exps[0]

    def test_get_next_directions_empty(self, nb):
        dirs = nb.get_next_directions()
        assert isinstance(dirs, list)


class TestExpressionHelpers:
    def test_validate_valid(self):
        err = _validate_expression("rank(close / ts_mean(close, 20))")
        assert err is None

    def test_validate_invalid(self):
        err = _validate_expression("rank(close / ts_mean(close)")
        assert err is not None

    def test_validate_v2_expression(self):
        err = _validate_expression("where(returns > 0 and close < ts_mean(close, 20), 1, 0)")
        assert err is None

    def test_normalize_expr(self):
        norm = _normalize_expr("rank( close / ts_mean(close, 20) )")
        assert " " not in norm
        assert "rank(close/ts_mean(close,20))" in norm


class TestParseLLMCandidates:
    @pytest.fixture
    def loop(self):
        tmp = tempfile.mkdtemp()
        nb_path = os.path.join(tmp, "research.md")
        config = ResearchConfig(max_rounds=2, convergence_window=3)
        loop = ResearchLoop(notebook_path=nb_path, config=config)
        yield loop
        shutil.rmtree(tmp)

    def test_parse_simple(self, loop):
        response = "rank(close) | momentum | 简单动量因子\nrank(volume) | vol | 量能因子"
        result = loop._parse_llm_candidates(response)
        assert len(result) == 2
        assert result[0]["name"] == "momentum"
        assert result[0]["expression"] == "rank(close)"

    def test_parse_with_hypothesis(self, loop):
        response = "rank(close/ts_mean(close,20)) | mom_20 | 20日动量因子"
        result = loop._parse_llm_candidates(response)
        assert len(result) == 1
        assert result[0]["hypothesis"] == "20日动量因子"

    def test_skip_code_fences(self, loop):
        response = "```\nrank(close) | m1 | test\n```"
        result = loop._parse_llm_candidates(response)
        assert len(result) == 0

    def test_empty_response(self, loop):
        result = loop._parse_llm_candidates("")
        assert result == []


class TestResearchLoop:
    @pytest.fixture
    def loop(self):
        tmp = tempfile.mkdtemp()
        nb_path = os.path.join(tmp, "research.md")
        config = ResearchConfig(max_rounds=2, convergence_window=3)
        loop = ResearchLoop(notebook_path=nb_path, config=config)
        yield loop
        shutil.rmtree(tmp)

    def test_initialization(self, loop):
        assert loop.config.max_rounds == 2
        assert loop.iteration == 0

    def test_parse_llm_candidates_valid(self, loop):
        response = "rank(close/ts_mean(close,20)) | mom_20 | 20日动量\n ts_delta(close,5)/close | mom_5d | 5日动量"
        candidates = loop._parse_llm_candidates(response)
        assert len(candidates) == 2

    def test_phase1_no_candidates_on_empty_response(self, loop):
        """LLM 空响应时返回空列表"""
        result = loop._parse_llm_candidates("")
        assert result == []

    def test_trajectory_tracking(self, loop):
        loop.trajectory.append({"expression": "e1", "score": 60, "ic": 0.03, "round": 1})
        loop.trajectory.append({"expression": "e2", "score": 70, "ic": 0.04, "round": 2})
        assert len(loop.trajectory) == 2
        assert loop.trajectory[-1]["score"] == 70

    def test_phase5_convergence_stop(self, loop):
        """收敛检测"""
        for i in range(5):
            loop.trajectory.append({"expression": f"e{i}", "score": 50, "ic": 0.02, "round": i})
        loop.best_score = 50
        assert loop._phase5_should_stop()  # 5轮无改善

    def test_phase5_max_rounds(self, loop):
        """轮次上限停止"""
        loop.iteration = loop.config.max_rounds
        assert loop._phase5_should_stop()


class TestResearchConfig:
    def test_default_config(self):
        config = ResearchConfig()
        assert config.max_rounds == 10
        assert config.convergence_window == 5
        assert config.max_concurrent == 10

    def test_custom_config(self):
        config = ResearchConfig(max_rounds=3, convergence_window=2)
        assert config.max_rounds == 3
        assert config.convergence_window == 2


class TestResearchReport:
    def test_empty_report(self):
        report = ResearchReport()
        assert report.rounds_completed == 0
        assert report.candidates == []
        assert report.best_factor is None

    def test_report_with_data(self):
        report = ResearchReport(
            rounds_completed=3,
            stop_reason="max_rounds",
            candidates=[{"name": "f1", "score": 80}],
            best_factor={"expression": "e1", "score": 80},
            new_knowledge=["k1"],
        )
        assert report.rounds_completed == 3
        assert len(report.candidates) == 1
        assert report.best_factor["score"] == 80
