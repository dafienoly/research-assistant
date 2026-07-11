from __future__ import annotations

import json
from dataclasses import asdict
from datetime import timedelta

import pytest
from pydantic import ValidationError

from factor_lab.vnext.contracts import (
    ApprovedOrderEnvelope,
    OrderDraft,
    QualityStatus,
    ResearchSignal,
    TargetPortfolioWeights,
    TargetWeightLine,
    TradingMode,
    Tradability,
    aware_now,
    contract_json_schemas,
)
from factor_lab.vnext.execution import (
    AuditJournal,
    ExecutionGuard,
    GovernedExecutionEngine,
    NonceRegistry,
    PaperBroker,
    QMTProbeBroker,
    SafetyContext,
    TelegramApprovalGate,
)
from factor_lab.vnext.cli import handle
from factor_lab.vnext.service import VNextService


SIGNING_SECRET = "-".join(("hermes", "test", "signing", "material"))


def draft(**updates) -> OrderDraft:
    values = {
        "portfolio_run_id": "portfolio_run_1",
        "account_snapshot_id": "account_snapshot_1",
        "position_snapshot_id": "position_snapshot_1",
        "data_snapshot_id": "data_snapshot_1",
        "symbol": "600183.SH",
        "side": "BUY",
        "quantity": 100,
        "order_type": "LIMIT",
        "limit_price": 10.5,
        "rationale": "signed contract test",
        "risk_summary": [],
        "strategy_source": "contract-test",
        "regime": "RANGE_BOUND",
        "semiconductor_state": "SEMI_DORMANT",
        "data_freshness": "OK",
        "account_permission": "OK",
        "quality_status": QualityStatus.OK,
    }
    values.update(updates)
    return OrderDraft(**values)


def envelope(order: OrderDraft | None = None, **updates) -> ApprovedOrderEnvelope:
    values = {
        "order_draft": order or draft(),
        "approved_by": "tester",
        "allowed_mode": TradingMode.PAPER,
        "risk_snapshot_id": "risk_snapshot_1",
        "secret": SIGNING_SECRET,
    }
    values.update(updates)
    return ApprovedOrderEnvelope.sign(**values)


def safety(approval_id: str, **updates) -> SafetyContext:
    values = {
        "data_status": "OK",
        "data_fresh": True,
        "account_permission": True,
        "funds_available": True,
        "positions_synced": True,
        "within_trading_session": True,
        "price_limit_clear": True,
        "suspension_clear": True,
        "st_clear": True,
        "liquidity_clear": True,
        "stock_weight_clear": True,
        "theme_exposure_clear": True,
        "portfolio_drawdown_clear": True,
        "daily_loss_clear": True,
        "kill_switch_triggered": False,
        "telegram_approved": False,
        "approval_id": approval_id,
    }
    values.update(updates)
    return SafetyContext(**values)


def test_seven_core_contracts_export_json_schema_and_reject_buy_sell_signal_fields():
    schemas = contract_json_schemas()
    assert set(schemas) == {
        "MarketDataEnvelope",
        "ResearchSignal",
        "TargetPortfolioWeights",
        "OrderDraft",
        "ApprovedOrderEnvelope",
        "ExecutionEvent",
        "ReviewRecord",
    }
    with pytest.raises(ValidationError):
        ResearchSignal(
            signal_run_id="signal_1",
            as_of="2026-07-11",
            instrument_id="600183.SH",
            confidence=0.5,
            regime_applicability=0.5,
            semi_state_applicability=0.5,
            evidence_bundle_id="evidence_1",
            quality_status=QualityStatus.OK,
            source_strategy="test",
            buy=True,
        )


