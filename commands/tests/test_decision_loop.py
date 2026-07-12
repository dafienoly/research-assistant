from __future__ import annotations

import json
from threading import Event, Thread
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from factor_lab.decision_loop.authorization import AuthorizationService
from factor_lab.decision_loop.benchmark import BenchmarkMatcher
from factor_lab.decision_loop.calendar import TradingCalendarGate
from factor_lab.decision_loop.data_gate import evaluate_data_gate
from factor_lab.decision_loop import data_health
from factor_lab.decision_loop import postmarket_review
from factor_lab.decision_loop.execution import GovernedExecutionGateway
from factor_lab.decision_loop.models import (
    AdviceMode,
    Book,
    Candidate,
    DataGateResult,
    DataItemStatus,
    ExecutionRequest,
    PlannedOrder,
    PortfolioRiskInput,
    Position,
    QuoteSnapshot,
)
from factor_lab.decision_loop.notifications import DualChannelNotifier
from factor_lab.decision_loop.opportunity import OpportunityEngine
from factor_lab.decision_loop.portfolio import (
    evaluate_portfolio_risk,
    validate_allocations,
)
from factor_lab.decision_loop.postmarket_review import PostMarketReviewService
from factor_lab.decision_loop.position_ingestion import (
    PositionIngestionService,
    parse_delimited,
    parse_ocr_text,
)
from factor_lab.decision_loop.profit_guard import ProfitGuard
from factor_lab.decision_loop.review import (
    ParameterPromotionService,
    calculate_review,
    calculate_system_metrics,
)
from factor_lab.decision_loop.storage import DecisionLoopStore


def store(tmp_path: Path) -> DecisionLoopStore:
    return DecisionLoopStore(tmp_path / "state")


def position(**updates) -> Position:
    values = {
        "symbol": "588200.SH",
        "name": "科创半导体设备ETF",
        "quantity": 1000,
        "available_quantity": 1000,
        "cost_price": 100,
        "market_price": 110,
        "instrument_type": "etf",
        "book": "catalyst",
        "theme": "semiconductor_equipment",
        "thesis": "国产替代",
        "invalidation": "资金与趋势共同转弱",
    }
    values.update(updates)
    return Position(**values)


def quote(price: float, when: datetime, **updates) -> QuoteSnapshot:
    values = {
        "symbol": "588200.SH",
        "last_price": price,
        "vwap": 108,
        "volume": 100,
        "average_volume": 100,
        "observed_at": when,
        "source": "test_quote",
        "freshness_seconds": 1,
    }
    values.update(updates)
    return QuoteSnapshot(**values)


def full_data(now: datetime) -> list[DataItemStatus]:
    return [
        DataItemStatus(name=name, available=True, fresh=True, source="test", as_of=now)
        for name in (
            "quotes",
            "positions",
            "trade_calendar",
            "news",
            "capital_flow",
            "fundamentals",
        )
    ]


def gate(
    mode: AdviceMode = AdviceMode.EXECUTABLE, confidence: float = 1.0
) -> DataGateResult:
    return DataGateResult(
        mode=mode,
        confidence_multiplier=confidence,
        evaluated_at=datetime.now().astimezone(),
    )


def candidate(
    index: int,
    score: float = 90,
    mode: AdviceMode = AdviceMode.EXECUTABLE,
    instrument_type: str = "stock",
) -> Candidate:
    return Candidate(
        candidate_id=f"c{index}",
        symbol=f"60000{index}.SH",
        name=f"候选{index}",
        instrument_type=instrument_type,
        book=Book.CATALYST,
        holding_period="1-5交易日",
        catalyst_score=score,
        industry_fundamental_score=score,
        technical_flow_score=score,
        risk_score=score,
        catalyst_evidence=[
            {"source": "exchange", "as_of": "2026-07-11", "freshness": "fresh"}
        ],
        industry_logic="设备国产替代",
        fundamental_valuation="订单增长且估值可接受",
        entry_plan="放量突破后回踩",
        entry_reference_price=10 + index,
        no_chase_zone=">+5%不追",
        position_pct=0.1,
        invalidation="跌破关键支撑",
        exit_plan="催化兑现或失效退出",
        crowding_risk="中",
        benchmark_symbol="588200.SH",
        data_gate=gate(mode, 1 if mode == AdviceMode.EXECUTABLE else 0.6),
    )


def planned_order(
    side: str = "BUY", order_id: str = "o1", amount: float = 1000
) -> PlannedOrder:
    return PlannedOrder(
        order_id=order_id,
        symbol="600000.SH",
        side=side,
        quantity=100,
        limit_price=amount / 100,
        book="catalyst",
        strategy="catalyst-breakout",
        reason="approved plan",
    )


