import numpy as np
import pandas as pd

from factor_lab.vnext.portfolio import PortfolioRiskAnalyzer


def test_portfolio_analysis_exposes_false_diversification():
    rng = np.random.default_rng(3)
    base = rng.normal(0, 0.01, 130)
    returns = pd.DataFrame({"a": base, "b": base + rng.normal(0, 0.0001, 130)})
    result = PortfolioRiskAnalyzer().analyze(returns, {"a": 0.5, "b": 0.5}, as_of="2026-07-10")
    assert result["payload"]["false_diversification_warning"] is True
    assert set(result["payload"]["risk_contribution"]) == {"a", "b"}