def test_target_weights_enforce_tradability_substitution_delta_and_cash_sum():
    line = TargetWeightLine(
        instrument_id="512480.SH",
        current_weight=0.1,
        raw_target_weight=0.25,
        eligible_target_weight=0.25,
        risk_adjusted_target_weight=0.2,
        weight_delta=0.1,
        source_strategy="semi",
        confidence=0.8,
        risk_budget=0.2,
        tradability=Tradability.ETF_SUBSTITUTION,
        substitution_of="688012.SH",
        quality_status=QualityStatus.OK,
    )
    weights = TargetPortfolioWeights(
        portfolio_run_id="portfolio_1",
        account_id="account_1",
        as_of="2026-07-11",
        universe_snapshot_id="universe_1",
        data_snapshot_id="data_1",
        strategy_version="strategy_1",
        regime_state="RANGE_BOUND",
        semi_mainline_state="SEMI_DORMANT",
        weights=[line],
        raw_weights={"512480.SH": 0.25},
        eligibility_adjusted_weights={"512480.SH": 0.25},
        risk_adjusted_weights={"512480.SH": 0.2},
        cash_weight=0.8,
        substitutions={"512480.SH": "688012.SH"},
        evidence_bundle_id="evidence_1",
        quality_status=QualityStatus.OK,
    )
    assert len(weights.target_weights_hash) == 64
    with pytest.raises(ValidationError):
        TargetWeightLine(
            instrument_id="688012.SH",
            current_weight=0,
            raw_target_weight=0.1,
            eligible_target_weight=0.1,
            risk_adjusted_target_weight=0.1,
            weight_delta=0.1,
            source_strategy="bad",
            confidence=0.5,
            risk_budget=0.1,
            tradability=Tradability.RESTRICTED,
            quality_status=QualityStatus.BLOCKED,
        )


def test_order_hash_signature_expiry_and_nonce_are_enforced(tmp_path):
    order = draft()
    signed = envelope(order)
    assert signed.verify(SIGNING_SECRET) == (True, "approved_envelope_valid")
    tampered_signature = signed.model_copy(update={"signature": "0" * 64})
    assert tampered_signature.verify(SIGNING_SECRET)[1] == "approval_signature_mismatch"

    expired = envelope(
        draft(expires_at=aware_now() + timedelta(minutes=5)),
        approved_at=aware_now() - timedelta(minutes=1),
        ttl_seconds=1,
    )
    assert expired.verify(SIGNING_SECRET)[1] == "approval_expired"

    journal = AuditJournal(tmp_path / "execution.jsonl")
    guard = ExecutionGuard(journal=journal, nonce_registry=NonceRegistry(tmp_path / "nonces"))
    context = safety(order.approval_id)
    assert guard.authorize(signed, context, mode=TradingMode.PAPER, signing_secret=SIGNING_SECRET)["passed"] is True
    replay = guard.authorize(signed, context, mode=TradingMode.PAPER, signing_secret=SIGNING_SECRET)
    assert replay["passed"] is False
    assert replay["reason"] == "approval_nonce_reused"


def test_execution_service_rejects_raw_draft_hash_mismatch_and_kill_switch(tmp_path):
    journal = AuditJournal(tmp_path / "execution.jsonl")
    engine = GovernedExecutionEngine(TradingMode.PAPER, journal)
    order = draft()
    raw_result = engine.submit(
        PaperBroker(journal),
        order,  # type: ignore[arg-type] -- intentional safety property test
        safety(order.approval_id),
        signing_secret=SIGNING_SECRET,
    )
    assert raw_result["status"] == "BLOCKED"
    assert raw_result["reason"] == "approved_order_envelope_required"

    signed = envelope(order)
    invalid_key = "-".join(("wrong", "key"))
    wrong_secret = engine.submit(
        PaperBroker(journal),
        signed,
        safety(order.approval_id),
        signing_secret=invalid_key,
    )
    assert wrong_secret["reason"] == "approval_signature_mismatch"

    killed = engine.submit(
        PaperBroker(journal),
        signed,
        safety(order.approval_id, kill_switch_triggered=True),
        signing_secret=SIGNING_SECRET,
    )
    assert killed["reason"] == "kill_switch"
    assert killed["real_broker_called"] is False

    research_only = draft(quality_status=QualityStatus.BACKTEST_ONLY)
    research_envelope = envelope(research_only)
    blocked_quality = engine.submit(
        PaperBroker(journal),
        research_envelope,
        safety(research_only.approval_id),
        signing_secret=SIGNING_SECRET,
    )
    assert blocked_quality["reason"] == "order_quality_not_executable"


