from factor_lab.vnext.contracts import ComponentResult, DataStatus, clamp, finite_number, mean_available


def test_contract_value_helpers_preserve_missing_values():
    assert clamp(1.5) == 1.0
    assert finite_number(float("nan")) is None
    assert mean_available([1, None, 3]) == 2.0
    assert ComponentResult(DataStatus.MISSING, "2026-07-10", 0.0).to_dict()["status"] == "MISSING"
