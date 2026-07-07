"""Adversarial Validation + Fitness Scoring 单元测试"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
import pandas as pd

from factor_lab.validation.adversarial import (
    AdversarialValidator, run_adversarial_validation,
    _daily_spearman_ic,
)
from factor_lab.scoring.fitness import compute_fitness, compute_cloud_alignment, enhanced_score


# ═══════════════════════════════════════════════════════
# Test Helpers
# ═══════════════════════════════════════════════════════

def _make_dummy_factor_df(n_stocks=10, n_dates=60) -> pd.DataFrame:
    """创建模拟因子 DataFrame"""
    rng = np.random.RandomState(42)
    rows = []
    stocks = [f"s{i:04d}" for i in range(n_stocks)]
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    for stock in stocks:
        for date in dates:
            rows.append({
                "stock_code": stock,
                "trade_date": date,
                "factor_value": rng.randn(),
                "daily_ret": rng.randn() * 0.02,
            })
    df = pd.DataFrame(rows)
    return df


# ═══════════════════════════════════════════════════════
# Adversarial Validation Tests
# ═══════════════════════════════════════════════════════

class TestDailySpearmanIC:
    def test_basic_ic_calculation(self):
        df = _make_dummy_factor_df(n_stocks=5, n_dates=10)
        ic = _daily_spearman_ic(df, factor_col="factor_value", ret_col="daily_ret")
        assert isinstance(ic, pd.Series)
        assert len(ic) > 0

    def test_insufficient_data(self):
        df = pd.DataFrame({"factor_value": [1], "daily_ret": [0.1],
                           "trade_date": ["2025-01-01"]})
        ic = _daily_spearman_ic(df, factor_col="factor_value", ret_col="daily_ret")
        assert len(ic) == 0


class TestAdversarialValidator:
    @pytest.fixture
    def validator(self):
        df = _make_dummy_factor_df(n_stocks=20, n_dates=120)
        return AdversarialValidator(df, holding_period=5)

    def test_initialization(self, validator):
        assert validator.holding_period == 5
        assert "fwd_ret" in validator.df.columns
        assert len(validator.df) > 0

    def test_run_all(self, validator):
        result = validator.run_all()
        assert result.total_count == 4
        assert 0 <= result.score <= 100
        assert result.recommendation in ("通过", "基本通过", "存疑", "高风险")
        assert len(result.tests) == 4

    def test_label_permutation(self, validator):
        result = validator.test_label_permutation(n_perms=10)
        assert result.name == "标签置换检验"
        assert isinstance(result.passed, bool)
        assert "real_ic" in result.details

    def test_temporal_shuffle(self, validator):
        result = validator.test_temporal_shuffle(block_size=10)
        assert result.name == "时序打乱检验"
        assert isinstance(result.passed, bool)

    def test_random_universe(self, validator):
        result = validator.test_random_universe(n_trials=10)
        assert result.name == "随机股票池检验"
        assert isinstance(result.passed, bool)

    def test_noise_injection(self, validator):
        result = validator.test_noise_injection()
        assert result.name == "噪声注入检验"
        assert isinstance(result.passed, bool)
        assert "retention_at_0.5x" in result.details

    def test_run_adversarial_validation_helper(self, validator):
        result = run_adversarial_validation(validator.df)
        assert "score" in result
        assert "recommendation" in result
        assert "tests" in result
        assert result["total_count"] == 4

    def test_perfect_factor_passes(self):
        """纯净因子应通过检验"""
        rng = np.random.RandomState(42)
        rows = []
        stocks = [f"s{i:04d}" for i in range(30)]
        dates = pd.date_range("2025-01-01", periods=200, freq="B")
        for stock in stocks:
            base = rng.randn() * 0.3
            for date in dates:
                factor = base + rng.randn() * 0.1
                ret = factor * 0.05 + rng.randn() * 0.01
                rows.append({
                    "stock_code": stock,
                    "trade_date": date,
                    "factor_value": factor,
                    "daily_ret": ret,
                })
        df = pd.DataFrame(rows)
        validator = AdversarialValidator(df, holding_period=5)
        result = validator.run_all()
        # Strong factor should pass at least 3 of 4
        assert result.passed_count >= 3


# ═══════════════════════════════════════════════════════
# Fitness Scoring Tests
# ═══════════════════════════════════════════════════════

class TestFitness:
    def test_fitness_formula(self):
        # WQ A-Rating: Sharpe ≥ 1.625, |Returns| ≥ 6.3%, Fitness ≥ 1.0
        f = compute_fitness(sharpe=2.0, returns=0.10, turnover=0.15)
        assert f > 1.0

    def test_fitness_low_turnover(self):
        # Fitness should use min_turnover floor
        f = compute_fitness(sharpe=1.0, returns=0.05, turnover=0.01)
        assert f > 0  # would be 0 if real turnover were used unchecked

    def test_fitness_zero_returns(self):
        f = compute_fitness(sharpe=1.0, returns=0.0, turnover=0.15)
        assert f == 0.0

    def test_fitness_negative_returns(self):
        f = compute_fitness(sharpe=-1.0, returns=-0.05, turnover=0.15)
        assert f < 0  # negative sharpe + absolute returns

    def test_fitness_a_rating(self):
        f = compute_fitness(sharpe=1.8, returns=0.08, turnover=0.20)
        assert f >= 1.0


class TestCloudAlignment:
    def test_strong_factor(self):
        cloud = compute_cloud_alignment(ic_mean=0.04, ic_ir=0.5, turnover=0.15)
        assert cloud["cloud_predicted_pass"] is True
        assert cloud["cloud_alignment_score"] > 60

    def test_weak_factor(self):
        cloud = compute_cloud_alignment(ic_mean=0.005, ic_ir=0.05, turnover=0.50)
        assert cloud["cloud_predicted_pass"] is False
        assert cloud["cloud_alignment_score"] < 40

    def test_wq_a_rating_possible(self):
        cloud = compute_cloud_alignment(ic_mean=0.03, ic_ir=0.4, turnover=0.20)
        assert cloud["wq_a_rating_possible"] is True

    def test_wq_a_rating_not_possible(self):
        cloud = compute_cloud_alignment(ic_mean=0.01, ic_ir=0.1, turnover=0.80)
        assert cloud["wq_a_rating_possible"] is False

    def test_data_sufficiency(self):
        cloud_short = compute_cloud_alignment(ic_mean=0.03, ic_ir=0.3, turnover=0.15, data_days=60)
        cloud_long = compute_cloud_alignment(ic_mean=0.03, ic_ir=0.3, turnover=0.15, data_days=240)
        assert cloud_long["component_scores"]["data_sufficiency"] > cloud_short["component_scores"]["data_sufficiency"]

    def test_turnover_penalty_high(self):
        cloud = compute_cloud_alignment(ic_mean=0.04, ic_ir=0.5, turnover=0.80)
        assert cloud["component_scores"]["turnover"] < 60


class TestEnhancedScore:
    def test_basic_enhancement(self):
        result = enhanced_score(
            existing_score_result={"grade": "B", "overall_score": 65},
            sharpe=1.5, returns=0.06, turnover=0.15,
            ic_mean=0.03, ic_ir=0.3,
        )
        assert "wq_fitness" in result
        assert "cloud_alignment_score" in result
        assert "cloud_predicted_pass" in result

    def test_with_adversarial(self):
        result = enhanced_score(
            existing_score_result={"grade": "A", "overall_score": 85},
            adversarial_result={"score": 75, "recommendation": "基本通过",
                                "passed_count": 3, "total_count": 4, "tests": []},
            sharpe=1.8, returns=0.08, turnover=0.15,
        )
        assert result["adversarial_score"] == 75
        assert result["adversarial_passed"] == 3

    def test_wq_grade_override(self):
        result = enhanced_score(
            existing_score_result={"grade": "B", "overall_score": 65},
            sharpe=2.0, returns=0.10, turnover=0.20,
            ic_mean=0.04, ic_ir=0.5,
        )
        assert result["wq_grade"] == "A"