def test_position_ingestion_requires_diff_hash_confirmation(tmp_path):
    service = PositionIngestionService(store(tmp_path))
    text = "证券代码\t证券名称\t持仓数量\t可用数量\t成本价\t现价\t品种\t账簿\t主题\n588200.SH\t半导体设备ETF\t1000\t800\t1.20\t1.25\tETF\t催化\t半导体设备"
    preview = service.preview_text(text, "clipboard")
    assert preview.additions[0].available_quantity == 800
    assert service.current() is None
    with pytest.raises(ValueError, match="hash mismatch"):
        service.confirm(preview.preview_id, "bad")
    confirmed = service.confirm(
        preview.preview_id, preview.proposed_snapshot.content_hash
    )
    assert confirmed.confirmed is True
    assert service.current().positions[0].book == Book.CATALYST


def test_position_preview_preserves_source_provenance(tmp_path):
    service = PositionIngestionService(store(tmp_path))
    preview = service.preview_rows(
        [{
            "symbol": "588710.SH",
            "name": "科半导体",
            "quantity": 100,
            "available_quantity": 100,
            "cost_price": 2.65,
            "instrument_type": "ETF",
        }],
        "manual",
        source_broker="银河证券",
        source_application="同花顺远航版",
        source_account="截图账户（未核验）",
    )

    snapshot = preview.proposed_snapshot
    assert snapshot.confirmed is False
    assert snapshot.source_broker == "银河证券"
    assert snapshot.source_application == "同花顺远航版"
    assert snapshot.source_account == "截图账户（未核验）"


def test_csv_aliases_and_available_quantity_default():
    parsed = parse_delimited("code,name,quantity,cost\n600000.SH,浦发银行,100,10")
    assert parsed[0].available_quantity == 100
    assert parsed[0].symbol == "600000.SH"


def test_ocr_whitespace_table_parser():
    parsed = parse_ocr_text(
        "证券代码  证券名称  持仓数量  可用数量  成本价\n588200.SH  设备ETF  1000  800  1.20"
    )
    assert parsed[0].symbol == "588200.SH"
    assert parsed[0].available_quantity == 800


def test_data_gate_blocks_core_and_degrades_auxiliary():
    now = datetime.now().astimezone()
    core_missing = full_data(now)
    core_missing[0] = DataItemStatus(name="quotes", available=False, fresh=False)
    assert evaluate_data_gate(core_missing).mode == AdviceMode.BLOCKED
    auxiliary_missing = full_data(now)
    auxiliary_missing[-1] = DataItemStatus(
        name="fundamentals", available=False, fresh=False
    )
    assert evaluate_data_gate(auxiliary_missing).mode == AdviceMode.WATCH_ONLY
    conflict = evaluate_data_gate(
        full_data(now), conflicts=[{"source_a": 1, "source_b": 2}]
    )
    assert conflict.mode == AdviceMode.WATCH_ONLY
    assert conflict.conflicts


