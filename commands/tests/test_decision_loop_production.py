from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from factor_lab.decision_loop.authorization import AuthorizationService
from factor_lab.decision_loop.certification import DecisionLoopCertification
from factor_lab.decision_loop.cycle import MinuteDecisionCycle
from factor_lab.decision_loop.models import Book, PlannedOrder
from factor_lab.decision_loop.qmt_sync import QMTReconciliationService
from factor_lab.decision_loop.position_ingestion import PositionIngestionService, parse_ocr_text
from factor_lab.decision_loop.storage import DecisionLoopStore
from factor_lab.decision_loop.service import DecisionLoopService
from factor_lab.decision_loop.vnext_opportunity import VNextPassListService


class FakeQMT:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def get_account(self):
        return {"status": "error", "error": "timeout"} if self.fail else {
            "status": "ok",
            "data": {"m_dTotalAsset": 1_000_000, "m_dAvailable": 200_000, "m_dMarketValue": 800_000},
        }

    def get_positions(self):
        return {"status": "error", "error": "timeout"} if self.fail else {
            "status": "ok",
            "data": [{
                "m_strInstrumentID": "588200.SH",
                "m_strInstrumentName": "设备ETF",
                "m_nVolume": 1000,
                "m_nCanUseVolume": 700,
                "m_nFrozenVolume": 300,
                "m_dOpenPrice": 1.2,
                "m_dLastPrice": 1.25,
            }],
        }


def test_qmt_sync_requires_preview_confirmation_and_keeps_quantities(tmp_path):
    store = DecisionLoopStore(tmp_path)
    sync = QMTReconciliationService(store, FakeQMT())
    preview = sync.preview()
    assert store.read_json("positions/current.json") is None
    position = preview.proposed_snapshot.positions[0]
    assert (position.quantity, position.available_quantity, position.frozen_quantity) == (1000, 700, 300)
    snapshot = sync.confirm(preview.preview_id, preview.proposed_snapshot.content_hash)
    assert snapshot.confirmed is True
    assert sync.latest()["status"] == "confirmed"


def test_qmt_consecutive_failures_revoke_daily_authorization(tmp_path, monkeypatch):
    store = DecisionLoopStore(tmp_path)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    trading_date = now.date().isoformat()
    auths = AuthorizationService(store)
    auth, nonce = auths.create_plan(
        trading_date=trading_date,
        strategy_summary="test",
        risk_budget={"swing": 0.5},
        max_order_amount=10_000,
        max_total_amount=20_000,
        orders=[PlannedOrder(order_id="o1", symbol="588200.SH", side="SELL", quantity=100, limit_price=1.2, book=Book.SWING, strategy="test", reason="test")],
        parameter_version="v1",
        now=now,
    )
    auths.activate(trading_date, nonce, auth.plan.plan_hash, now=now)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("factor_lab.decision_loop.qmt_sync.datetime", FixedDateTime)
    monkeypatch.setattr("factor_lab.decision_loop.authorization.datetime", FixedDateTime)
    sync = QMTReconciliationService(store, FakeQMT(fail=True), failure_limit=3)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="timeout"):
            sync.preview()
    assert auths.current(trading_date, now).status == "revoked"
    assert auths.current(trading_date, now).revoke_reason == "qmt_consecutive_read_failures"


def test_authorization_activation_is_single_flight(tmp_path):
    store = DecisionLoopStore(tmp_path)
    auths = AuthorizationService(store)
    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    trading_date = now.date().isoformat()
    auth, nonce = auths.create_plan(
        trading_date=trading_date,
        strategy_summary="test",
        risk_budget={"swing": 0.5},
        max_order_amount=10_000,
        max_total_amount=20_000,
        orders=[PlannedOrder(
            order_id="o1", symbol="588200.SH", side="SELL", quantity=100,
            limit_price=1.2, book=Book.SWING, strategy="test", reason="test",
        )],
        parameter_version="v1",
        now=now,
    )

    def activate_once(_):
        try:
            activated = auths.activate(trading_date, nonce, auth.plan.plan_hash, now=now)
            return "ok", activated.status
        except ValueError as exc:
            return "error", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(activate_once, range(2)))
    assert [item[0] for item in outcomes].count("ok") == 1
    assert [item[0] for item in outcomes].count("error") == 1
    assert "not pending" in next(item[1] for item in outcomes if item[0] == "error")
    assert auths.current(trading_date, now).status == "active"
    activated_audits = [
        row for row in store.read_jsonl("authorization/audit.jsonl")
        if row.get("action") == "activated"
    ]
    assert len(activated_audits) == 1


