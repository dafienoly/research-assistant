from __future__ import annotations

import numpy as np
import pandas as pd

from factor_lab.vnext.optimization import PortfolioOptimizer


def _returns() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = rng.normal(0.0005, 0.01, 180)
    return pd.DataFrame(
        {
            "technology": base + rng.normal(0, 0.004, 180),
            "semiconductor": base * 1.2 + rng.normal(0, 0.006, 180),
            "bond": rng.normal(0.0001, 0.002, 180),
            "gold": rng.normal(0.0002, 0.008, 180),
        }
    )


def test_all_optimizers_enforce_budget_upper_bounds_and_theme_limits():
    returns = _returns()
    optimizer = PortfolioOptimizer()
    for method in PortfolioOptimizer.METHODS:
        result = optimizer.optimize(
            returns,
            method=method,
            invested_budget=0.7,
            upper_bounds={column: 0.35 for column in returns},
            current_weights={column: 0.175 for column in returns},
            theme_exposures={
                "technology": {"technology_beta": 1.0},
                "semiconductor": {"technology_beta": 0.8, "semiconductor_beta": 1.0},
                "bond": {"technology_beta": 0.0, "semiconductor_beta": 0.0},
                "gold": {"technology_beta": 0.0, "semiconductor_beta": 0.0},
            },
            theme_limits={"technology_beta": 0.45, "semiconductor_beta": 0.25},
        )
        assert abs(sum(result["weights"].values()) - 0.7) < 1e-6
        assert all(weight <= 0.35 + 1e-8 for weight in result["weights"].values())
        assert result["theme_exposures"]["technology_beta"] <= 0.45 + 1e-6
        assert result["theme_exposures"]["semiconductor_beta"] <= 0.25 + 1e-6
        assert result["hard_constraints"]["violations"] == []


def test_ineligible_asset_zero_upper_bound_stays_zero():
    returns = _returns()
    result = PortfolioOptimizer().optimize(
        returns,
        method="minimum_variance",
        invested_budget=0.6,
        upper_bounds={"technology": 0.3, "semiconductor": 0.0, "bond": 0.3, "gold": 0.3},
    )
    assert result["weights"]["semiconductor"] == 0.0