def test_authoritative_calendar_gate_caches_open_and_fails_closed(tmp_path):
    calls = []

    def provider(day):
        calls.append(day)
        return [{"cal_date": day, "is_open": 1}]

    gate_service = TradingCalendarGate(store(tmp_path), provider)
    day = datetime(2026, 7, 13).date()
    first = gate_service.resolve(day, datetime(2026, 7, 13, 8).astimezone())
    second = gate_service.resolve(day, datetime(2026, 7, 13, 9).astimezone())
    assert first["available"] is True and first["is_open"] is True
    assert second == first
    assert calls == ["20260713"]

    unavailable = TradingCalendarGate(
        store(tmp_path / "failed"),
        lambda _: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert unavailable.resolve(day)["available"] is False


def test_profit_guard_2_3_points_and_ten_minute_structure_break(tmp_path):
    guard = ProfitGuard(store(tmp_path), structure_confirm_minutes=10)
    base = datetime(2026, 7, 13, 10, 0).astimezone()
    assert guard.evaluate(position(), quote(110, base), AdviceMode.EXECUTABLE) == []
    warned = guard.evaluate(
        position(), quote(108, base + timedelta(minutes=10)), AdviceMode.EXECUTABLE
    )
    assert [item.action for item in warned] == ["warn"]
    halved = guard.evaluate(
        position(),
        quote(107, base + timedelta(minutes=20), vwap=106),
        AdviceMode.EXECUTABLE,
    )
    assert [item.action for item in halved] == ["reduce_half"]
    assert halved[0].quantity == 500
    afternoon = base.replace(hour=13, minute=0)
    assert (
        guard.evaluate(position(), quote(106, afternoon), AdviceMode.EXECUTABLE) == []
    )
    exited = guard.evaluate(
        position(), quote(105, afternoon + timedelta(minutes=10)), AdviceMode.EXECUTABLE
    )
    assert [item.action for item in exited] == ["exit_remaining"]


def test_profit_guard_reentry_requires_volume_reclaim(tmp_path):
    guard = ProfitGuard(store(tmp_path), structure_confirm_minutes=0)
    base = datetime(2026, 7, 13, 10, 0).astimezone()
    guard.evaluate(position(), quote(110, base), AdviceMode.EXECUTABLE)
    guard.evaluate(
        position(), quote(107, base + timedelta(minutes=1)), AdviceMode.EXECUTABLE
    )
    guard.evaluate(position(), quote(106, base.replace(hour=13)), AdviceMode.EXECUTABLE)
    weak = guard.evaluate(
        position(),
        quote(109, base.replace(hour=13, minute=1), volume=100, average_volume=100),
        AdviceMode.EXECUTABLE,
    )
    assert not any(item.action == "reentry_eligible" for item in weak)
    strong = guard.evaluate(
        position(),
        quote(109, base.replace(hour=13, minute=2), volume=121, average_volume=100),
        AdviceMode.EXECUTABLE,
    )
    assert [item.action for item in strong] == ["reentry_eligible"]


def test_dual_channel_independent_receipts_and_shared_ack(tmp_path):
    calls = []

    def ok(payload):
        calls.append(("ok", payload["event_id"]))
        return {"ok": True}

    def fail(payload):
        calls.append(("fail", payload["event_id"]))
        raise RuntimeError("network")

    notifier = DualChannelNotifier(
        store(tmp_path), {"telegram": ok, "enterprise_wechat": fail}
    )
    event = ProfitGuard(store(tmp_path))._card(
        position(),
        quote(107, datetime.now().astimezone()),
        "L3",
        "reduce_half",
        7,
        10,
        3,
        AdviceMode.EXECUTABLE,
        "test",
        500,
    )
    result = notifier.notify(event)
    assert result["channels"]["telegram"]["delivered"] is True
    assert result["channels"]["enterprise_wechat"]["delivered"] is False
    assert {event_id for _, event_id in calls} == {event.event_id}
    ack = notifier.acknowledge(event.event_id, "ly")
    assert set(ack["closes_channels"]) == {"telegram", "enterprise_wechat"}


def test_notification_outbox_enqueue_has_no_network_and_delivery_is_idempotent(tmp_path):
    calls = []

    def sender(payload):
        calls.append(payload["event_id"])
        return {"ok": True}

    notifier = DualChannelNotifier(store(tmp_path), {"telegram": sender})
    event = ProfitGuard(store(tmp_path))._card(
        position(), quote(107, datetime.now().astimezone()), "L3", "reduce_half",
        7, 10, 3, AdviceMode.EXECUTABLE, "test", 500,
    )
    queued = notifier.enqueue(event)
    assert queued["delivery"] == "outbox_queued"
    assert calls == []
    first = notifier.deliver_pending(event_id=event.event_id)
    second = notifier.deliver_pending(event_id=event.event_id)
    assert first["channels"]["telegram"]["delivered"] is True
    assert second["channels"]["telegram"]["delivered"] is True
    assert calls == [event.event_id]


def test_notification_worker_releases_lock_while_sender_is_in_flight(tmp_path):
    started = Event()
    release = Event()
    calls = []
    worker_store = store(tmp_path)
    competing_store = store(tmp_path)

    def slow_sender(payload):
        calls.append(payload["event_id"])
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True}

    notifier = DualChannelNotifier(worker_store, {"telegram": slow_sender})
    event = ProfitGuard(worker_store)._card(
        position(), quote(107, datetime.now().astimezone()), "L3", "reduce_half",
        7, 10, 3, AdviceMode.EXECUTABLE, "test", 500,
    )
    notifier.enqueue(event)
    result_holder = {}
    thread = Thread(
        target=lambda: result_holder.update(notifier.deliver_pending(event_id=event.event_id)),
        daemon=True,
    )
    thread.start()
    assert started.wait(timeout=2)
    try:
        with competing_store.exclusive("notifications/outbox-worker", timeout=0.5):
            lock_acquired = True
    except TimeoutError:
        lock_acquired = False
    assert lock_acquired is True
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result_holder["channels"]["telegram"]["delivered"] is True
    assert calls == [event.event_id]