def test_store_cross_process_style_idempotency_and_corruption_recovery(tmp_path):
    store = DecisionLoopStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: store.append_unique_jsonl("events/test.jsonl", {"value": index}, f"key:{index % 20}"), range(100)))
    rows = store.read_jsonl("events/test.jsonl")
    assert len(rows) == 20
    store.write_json("state/current.json", {"value": 1})
    store.write_json("state/current.json", {"value": 2})
    store.path("state/current.json").write_text("{broken", encoding="utf-8")
    assert store.read_json("state/current.json") == {"value": 1}


def test_store_update_json_serializes_concurrent_read_modify_write(tmp_path):
    store = DecisionLoopStore(tmp_path)

    def increment(_index):
        store.update_json(
            "parameters/production.json",
            {"version": 0, "values": {}},
            lambda current: {**current, "version": int(current.get("version", 0)) + 1},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(80)))
    assert store.read_json("parameters/production.json")["version"] == 80


def test_store_does_not_steal_old_but_live_lock(tmp_path):
    store = DecisionLoopStore(tmp_path)
    lock_path = store.path("notifications/outbox-worker").with_suffix(".lock")
    with store.exclusive("notifications/outbox-worker"):
        old = time.time() - 3600
        os.utime(lock_path, (old, old))
        with pytest.raises(TimeoutError, match="state lock timeout"):
            with store.exclusive("notifications/outbox-worker", timeout=0.05):
                pass


def test_store_quarantines_bad_jsonl_row_without_losing_valid_rows(tmp_path):
    store = DecisionLoopStore(tmp_path)
    ledger = store.path("notifications/outbox.jsonl")
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        '{"idempotency_key":"first","value":1}\n'
        '{broken-json\n'
        '{"idempotency_key":"second","value":2}\n',
        encoding="utf-8",
    )

    assert [row["value"] for row in store.read_jsonl("notifications/outbox.jsonl")] == [1, 2]
    _, created = store.append_unique_jsonl(
        "notifications/outbox.jsonl", {"value": 3}, "third"
    )
    quarantine = store.read_jsonl("quarantine/jsonl_corruption.jsonl")

    assert created is True
    assert [row["value"] for row in store.read_jsonl("notifications/outbox.jsonl")] == [1, 2, 3]
    assert len(quarantine) == 1
    assert quarantine[0]["source_file"] == "notifications/outbox.jsonl"
    assert quarantine[0]["raw_line"] == "{broken-json"


def test_semiconductor_etf_gap_fade_replay_covers_all_three_exits(tmp_path):
    result = DecisionLoopCertification(DecisionLoopStore(tmp_path)).replay_semiconductor_etf_gap_fade()
    assert result["passed"] is True
    assert all(result["assertions"].values())


def test_vnext_passlist_is_automatic_and_never_pads_primary(tmp_path):
    store = DecisionLoopStore(tmp_path)
    result = VNextPassListService(store).generate()
    assert len(result.primary) <= 3
    assert len(result.backup) <= 5
    if not result.primary:
        assert result.no_opportunity_reason
    watchlist = store.read_json("watchlist/current.json")
    assert watchlist["decision_id"] == result.decision_id


def test_ocr_aliases_and_low_confidence_preview_require_correction(tmp_path):
    positions = parse_ocr_text(
        "证券代码 证券名称 股票余额 可卖数量 成本价 最新价 证券类型 账簿\n"
        "588200.SH 设备ETF 1000 700 1.20 1.25 ETF 催化\n"
        "688012.SH 中微公司 200 100 160.50 165.00 股票 核心"
    )
    assert [(row.symbol, row.quantity, row.available_quantity) for row in positions] == [
        ("588200.SH", 1000, 700),
        ("688012.SH", 200, 100),
    ]
    service = PositionIngestionService(DecisionLoopStore(tmp_path))
    preview = service.preview_positions(positions, "ocr").model_copy(
        update={
            "requires_correction": True,
            "quality_issues": [{"text": "5882OO", "confidence": 41}],
        }
    )
    service.store.write_json(
        f"positions/previews/{preview.preview_id}.json",
        preview.model_dump(mode="json"),
    )
    with pytest.raises(ValueError, match="manual correction"):
        service.confirm(preview.preview_id, preview.proposed_snapshot.content_hash)


def test_minute_cycle_lock_skips_overlapping_invocation(tmp_path):
    service = DecisionLoopService(DecisionLoopStore(tmp_path))
    cycle = MinuteDecisionCycle(service, FakeQMT())
    with service.store.exclusive("cycle/minute"):
        result = cycle.run()
    assert result.status == "skipped"
    assert result.blockers == ["minute_cycle_overlap"]