def test_telegram_gate_signs_valid_approval_and_modify_invalidates_original(tmp_path):
    gate = TelegramApprovalGate(tmp_path, signing_secret=SIGNING_SECRET)
    order = draft()
    record = gate.create(order, kill_switch=False, miniqmt_mode=TradingMode.PAPER.value)
    approved = gate.decide(record["approval_id"], "APPROVE", approver="tester", reason="paper only")
    assert approved["status"] == "APPROVED"
    assert approved["signature_status"] == "SIGNED"
    assert gate.is_approved(record["approval_id"]) is True
    assert gate.get_envelope(record["approval_id"]).order_draft_hash == order.draft_hash

    second = gate.create(draft(), kill_switch=False, miniqmt_mode=TradingMode.PAPER.value)
    modified = gate.decide(
        second["approval_id"],
        "MODIFY",
        approver="tester",
        reason="change quantity",
        modifications={"quantity": 200},
    )
    assert modified["status"] == "INVALIDATED_BY_MODIFICATION"
    assert modified["requires_reapproval"] is True
    assert gate.is_approved(second["approval_id"]) is False
    with pytest.raises(ValueError):
        gate.decide(second["approval_id"], "APPROVE", approver="tester", reason="must create new draft")


def test_audit_ledger_hash_chain_detects_tampering(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    journal.append("one", {"value": 1})
    journal.append("two", {"value": 2})
    assert journal.verify_chain()["valid"] is True

    rows = journal.path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["value"] = 999
    rows[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    journal.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = journal.verify_chain()
    assert result["valid"] is False
    assert result["reason"] in {"event_hash_mismatch", "payload_hash_mismatch"}


def test_execution_status_merges_read_only_qmt_probe_without_enabling_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_APPROVAL_SIGNING_KEY", SIGNING_SECRET)
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    service.store.write(
        "qmt-probe",
        "2026-07-11",
        {
            "status": "OK",
            "connected": True,
            "account_readable": True,
            "positions_readable": True,
            "order_channel_enabled": False,
            "real_broker_called": False,
        },
    )
    status = service.execution_status("2026-07-11")
    assert status["accepted_input_contract"] == "ApprovedOrderEnvelope"
    assert status["approval_signing_configured"] is True
    assert status["miniqmt"]["connection_status"] == "OK"
    assert status["miniqmt"]["account_permission_status"] == "OK"
    assert status["miniqmt"]["position_sync_status"] == "OK"
    assert status["miniqmt"]["order_channel_status"] == "DISABLED"
    assert status["no_live_trade"] is True
    assert status["live_enabled"] is False
    assert status["trading_mode"] == "PAPER"


def test_qmt_probe_fails_closed_when_trader_or_read_endpoints_are_unavailable():
    class DisconnectedClient:
        def health(self):
            return {
                "status": "ok",
                "data": {"connected": True, "xttrader_connected": False},
            }

        def get_account(self):
            return {"status": "error", "error": "trader unavailable"}

        def get_positions(self):
            return {"status": "error", "error": "trader unavailable"}

    result = QMTProbeBroker(DisconnectedClient()).probe()

    assert result["status"] == "PARTIAL"
    assert result["connected"] is False
    assert result["account_readable"] is False
    assert result["positions_readable"] is False
    assert result["order_channel_enabled"] is False


def test_paper_cli_accepts_signed_envelope_only_and_replay_is_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_APPROVAL_SIGNING_KEY", SIGNING_SECRET)
    monkeypatch.setenv("HERMES_VNEXT_OUTPUT_DIR", str(tmp_path / "artifacts"))
    order = draft()
    signed = envelope(order)
    payload = {
        "orders": [
            {
                "approved_envelope": signed.to_dict(),
                "safety": asdict(safety(order.approval_id)),
            }
        ]
    }
    input_path = tmp_path / "approved-orders.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert handle("trading:paper-run", ["--date", "2026-07-11", "--input", str(input_path)]) is True
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "OK"
    assert first["cycles"][0]["results"][0]["status"] == "PAPER_FILLED"
    assert first["real_broker_called"] is False

    assert handle("trading:paper-run", ["--date", "2026-07-11", "--input", str(input_path)]) is True
    replay = json.loads(capsys.readouterr().out)
    assert replay["status"] == "PARTIAL"
    assert replay["cycles"][0]["results"][0]["reason"] == "approval_nonce_reused"
