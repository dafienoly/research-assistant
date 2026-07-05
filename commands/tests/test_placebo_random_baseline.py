"""测试: 安慰剂检验"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd

from factor_lab.validation.anti_overfit import run_placebo_test


def test_placebo_strong_factor():
    """强因子的安慰剂检验百分位应 > 80"""
    np.random.seed(42)
    df = _make_strong_factor_data()
    result = run_placebo_test(df, "test_factor", n_trials=30)
    print(f"Percentile={result['factor_score_percentile']:.0f}%, Z={result['zscore_vs_placebo']:.2f}")
    assert result["factor_score_percentile"] >= 80


def test_placebo_random_factor():
    """随机因子安慰剂检验百分位应 < 80 或 zscore 低"""
    np.random.seed(42)
    df = _make_random_factor_data()
    result = run_placebo_test(df, "test_factor", n_trials=30)
    print(f"Percentile={result['factor_score_percentile']:.0f}%, Z={result['zscore_vs_placebo']:.2f}")
    assert result["factor_score_percentile"] < 80 or result["zscore_vs_placebo"] < 1


def test_placebo_returns_expected_keys():
    """输出包含预期字段"""
    df = _make_strong_factor_data()
    result = run_placebo_test(df, "test_factor", n_trials=20)
    for key in ["n_trials", "factor_score_percentile", "placebo_mean_ic", "placebo_std_ic", "verdict"]:
        assert key in result, f"缺少 key: {key}"


def _make_strong_factor_data() -> pd.DataFrame:
    """构造强因子 (IC 显著正)"""
    np.random.seed(42)
    symbols = [f"{i:06d}" for i in range(80)]
    dates = pd.bdate_range("2025-01-02", periods=80, freq="B")
    rows = []
    for sym in symbols:
        base = np.random.randn() * 0.01
        for d in dates:
            factor = base + np.random.randn() * 0.015
            ret1 = factor * 0.3 + np.random.randn() * 0.02
            rows.append({"date": d, "symbol": sym, "test_factor": factor, "ret1": ret1})
    return pd.DataFrame(rows)


def _make_random_factor_data() -> pd.DataFrame:
    """随机因子 (IC ≈ 0)"""
    np.random.seed(42)
    symbols = [f"{i:06d}" for i in range(80)]
    dates = pd.bdate_range("2025-01-02", periods=80, freq="B")
    rows = []
    for _ in symbols:
        for d in dates:
            factor = np.random.randn() * 0.02
            ret1 = np.random.randn() * 0.02
            rows.append({"date": d, "symbol": _, "test_factor": factor, "ret1": ret1})
    return pd.DataFrame(rows)
