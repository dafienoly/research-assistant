from __future__ import annotations

from factor_lab.vnext.event_truth import (
    BarData,
    ContractData,
    MechanicalRiskManager,
    OrderData,
    PositionData,
    PositionLot,
)


def _bar(*, day: str = "2026-07-10", opening: float = 10.0, previous: float = 10.0, volume: float = 100_000) -> BarData:
    return BarData(
        symbol="000001.SZ",
        trading_date=day,
        open=opening,
        high=max(opening, previous) * 1.01,
        low=min(opening, previous) * 0.99,
        close=opening,
        pre_close=previous,
        volume_shares=volume,
        amount_yuan=volume * opening,
    )


def _order(side: str, quantity: int, day: str = "2026-07-10") -> OrderData:
    return OrderData(
        order_id=f"order-{side}-{quantity}",
        symbol="000001.SZ",
        side=side,
        requested_quantity=quantity,
        submitted_date=day,
        reference_price=10.0,
    )


def test_t_plus_one_blocks_same_day_sale_and_allows_next_day():
    manager = MechanicalRiskManager(max_volume_participation=0.1)
    contract = ContractData("000001.SZ", "SZSE", "MAINBOARD")
    position = PositionData("000001.SZ", quantity=1000, lots=[PositionLot(1000, "2026-07-10")])
    same_day = manager.evaluate(
        _order("SELL", 1000),
        contract=contract,
        bar=_bar(),
        position=position,
    )
    next_day = manager.evaluate(
        _order("SELL", 1000, "2026-07-11"),
        contract=contract,
        bar=_bar(day="2026-07-11"),
        position=position,
    )
    assert same_day.allowed_quantity == 0
    assert same_day.reason == "t_plus_one_unavailable"
    assert next_day.allowed_quantity == 1000


def test_dynamic_limits_cover_main_star_chinext_bse_and_st():
    assert MechanicalRiskManager.price_limit_pct(ContractData("600000.SH", "SSE", "MAINBOARD"), "2026-07-10") == 0.10
    assert MechanicalRiskManager.price_limit_pct(ContractData("688001.SH", "SSE", "STAR"), "2026-07-10") == 0.20
    assert MechanicalRiskManager.price_limit_pct(ContractData("300001.SZ", "SZSE", "CHINEXT"), "2020-08-23") == 0.10
    assert MechanicalRiskManager.price_limit_pct(ContractData("300001.SZ", "SZSE", "CHINEXT"), "2020-08-24") == 0.20
    assert MechanicalRiskManager.price_limit_pct(ContractData("830001.BJ", "BSE", "BSE"), "2026-07-10") == 0.30
    assert MechanicalRiskManager.price_limit_pct(
        ContractData("600000.SH", "SSE", "MAINBOARD", is_st=True), "2026-07-10"
    ) == 0.05


def test_limit_up_permission_and_partial_capacity_are_mechanical_blocks():
    manager = MechanicalRiskManager(max_volume_participation=0.05)
    position = PositionData("000001.SZ")
    main = ContractData("000001.SZ", "SZSE", "MAINBOARD")
    limit = manager.evaluate(
        _order("BUY", 1000),
        contract=main,
        bar=_bar(opening=11.0, previous=10.0),
        position=position,
    )
    assert limit.allowed_quantity == 0
    assert limit.reason == "limit_up_buy_blocked"

    blocked_contract = ContractData("688001.SH", "SSE", "STAR", account_allowed=False)
    permission = manager.evaluate(
        _order("BUY", 1000),
        contract=blocked_contract,
        bar=_bar(opening=10.0, previous=10.0),
        position=position,
    )
    assert permission.reason == "account_permission_blocked"

    partial = manager.evaluate(
        _order("BUY", 1000),
        contract=main,
        bar=_bar(volume=10_000),
        position=position,
    )
    assert partial.allowed_quantity == 500
    assert partial.partial is True


def test_buy_orders_are_rounded_to_board_lots():
    manager = MechanicalRiskManager(max_volume_participation=1.0)
    decision = manager.evaluate(
        _order("BUY", 255),
        contract=ContractData("000001.SZ", "SZSE", "MAINBOARD", lot_size=100),
        bar=_bar(volume=100_000),
        position=PositionData("000001.SZ"),
    )
    assert decision.allowed_quantity == 200
    assert decision.partial is True