def test_notification_claim_prevents_duplicate_concurrent_delivery(tmp_path):
    started = Event()
    release = Event()
    calls = []

    def slow_sender(payload):
        calls.append(payload["event_id"])
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True}

    first = DualChannelNotifier(store(tmp_path), {"telegram": slow_sender})
    second = DualChannelNotifier(store(tmp_path), {"telegram": slow_sender})
    event = ProfitGuard(store(tmp_path))._card(
        position(), quote(107, datetime.now().astimezone()), "L3", "reduce_half",
        7, 10, 3, AdviceMode.EXECUTABLE, "test", 500,
    )
    first.enqueue(event)
    result_holder = {}
    thread = Thread(
        target=lambda: result_holder.update(first.deliver_pending(event_id=event.event_id)),
        daemon=True,
    )
    thread.start()
    assert started.wait(timeout=2)
    observed = second.deliver_pending(event_id=event.event_id)
    assert observed["attempted"] == 0
    assert observed["channels"]["telegram"]["status"] == "in_flight"
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert calls == [event.event_id]
    assert result_holder["channels"]["telegram"]["delivered"] is True


def test_l2_digest_keeps_failed_channel_cursor_for_retry(tmp_path):
    attempts = {"telegram": 0, "enterprise_wechat": 0}

    def telegram(_):
        attempts["telegram"] += 1
        return {"ok": True}

    def wechat(_):
        attempts["enterprise_wechat"] += 1
        return {"ok": False, "error": "down"}

    notifier = DualChannelNotifier(
        store(tmp_path), {"telegram": telegram, "enterprise_wechat": wechat}
    )
    event = ProfitGuard(store(tmp_path))._card(
        position(), quote(108, datetime.now().astimezone()), "L2", "warn",
        8, 10, 2, AdviceMode.EXECUTABLE, "test",
    )
    notifier.enqueue(event)
    first = notifier.flush_l2_digest()
    second = notifier.flush_l2_digest()
    assert first["status"] == "partial"
    assert second["count"] == 1
    assert attempts == {"telegram": 1, "enterprise_wechat": 2}


def test_l2_digest_claim_prevents_duplicate_concurrent_flush(tmp_path):
    started = Event()
    release = Event()
    attempts = []

    def slow_sender(_):
        attempts.append("telegram")
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True}

    first = DualChannelNotifier(store(tmp_path), {"telegram": slow_sender})
    second = DualChannelNotifier(store(tmp_path), {"telegram": slow_sender})
    event = ProfitGuard(store(tmp_path))._card(
        position(), quote(108, datetime.now().astimezone()), "L2", "warn",
        8, 10, 2, AdviceMode.EXECUTABLE, "test",
    )
    first.enqueue(event)
    result_holder = {}
    thread = Thread(target=lambda: result_holder.update(first.flush_l2_digest()), daemon=True)
    thread.start()
    assert started.wait(timeout=2)
    observed = second.flush_l2_digest()
    assert observed["channels"] == {}
    assert observed["count"] == 1
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert attempts == ["telegram"]
    assert result_holder["status"] == "delivered"


def test_acknowledge_rejects_unknown_event(tmp_path):
    notifier = DualChannelNotifier(store(tmp_path), {"telegram": lambda _: {"ok": True}})
    assert notifier.acknowledge("evt_missing", "ly")["status"] == "not_found"


def test_archive_understands_runtime_timestamps_and_keeps_undated_rows(tmp_path):
    archive_store = store(tmp_path)
    old = datetime.now().astimezone() - timedelta(days=120)
    recent = datetime.now().astimezone() - timedelta(days=1)
    archive_store.append_jsonl("notifications/receipts.jsonl", {"id": "old", "attempted_at": old.isoformat()})
    archive_store.append_jsonl("notifications/receipts.jsonl", {"id": "recent", "started_at": recent.isoformat()})
    archive_store.append_jsonl("notifications/receipts.jsonl", {"id": "undated"})
    archived = archive_store.archive_jsonl(
        "notifications/receipts.jsonl", datetime.now().astimezone() - timedelta(days=90)
    )
    assert archived is not None
    assert [row["id"] for row in archive_store.read_jsonl("notifications/receipts.jsonl")] == [
        "recent",
        "undated",
    ]


def test_l2_is_queued_for_digest(tmp_path):
    notifier = DualChannelNotifier(
        store(tmp_path), {"telegram": lambda _: {"ok": True}}
    )
    event = ProfitGuard(store(tmp_path))._card(
        position(),
        quote(108, datetime.now().astimezone()),
        "L2",
        "warn",
        8,
        10,
        2,
        AdviceMode.EXECUTABLE,
        "test",
    )
    assert notifier.notify(event)["delivery"] == "digest_queued"
    assert notifier.flush_l2_digest()["count"] == 1


def test_daily_authorization_activation_expiry_and_runtime_revocation(tmp_path):
    auths = AuthorizationService(store(tmp_path))
    now = datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
    date = now.date().isoformat()
    auth, nonce = auths.create_plan(
        date, "test", {"catalyst": 0.25}, 2000, 5000, [planned_order()], "v1", now
    )
    assert auth.status == "pending"
    active = auths.activate(
        date, nonce, auth.plan.plan_hash, now + timedelta(minutes=1)
    )
    assert active.status == "active"
    revoked = auths.validate_runtime(
        date,
        "v2",
        active.plan.plan_hash,
        True,
        True,
        "normal",
        now + timedelta(minutes=2),
    )
    assert revoked.status == "revoked"
    assert revoked.revoke_reason == "parameters_or_plan_changed"


