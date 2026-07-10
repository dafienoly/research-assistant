import numpy as np
import pandas as pd

from factor_lab.vnext.backtest import PolicyHypothesisBacktester, RobustnessValidator


def test_backtest_marks_absent_benchmark_as_missing():
    frame = pd.DataFrame({"signal": [True, False] * 40, "asset": np.linspace(-0.01, 0.01, 80)})
    result = PolicyHypothesisBacktester().evaluate(
        frame,
        signal_columns=["signal"],
        target_columns=["asset"],
        benchmark_columns=["missing"],
        horizons=[1],
    )
    assert result["status"] == "MISSING"
    assert result["missing_evidence"] == ["missing"]


def test_fixed_dynamic_comparison_is_explicit_and_non_permanent():
    fixed = {"hypothesis_results": [{"mean_excess_return": 0.01, "events": 20}]}
    dynamic = {"hypothesis_results": [{"mean_excess_return": 0.02, "events": 20}]}
    result = PolicyHypothesisBacktester.compare_threshold_variants(fixed, dynamic)
    assert result["verdict"] == "DYNAMIC_BETTER_IN_SAMPLE"
    assert "not proof" in result["warning"]


def test_robustness_does_not_zero_fill_missing_benchmark_history():
    index = pd.date_range("2025-01-01", periods=100, freq="B")
    strategy = pd.Series(0.001, index=index)
    partial = pd.Series(0.0005, index=index[:20])
    result = RobustnessValidator().evaluate(strategy, {"partial": partial}, turnover=0.1)
    assert result["status"] == "PARTIAL"
    assert result["benchmark_coverage"]["partial"] == 0.2
    assert result["benchmark_metrics"]["partial"]["total_return"] < 0.02
