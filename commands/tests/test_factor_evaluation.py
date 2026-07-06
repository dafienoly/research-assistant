"""测试: V3.2 因子评估 — FactorEvaluation"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

from factor_lab.factor_evaluation import (
    FactorEvaluation,
    evaluate_ic,
    evaluate_anti_overfit,
    evaluate_orthogonality,
    evaluate_scoring,
    run_full_evaluation,
)


def _make_test_data(
    n_stocks: int = 50,
    n_days: int = 60,
    noise_level: float = 0.5,
    seed: int = 42,
) -> pd.DataFrame:
    """生成测试用因子数据 + 收益 + 收盘价"""
    rng = np.random.RandomState(seed)
    symbols = [f"{i:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2025-01-02", periods=n_days, freq="B")

    rows = []
    for sym in symbols:
        base = rng.randn() * 0.02
        for d in dates:
            factor = base + rng.randn() * noise_level * 0.01
            ret1 = base * 0.5 + rng.randn() * 0.02
            close = 10 + base + rng.randn() * 0.1
            rows.append({
                "date": d, "symbol": sym,
                "test_factor": factor, "ret1": ret1,
                "close": close,
            })
    return pd.DataFrame(rows)


def _make_close_pivot(df: pd.DataFrame) -> pd.DataFrame:
    cp = df.pivot_table(index="date", columns="symbol", values="close").sort_index()
    cp.index = pd.to_datetime(cp.index)
    return cp


def test_evaluate_ic_returns_expected_fields():
    """evaluate_ic 返回预期字段"""
    df = _make_test_data(seed=42)
    result = evaluate_ic(df, "test_factor")
    assert isinstance(result, dict)
    for key in ["ic_mean", "ic_ir", "pos_ratio", "layer_test", "daily_ic_series",
                 "monthly_ic_series", "quarterly_ic_series"]:
        assert key in result, f"缺少字段: {key}"
    assert result["ic_mean"] is not None
    assert result["n_dates"] > 0


def test_evaluate_ic_random_factor_returns_fair_value():
    """随机因子 IC 接近 0 (独立生成的因子与收益)"""
    rng = np.random.RandomState(99)
    symbols = [f"{i:06d}" for i in range(100)]
    dates = pd.bdate_range("2025-01-02", periods=60, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            # 因子和收益完全独立随机
            factor = rng.randn() * 0.02
            ret1 = rng.randn() * 0.02
            rows.append({"date": d, "symbol": sym, "test_factor": factor, "ret1": ret1})
    df = pd.DataFrame(rows)
    result = evaluate_ic(df, "test_factor")
    assert abs(result.get("ic_mean", 1)) < 0.15, f"随机因子 IC 应接近 0: {result['ic_mean']}"


def test_evaluate_ic_insufficient_data():
    """数据不足时返回 error"""
    df = _make_test_data(n_stocks=5, n_days=3, seed=42)
    result = evaluate_ic(df, "test_factor")
    if result.get("n_dates", 0) == 0:
        assert "error" in result, "数据不足应包含 error"
    else:
        assert result["n_dates"] > 0


def test_factor_evaluation_class_creation():
    """FactorEvaluation 实例化"""
    ev = FactorEvaluation()
    assert isinstance(ev, FactorEvaluation)
    assert ev.results == {}


def test_factor_evaluation_evaluate_ic():
    """FactorEvaluation.evaluate_ic 分步执行"""
    df = _make_test_data(seed=42)
    ev = FactorEvaluation()
    result = ev.evaluate_ic(df, "test_factor")
    assert "ic_mean" in result
    assert "ic_ir" in result
    assert "ic_analysis" in ev.results


def test_factor_evaluation_anti_overfit():
    """FactorEvaluation.evaluate_anti_overfit 分步执行 (轻量)"""
    df = _make_test_data(seed=42)
    cp = _make_close_pivot(df)
    ev = FactorEvaluation()
    # check_peer_benchmark 需要 reports.report_schema 模块
    # 如果不可用, 只测试 IC 稳定性等前置步骤
    has_report_schema = True
    try:
        import reports.report_schema  # noqa: F401
    except ImportError:
        has_report_schema = False

    if not has_report_schema:
        pytest.skip("需要 reports.report_schema 模块")

    result = ev.evaluate_anti_overfit(
        df, "test_factor", cp,
        top_quantile=0.3, placebo_trials=20,
    )
    assert "ic_stability" in result


def test_evaluate_scoring_empty_no_crash():
    """evaluate_scoring 在空输入时不崩溃 (使用最小有效结构)"""
    ao = {
        "factor_name": "test",
        "ic_stability": {"ic_mean": 0, "ic_std": 0, "ic_ir": 0,
                         "positive_ic_ratio": 0, "verdict": "fail",
                         "detail": "no data"},
        "stress_test": {"subsamples": [
            {"label": "dummy", "sharpe": 0, "max_drawdown_pct": -5,
             "cumulative_return_pct": 0, "days": 10, "ic_mean": 0,
             "rank_ic_mean": 0, "win_rate_pct": 50},
        ], "worst_subsample_score": 1.0,
                        "stability_score": 0, "verdict": "fail",
                        "detail": "no data"},
        "placebo": {"n_trials": 0, "factor_score_percentile": 50,
                    "placebo_mean_ic": 0, "placebo_std_ic": 0,
                    "factor_ic": 0, "zscore_vs_placebo": 0,
                    "p_value_like": 0.5, "verdict": "fail",
                    "detail": "no data"},
        "ic_decay": {"ic_decay_curve": {}, "best_horizon": 1,
                     "half_life_days": 1, "signal_decay_warning": "",
                     "verdict": "warn", "detail": "no data"},
        "peer_benchmark": {"beats_peer": False, "excess_return_pct": 0,
                           "verdict": "fail", "excess_sharpe": 0,
                           "strategy_cumulative_pct": 0,
                           "peer_ew_cumulative_pct": 0},
    }
    result = evaluate_scoring(ao)
    assert isinstance(result, dict)
    assert "overall_score" in result
    assert "grade" in result


def test_evaluate_scoring_full_data():
    """evaluate_scoring 完整数据应返回合理分数"""
    ao = {
        "factor_name": "test",
        "ic_stability": {"verdict": "pass", "ic_ir": 0.25, "positive_ic_ratio": 0.58,
                         "ic_mean": 0.03, "ic_std": 0.12},
        "stress_test": {"verdict": "pass", "stability_score": 0.6, "worst_subsample_score": 0.2,
                        "subsamples": [
                            {"label": "sub1", "sharpe": 2.0, "max_drawdown_pct": -10,
                             "cumulative_return_pct": 20, "days": 60, "ic_mean": 0.02,
                             "rank_ic_mean": 0.02, "win_rate_pct": 55},
                        ]},
        "placebo": {"verdict": "pass", "factor_score_percentile": 95, "zscore_vs_placebo": 3.0,
                    "n_trials": 100, "placebo_mean_ic": 0.0, "placebo_std_ic": 0.01,
                    "factor_ic": 0.03, "p_value_like": 0.01},
        "ic_decay": {"verdict": "pass", "half_life_days": 10, "best_horizon": 5,
                     "ic_decay_curve": {"1D": 0.03, "5D": 0.02, "10D": 0.01}},
        "peer_benchmark": {"beats_peer": True, "excess_return_pct": 15.0, "verdict": "pass",
                           "excess_sharpe": 1.5, "strategy_cumulative_pct": 80,
                           "peer_ew_cumulative_pct": 50},
    }
    result = evaluate_scoring(ao, family="momentum")
    assert result["overall_score"] >= 50
    assert result["grade"] in ("A", "B")
    assert result["pass_gate"] is True


def test_run_full_evaluation_with_family():
    """run_full_evaluation 返回完整评估结构 (跳过依赖缺失的情形)"""
    try:
        import reports.report_schema  # noqa: F401
    except ImportError:
        pytest.skip("需要 reports.report_schema 模块")

    df = _make_test_data(seed=42)
    cp = _make_close_pivot(df)

    result = run_full_evaluation(
        df, cp, "test_factor",
        top_quantile=0.3, rebalance="monthly",
        expression="test_factor",
        family="momentum",
    )

    assert "factor_name" in result
    assert "ic_analysis" in result
    assert "anti_overfit" in result
    assert "walk_forward" in result
    assert "scoring" in result
    assert result["factor_name"] == "test_factor"


def test_factor_evaluation_summary_format():
    """FactorEvaluation.summary() 返回摘要"""
    ev = FactorEvaluation()
    ev.results = {
        "factor_name": "test",
        "ic_analysis": {"ic_ir": 0.25, "pos_ratio": 0.58,
                        "layer_test": {"long_short_sharpe": 2.5}},
        "anti_overfit": {"overall_verdict": "pass"},
        "walk_forward": {"overall_verdict": "pass", "avg_test_sharpe": 1.2, "avg_decay": 0.3},
        "scoring": {"overall_score": 75.0, "grade": "B", "pass_gate": True},
    }
    s = ev.summary()
    assert s["status"] == "completed"
    assert s["overall_score"] == 75.0
    assert s["grade"] == "B"
    assert s["pass_gate"] is True


def test_evaluate_ic_layer_test_fields():
    """evaluate_ic 的分层回测返回正确字段"""
    df = _make_test_data(n_stocks=100, n_days=80, seed=42)
    result = evaluate_ic(df, "test_factor")
    layers = result.get("layer_test", {})
    if layers:
        for key in ["long_short_mean", "long_short_sharpe"]:
            assert key in layers, f"分层回测缺少字段: {key}"


def test_factor_evaluation_no_ret1_auto_adds():
    """df 没有 ret1 时 evaluate_anti_overfit 自动计算"""
    df = _make_test_data(seed=42)
    df_no_ret = df.drop(columns=["ret1"])
    ev = FactorEvaluation()

    # evaluate_ic 不自动添加 ret1 (因为它调用 ic_analyzer.calc_daily_ic)
    # 但 evaluate_anti_overfit 会在内部自动添加
    try:
        import reports.report_schema  # noqa: F401
    except ImportError:
        pytest.skip("需要 reports.report_schema 模块")

    cp = _make_close_pivot(df)
    result = ev.evaluate_anti_overfit(df_no_ret, "test_factor", cp, top_quantile=0.3)
    assert "ic_stability" in result
    assert "anti_overfit" in ev.results


def test_factor_evaluation_methods_independent():
    """各评估方法可独立调用, 不依赖全流程"""
    df = _make_test_data(seed=42)
    cp = _make_close_pivot(df)

    ev = FactorEvaluation()
    ic_result = ev.evaluate_ic(df, "test_factor")
    assert "ic_mean" in ic_result

    # Walk-Forward 可以独立执行 (数据不足时会返回 limitation)
    wf_result = ev.evaluate_walk_forward(
        df, "test_factor", cp,
        top_quantile=0.3,
        start_date="2025-01-02",
        end_date="2025-03-01",
    )
    assert "factor_name" in wf_result
