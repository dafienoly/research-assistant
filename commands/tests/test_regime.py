from factor_lab.vnext.regime import RegimeRouter


def test_regime_router_blocks_new_buys_on_sparse_inputs():
    result = RegimeRouter().route({"technology_strength": 0.9}, as_of="2026-07-10")
    assert result["payload"]["regime_name"] == "CASH_OR_WAIT"
    assert result["payload"]["allow_new_buy"] is False