def test_authorization_rejects_plan_amount_over_budget(tmp_path):
    auths = AuthorizationService(store(tmp_path))
    now = datetime.now().astimezone().replace(hour=9)
    with pytest.raises(ValueError, match="max_order"):
        auths.create_plan(
            now.date().isoformat(),
            "test",
            {},
            500,
            5000,
            [planned_order(amount=1000)],
            "v1",
            now,
        )


class FakeExecutor:
    def place_order(self, payload):
        return {"status": "ok", "broker_order_id": "b1"}


def _active_gateway(tmp_path, monkeypatch):
    state = store(tmp_path)
    auths = AuthorizationService(state)
    now = datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
    date = now.date().isoformat()
    auth, nonce = auths.create_plan(
        date, "test", {}, 2000, 5000, [planned_order()], "v1", now
    )
    auths.activate(date, nonce, auth.plan.plan_hash, now + timedelta(minutes=1))
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    return (
        GovernedExecutionGateway(auths, state, FakeExecutor()),
        date,
        now + timedelta(minutes=2),
        auth.plan.plan_hash,
    )


def test_execution_blocks_unplanned_buy_and_allows_hard_risk_sell(
    tmp_path, monkeypatch
):
    gateway, date, now, plan_hash = _active_gateway(tmp_path, monkeypatch)
    buy = ExecutionRequest(
        order=planned_order(order_id="new-buy"),
        data_mode="executable",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
    )
    assert (
        gateway.submit(buy, date, now)["reason"]
        == "unplanned_buy_requires_new_approval"
    )
    sell = ExecutionRequest(
        order=planned_order(side="SELL", order_id="risk-sell"),
        event_id="evt_l4",
        hard_risk_sell=True,
        available_quantity=80,
        data_mode="executable",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
    )
    result = gateway.submit(sell, date, now)
    assert result["status"] == "submitted"
    assert result["payload"]["quantity"] == 80


def test_execution_is_fail_closed_without_live_configuration(tmp_path, monkeypatch):
    gateway, date, now, plan_hash = _active_gateway(tmp_path, monkeypatch)
    monkeypatch.delenv("QMT_LIVE_TRADING_ENABLED")
    request = ExecutionRequest(
        order=planned_order(),
        data_mode="executable",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
    )
    assert gateway.submit(request, date, now)["reason"] == "miniqmt_live_not_configured"


def test_execution_detects_plan_tampering_and_risk_mode_keeps_only_protective_sell(
    tmp_path, monkeypatch
):
    gateway, date, now, plan_hash = _active_gateway(tmp_path, monkeypatch)
    changed = planned_order()
    changed = changed.model_copy(update={"quantity": 200})
    request = ExecutionRequest(
        order=changed,
        data_mode="executable",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
    )
    assert (
        gateway.submit(request, date, now)["reason"] == "planned_order_payload_changed"
    )

    risk_sell = ExecutionRequest(
        order=planned_order(side="SELL", order_id="l4-sell"),
        event_id="evt_l4",
        hard_risk_sell=True,
        available_quantity=100,
        data_mode="executable",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
        risk_mode="no_new_positions",
    )
    assert gateway.submit(risk_sell, date, now)["status"] == "submitted"
    blocked_buy = ExecutionRequest(
        order=planned_order(),
        data_mode="executable",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
        risk_mode="no_new_positions",
    )
    assert (
        gateway.submit(blocked_buy, date, now)["reason"]
        == "daily_authorization_inactive"
    )


def test_watch_only_blocks_buy_but_keeps_hard_risk_sell(tmp_path, monkeypatch):
    gateway, date, now, plan_hash = _active_gateway(tmp_path, monkeypatch)
    buy = ExecutionRequest(
        order=planned_order(),
        data_mode="watch_only",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
    )
    assert gateway.submit(buy, date, now)["reason"] == "daily_authorization_inactive"
    sell = ExecutionRequest(
        order=planned_order(side="SELL", order_id="watch-risk-sell"),
        event_id="evt_watch_l4",
        hard_risk_sell=True,
        available_quantity=100,
        data_mode="watch_only",
        audit_passed=True,
        parameter_version="v1",
        plan_hash=plan_hash,
    )
    assert gateway.submit(sell, date, now)["status"] == "submitted"


def test_opportunity_passlist_limits_and_allows_zero_primary():
    engine = OpportunityEngine()
    result = engine.build_pass_list([candidate(index) for index in range(7)])
    assert len(result.primary) == 3
    assert len(result.backup) == 4
    weak = engine.build_pass_list([candidate(1, score=50)])
    assert weak.primary == []
    assert "保持现金" in weak.no_opportunity_reason


