import numpy as np
import pandas as pd

from factor_lab.vnext.market import compute_breadth_divergence, compute_index_box, compute_style_rotation_matrix


def test_market_metrics_are_bounded_and_fail_visible():
    box = compute_index_box(np.linspace(3900, 4100, 140), current=3950, as_of="2026-07-10", source="fixture")
    score, _, missing = compute_breadth_divergence(
        advancing=None,
        declining=None,
        index_reversal_strength=None,
        semiconductor_relative_strength=None,
        large_cap_tech_support=None,
    )
    assert 0 <= box["payload"]["dynamic_box"]["position"] <= 1
    assert score is None
    assert "market_breadth" in missing


def test_style_rotation_serializes_undefined_cash_correlation_as_null():
    returns = pd.DataFrame({"technology": np.linspace(-0.01, 0.01, 30), "cash": np.zeros(30)})
    result = compute_style_rotation_matrix(returns, as_of="2026-07-10", source="fixture")
    assert result["payload"]["correlation"]["technology"]["cash"] is None
    assert result["payload"]["relative_strength"]["cash"] == 0.0
