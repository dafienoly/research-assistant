from factor_lab.vnext.semiconductor import SemiconductorMainlineStateMachine


def test_semiconductor_machine_downgrades_when_evidence_missing():
    result = SemiconductorMainlineStateMachine().evaluate({}, as_of="2026-07-10")
    assert result["status"] == "MISSING"
    assert result["payload"]["recommended_action_bias"] == "watch_only"