def test_watch_only_candidate_cannot_be_primary():
    result = OpportunityEngine().build_pass_list(
        [candidate(1, 100, AdviceMode.WATCH_ONLY)]
    )
    assert result.primary == []
    assert result.backup[0].candidate_id == "c1"


def test_empty_passlist_explains_watch_only_gate():
    item = candidate(1, 50, AdviceMode.WATCH_ONLY)
    item = item.model_copy(update={"data_gate": DataGateResult(
        mode=AdviceMode.WATCH_ONLY,
        confidence_multiplier=0.35,
        reasons=["mandatory execution checks missing"],
        evaluated_at=datetime.now().astimezone(),
    )})
    result = OpportunityEngine().build_pass_list([item])
    assert result.primary == []
    assert "观察 1 项" in result.no_opportunity_reason
    assert "mandatory execution checks missing" in result.no_opportunity_reason


def test_three_book_and_through_theme_constraints():
    positions = [
        position(
            symbol="600001.SH",
            instrument_type="stock",
            quantity=1000,
            cost_price=10,
            market_price=10,
            book="catalyst",
        ),
        position(
            symbol="600001.SH",
            instrument_type="stock",
            quantity=1000,
            cost_price=10,
            market_price=10,
            book="swing",
        ),
        position(
            symbol="588200.SH",
            instrument_type="etf",
            quantity=5100,
            cost_price=10,
            market_price=10,
            book="swing",
        ),
    ]
    result = validate_allocations(positions, equity=100000, cash=4000)
    rules = {row["rule"] for row in result["violations"]}
    assert "single_instrument" in rules
    assert "minimum_cash" in rules
    assert "theme_through" in rules


@pytest.mark.parametrize(
    "values,expected",
    [
        (
            PortfolioRiskInput(
                equity=97,
                intraday_peak_equity=100,
                previous_close_equity=100,
                rolling_20d_peak_equity=100,
            ),
            "no_new_positions",
        ),
        (
            PortfolioRiskInput(
                equity=96,
                intraday_peak_equity=100,
                previous_close_equity=100,
                rolling_20d_peak_equity=100,
            ),
            "reduce_high_beta",
        ),
        (
            PortfolioRiskInput(
                equity=89,
                intraday_peak_equity=100,
                previous_close_equity=100,
                rolling_20d_peak_equity=100,
            ),
            "reduce_only",
        ),
    ],
)
def test_portfolio_hard_risk_modes(values, expected):
    assert evaluate_portfolio_risk(values).mode.value == expected


def test_benchmark_match_returns_null_without_evidence():
    matcher = BenchmarkMatcher({"600000.SH": {"benchmark": "BK001"}}, {})
    assert matcher.match_instrument("600000.SH", "stock").primary is None
    complete = BenchmarkMatcher(
        {"600000.SH": {"benchmark": "512480.SH", "source": "exchange"}}, {}
    )
    assert complete.match_instrument("600000.SH", "stock").primary == "512480.SH"
    mapped = BenchmarkMatcher.match_portfolio(
        {"600000.SH": 0.7, "000300.SH": 0.3},
        {"600000.SH", "000300.SH"},
        tradable_benchmarks={"512480.SH"},
        instrument_types={"600000.SH": "stock", "000300.SH": "stock"},
        matcher=complete,
    )
    assert mapped["components"] == {"512480.SH": 1.0}
    assert mapped["unmapped"]["000300.SH"]
    missing = BenchmarkMatcher.match_portfolio(
        {"512480.SH": 0.7, "000300.SH": 0.3},
        {"512480.SH", "000300.SH"},
        matcher=BenchmarkMatcher({}, {}),
    )
    assert missing["components"] is None
    assert "512480.SH" in missing["unmapped"]


def test_review_metrics_and_missing_benchmark_are_honest():
    metrics = calculate_review(
        10,
        [10, 11, 9, 10.5, 12, 11],
        11,
        None,
        10,
        100,
        5,
        expected_entry_price=9.9,
        ordered_quantity=100,
        filled_quantity=100,
    )
    assert metrics.mfe_pct == 20
    assert metrics.mae_pct == -10
    assert metrics.excess_returns["1d"] is None
    assert metrics.actual_minus_system_pct == 10
    assert metrics.slippage_bps is not None
    assert metrics.execution_feasible is True


