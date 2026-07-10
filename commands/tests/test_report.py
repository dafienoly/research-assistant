from factor_lab.vnext.report import VNextReportRenderer


def test_report_discloses_no_live_trade_and_missing_evidence():
    component = {"status": "MISSING", "confidence": 0, "evidence": [], "missing_evidence": ["source"], "payload": {}}
    text = VNextReportRenderer().render({"as_of": "2026-07-10", "policy_put": component, "semi_mainline": component, "regime": component, "portfolio_risk": component, "candidates": component, "data_health": component, "execution_status": {"trading_mode": "READ_ONLY", "no_live_trade": True}})
    assert "不会触发真实委托" in text
    assert "缺失证据" in text