def test_system_metrics_cover_calmar_alert_quality_capacity_and_books():
    metrics = calculate_system_metrics(
        equity_curve=[100, 110, 105, 120],
        period_days=20,
        turnover_notional=200,
        capacity_estimate=1_000_000,
        alerts=[
            {"true_positive": True, "lead_minutes": 12},
            {"true_positive": False, "lead_minutes": 0},
        ],
        book_trade_returns={"catalyst": [5, -2], "swing": [3], "core": []},
        planned_orders=4,
        filled_orders=3,
    )
    assert metrics["max_drawdown_pct"] < 0
    assert metrics["calmar"] is not None
    assert metrics["alert_precision"] == 0.5
    assert metrics["alert_false_positive_rate"] == 0.5
    assert metrics["alert_average_lead_minutes"] == 12
    assert metrics["execution_feasibility"] == 0.75
    assert metrics["by_book"]["catalyst"]["trades"] == 2


def test_parameter_promotion_requires_oos_and_human_review(tmp_path):
    service = ParameterPromotionService(store(tmp_path))
    proposed = service.propose("giveback_reduce_points", 3, 2.8, {"sample": 40})
    with pytest.raises(ValueError, match="OOS"):
        service.weekly_decide(proposed.candidate_id, True, "ly")
    passed = service.record_oos(proposed.candidate_id, True, {"sharpe_delta": 0.2})
    assert passed.status == "candidate"
    promoted = service.weekly_decide(proposed.candidate_id, True, "ly")
    assert promoted.status == "promoted"
    production = service.store.read_json("parameters/production.json")
    assert production["values"]["giveback_reduce_points"] == 2.8


def test_postmarket_review_uses_verified_dynamic_benchmark(tmp_path, monkeypatch):
    review_store = store(tmp_path)
    review_store.write_json("opportunities/current.json", {"decision_id": "decision-1"})
    review_store.write_json(
        "positions/current.json",
        {"positions": [{"symbol": "600000.SH", "instrument_type": "stock", "cost_price": 10}]},
    )
    review_store.append_jsonl(
        "execution/audit.jsonl",
        {
            "timestamp": "2026-07-11T15:01:00+08:00",
            "status": "filled",
            "payload": {"symbol": "600000.SH", "book": "swing", "quantity": 100, "limit_price": 11, "event_id": "event-1", "order_id": "order-1"},
            "broker_response": {"filled_quantity": 100, "fees": 5},
        },
    )
    matcher = BenchmarkMatcher(
        {"600000.SH": {"benchmark": "512480.SH", "source": "verified-registry"}},
        {},
    )
    monkeypatch.setattr(BenchmarkMatcher, "from_durable_registry", classmethod(lambda cls: matcher))
    records = PostMarketReviewService(review_store).generate("2026-07-11")
    assert records[0].benchmark_symbol == "512480.SH"
    assert records[0].benchmark_missing_reason is None


def test_postmarket_review_uses_canonical_paths_for_horizons_and_excess(tmp_path, monkeypatch):
    review_store = store(tmp_path)
    review_store.write_json("opportunities/current.json", {"decision_id": "decision-path"})
    review_store.write_json(
        "positions/current.json",
        {"positions": [{"symbol": "600000.SH", "instrument_type": "stock", "cost_price": 10}]},
    )
    trading_date = "2026-06-01"
    stock_path = tmp_path / "600000.SH.csv"
    benchmark_path = tmp_path / "512480.SH.csv"
    stock_path.write_text(
        "trade_date,close\n" + "\n".join(f"202606{day:02d},{10 + day / 10:.2f}" for day in range(1, 22)) + "\n",
        encoding="utf-8",
    )
    benchmark_path.write_text(
        "trade_date,close\n" + "\n".join(f"202606{day:02d},{100 + day / 20:.2f}" for day in range(1, 22)) + "\n",
        encoding="utf-8",
    )
    paths = {"600000.SH": stock_path, "512480.SH": benchmark_path}
    monkeypatch.setattr(postmarket_review, "daily_kline_path", lambda symbol: paths[str(symbol)])
    matcher = BenchmarkMatcher(
        {"600000.SH": {"benchmark": "512480.SH", "source": "verified-registry"}},
        {},
    )
    monkeypatch.setattr(BenchmarkMatcher, "from_durable_registry", classmethod(lambda cls: matcher))
    review_store.append_jsonl(
        "execution/audit.jsonl",
        {
            "timestamp": f"{trading_date}T15:01:00+08:00",
            "status": "filled",
            "payload": {"symbol": "600000.SH", "book": "swing", "quantity": 100, "limit_price": 11, "event_id": "event-path", "order_id": "order-path"},
            "broker_response": {"filled_quantity": 100, "fees": 5},
        },
    )
    records = PostMarketReviewService(review_store).generate(trading_date)
    metrics = records[0].metrics
    assert metrics is not None
    assert metrics.returns["1d"] is not None
    assert metrics.returns["5d"] is not None
    assert metrics.returns["20d"] is not None
    assert metrics.excess_returns["1d"] is not None
    assert metrics.mfe_pct > 0
    assert metrics.total_cost == 5


def test_weekly_candidate_inherits_review_lineage(tmp_path):
    review_store = store(tmp_path)
    for index in range(5):
        review_store.append_jsonl(
            "reviews/records.jsonl",
            {
                "review_id": f"review-{index}",
                "decision_id": "decision-1",
                "event_id": f"event-{index}",
                "order_id": f"order-{index}",
                "metrics": {"attribution": {"risk_alert": "false_positive"}},
            },
        )
    candidate = PostMarketReviewService(review_store).propose_weekly_candidates("2026-W28")[0]
    assert candidate["decision_id"] == "decision-1"
    assert candidate["event_id"] == "event-4"
    assert candidate["order_id"] == "order-4"


def test_auxiliary_gate_reads_durable_source_time_and_conflicts(tmp_path, monkeypatch):
    monkeypatch.setattr(data_health, "BASE", tmp_path)
    manifest_path = tmp_path / "data/audit/manifests/factor_input_projection.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({
            "generated_at": "2026-07-11T15:00:00+08:00",
            "datasets": {
                "fund-flow": {
                    "status": "PARTITIONED",
                    "observed_at": "2026-07-11T15:00:00+08:00",
                    "source": "tushare",
                    "evidence": {"input_files": 1},
                },
                "fundamentals": {
                    "status": "OK",
                    "observed_at": "2026-07-11T15:00:00+08:00",
                    "source": "tushare",
                },
                "sentiment": {
                    "status": "OK",
                    "observed_at": "2026-07-11T15:00:00+08:00",
                    "source": "regulatory",
                },
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(data_health, "PROJECTION_MANIFEST", manifest_path)
    conflict_log = tmp_path / "data/audit/source_conflicts.jsonl"
    conflict_log.parent.mkdir(parents=True, exist_ok=True)
    conflict_log.write_text(
        '{"dataset":"capital_flow","source_a":"tushare","source_b":"backup"}\n',
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-07-11T16:00:00+08:00")
    items, conflicts, manifest = data_health.load_auxiliary_gate(now)
    capital_flow = next(item for item in items if item.name == "capital_flow")
    assert capital_flow.available is True
    assert capital_flow.fresh is True
    assert capital_flow.source == "tushare"
    assert conflicts[0]["dataset"] == "capital_flow"
    assert manifest["datasets"]["capital_flow"]["conflict_count"] == 1
    published = json.loads(
        (tmp_path / "data/audit/health/decision_gate_manifest.json").read_text(encoding="utf-8")
    )
    assert published["source"] == "datahub_manifest"
    assert published["datasets"]["capital_flow"]["conflict_count"] == 1


def test_auxiliary_gate_is_fail_closed_without_projection_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(data_health, "BASE", tmp_path)
    monkeypatch.setattr(data_health, "PROJECTION_MANIFEST", tmp_path / "missing.json")
    items, conflicts, manifest = data_health.load_auxiliary_gate(
        datetime.fromisoformat("2026-07-11T16:00:00+08:00")
    )
    assert conflicts == []
    assert manifest["source"] == "datahub_manifest"
    assert {item.name for item in items} == {"news", "capital_flow", "fundamentals"}
    assert all(not item.available for item in items)


def test_jsonl_archive_is_atomic_and_preserves_current_rows(tmp_path):
    review_store = store(tmp_path)
    review_store.append_jsonl("events/events.jsonl", {"event_id": "old", "created_at": "2025-01-01T00:00:00+08:00"})
    review_store.append_jsonl("events/events.jsonl", {"event_id": "current", "created_at": "2026-07-10T00:00:00+08:00"})
    archive = review_store.archive_jsonl(
        "events/events.jsonl",
        datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
    )
    assert archive is not None
    assert [row["event_id"] for row in review_store.read_jsonl("events/events.jsonl")] == ["current"]
    assert json.loads(archive.read_text(encoding="utf-8").strip())["event_id"] == "old"


def test_jsonl_archive_retry_does_not_duplicate_already_archived_rows(tmp_path):
    review_store = store(tmp_path)
    row = {"event_id": "old", "created_at": "2025-01-01T00:00:00+08:00"}
    review_store.append_jsonl("events/events.jsonl", row)
    cutoff = datetime.fromisoformat("2026-01-01T00:00:00+08:00")
    archive = review_store.archive_jsonl("events/events.jsonl", cutoff)
    assert archive is not None

    # Simulate a crash after the archive write but before the live ledger rewrite.
    review_store.append_jsonl("events/events.jsonl", row)
    repeated = review_store.archive_jsonl("events/events.jsonl", cutoff)

    assert repeated == archive
    assert archive.read_text(encoding="utf-8").count('"event_id": "old"') == 1
