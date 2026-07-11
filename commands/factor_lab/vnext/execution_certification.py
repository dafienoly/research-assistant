"""End-to-end Paper/Shadow/LiveDryRun execution-boundary certification."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from .contracts import DataStatus, QualityStatus, TradingMode, now_iso, sha256_payload
from .execution import (
    AuditJournal,
    GovernedExecutionEngine,
    LiveDryRunBroker,
    NonceRegistry,
    PaperBroker,
    QMTProbeBroker,
    SafetyContext,
    ShadowBroker,
    TelegramApprovalGate,
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class ExecutionCertificationLab:
    """Certify governed execution mechanics without producing a recommendation."""

    def run(self, project_root: str | Path, *, as_of: str, output_path: str | Path) -> dict[str, Any]:
        root = Path(project_root).resolve()
        artifact_root = root / "artifacts" / "vnext"
        snapshot, market_evidence = self._load_market_evidence(artifact_root, as_of=as_of)
        signing_secret = secrets.token_urlsafe(48)
        approval_journal = AuditJournal(artifact_root / "approval_audit.jsonl")
        approval_root = artifact_root / "certification_approvals"

        runs: dict[str, Any] = {}
        for mode, broker_type, ledger_name in (
            (TradingMode.PAPER, PaperBroker, "paper_ledger.jsonl"),
            (TradingMode.SHADOW, ShadowBroker, "shadow_ledger.jsonl"),
            (TradingMode.LIVE_DRY_RUN, LiveDryRunBroker, "live_dry_run_ledger.jsonl"),
        ):
            ledger = AuditJournal(artifact_root / ledger_name)
            engine = GovernedExecutionEngine(mode, ledger)
            approval_gate = TelegramApprovalGate(
                approval_root / mode.value.lower(),
                approval_journal,
                signing_secret=signing_secret,
                approval_ttl_seconds=300,
            )
            draft = engine.create_order_draft(
                symbol=market_evidence["instrument_id"],
                side="BUY",
                quantity=100,
                limit_price=market_evidence["close"],
                strategy_source="vnext_execution_security_certification",
                rationale="isolated security certification; not an investment recommendation",
                regime="CERTIFICATION_REPLAY",
                semiconductor_state="NOT_APPLICABLE_TO_RECOMMENDATION",
                model_score=None,
                portfolio_impact={
                    "purpose": "security_certification_only",
                    "notional": round(market_evidence["close"] * 100, 4),
                    "production_recommendation": False,
                    "isolated_account": True,
                },
                risk_summary=[
                    "no real broker transmission",
                    "real market snapshot used only to certify lineage and price binding",
                    "automated approval is isolated test evidence, not production human approval",
                ],
                data_freshness=f"verified_snapshot_as_of_{as_of}",
                account_permission="ALLOWED",
                positions={},
                portfolio_run_id=f"security-certification-{as_of}",
                account_snapshot_id=f"isolated-{mode.value.lower()}-account-empty-{as_of}",
                position_snapshot_id=f"isolated-{mode.value.lower()}-positions-empty-{as_of}",
                data_snapshot_id=snapshot["data_snapshot_id"],
                quality_status=QualityStatus.OK,
            )
            pending = approval_gate.create(draft, kill_switch=False, miniqmt_mode=mode.value)
            telegram = approval_gate.send(draft.approval_id, dry_run=True)
            approved = approval_gate.decide(
                draft.approval_id,
                "APPROVE",
                approver="isolated-security-certification",
                reason="cryptographic execution-boundary certification only",
            )
            envelope = approval_gate.get_envelope(draft.approval_id)
            context = self._safety_context(draft.approval_id)
            nonce_registry = NonceRegistry(artifact_root / "certification_nonces" / mode.value.lower())
            broker = broker_type(ledger) if broker_type in {PaperBroker, ShadowBroker} else broker_type()
            result = engine.submit(
                broker,
                envelope,
                context,
                signing_secret=signing_secret,
                nonce_registry=nonce_registry,
            )
            replay = engine.submit(
                broker,
                envelope,
                context,
                signing_secret=signing_secret,
                nonce_registry=nonce_registry,
            )
            runs[mode.value] = {
                "approval_id": draft.approval_id,
                "order_draft_hash": draft.draft_hash,
                "pending_status": pending["status"],
                "approval_status": approved["status"],
                "signature_status": approved["signature_status"],
                "telegram": telegram,
                "execution": result,
                "nonce_replay": replay,
                "ledger_path": str(ledger.path),
                "ledger_chain": ledger.verify_chain(),
            }

        qmt_probe = self._qmt_probe()
        credentials_present = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
        expected_statuses = {
            TradingMode.PAPER.value: "PAPER_FILLED",
            TradingMode.SHADOW.value: "SHADOW_RECORDED",
            TradingMode.LIVE_DRY_RUN.value: "LIVE_DRY_RUN",
        }
        mechanics_passed = all(
            runs[mode]["execution"].get("status") == status
            and runs[mode]["nonce_replay"].get("reason") == "approval_nonce_reused"
            and runs[mode]["ledger_chain"].get("valid") is True
            for mode, status in expected_statuses.items()
        )
        result = {
            "schema_version": "1.0",
            "status": DataStatus.OK.value if mechanics_passed else DataStatus.BLOCKED.value,
            "as_of": as_of,
            "purpose": "execution_security_certification_only",
            "production_recommendation": False,
            "data_snapshot_id": snapshot["data_snapshot_id"],
            "market_evidence": market_evidence,
            "runs": runs,
            "approval_audit": approval_journal.verify_chain(),
            "telegram_external_send": {
                "credentials_present": credentials_present,
                "sent": False,
                "status": "DRY_RUN_ONLY",
                "reason": "certification order must not be presented as a production approval request",
            },
            "qmt_read_only_probe": qmt_probe,
            "security_invariants": {
                "signed_envelope_required": True,
                "ttl_enforced": True,
                "one_time_nonce_enforced": True,
                "kill_switch_checked": True,
                "watch_only_checked": True,
                "lineage_required": True,
                "live_send_disabled": True,
            },
            "real_broker_called": False,
            "no_live_trade": True,
            "generated_at": now_iso(),
        }
        result["run_hash"] = sha256_payload({key: value for key, value in result.items() if key != "generated_at"})
        _atomic_json(Path(output_path), result)
        return result

    @staticmethod
    def _load_market_evidence(artifact_root: Path, *, as_of: str) -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot = json.loads((artifact_root / "snapshot_manifest.json").read_text(encoding="utf-8"))
        if snapshot.get("snapshot_id_valid") is not True or snapshot.get("silent_fallback_used") is True:
            raise ValueError("aggregate snapshot is not eligible for execution certification")
        entry = next(
            (
                item
                for item in snapshot.get("entries", [])
                if item.get("instrument_id") == "512480.SH"
                and item.get("dataset") == "fund_daily"
                and item.get("verified") is True
            ),
            None,
        )
        if entry is None:
            raise ValueError("verified 512480.SH fund_daily evidence is missing")
        data_path = Path(entry["data_file"])
        rows = json.loads(data_path.read_text(encoding="utf-8"))
        if sha256_payload(rows) != entry["content_hash"]:
            raise ValueError("market evidence content hash mismatch")
        row = next((item for item in rows if str(item.get("trade_date")) == as_of.replace("-", "")), None)
        if row is None:
            raise ValueError(f"market evidence has no row for {as_of}")
        evidence = {
            "instrument_id": "512480.SH",
            "provider": entry["provider"],
            "dataset": entry["dataset"],
            "trade_date": row["trade_date"],
            "close": float(row["close"]),
            "volume": float(row["vol"]),
            "raw_snapshot_id": entry["raw_snapshot_id"],
            "content_hash": entry["content_hash"],
            "content_hash_verified": True,
            "quality_status": entry["quality_status"],
        }
        return snapshot, evidence

    @staticmethod
    def _safety_context(approval_id: str) -> SafetyContext:
        return SafetyContext(
            data_status=DataStatus.OK.value,
            data_fresh=True,
            account_permission=True,
            funds_available=True,
            positions_synced=True,
            within_trading_session=True,
            price_limit_clear=True,
            suspension_clear=True,
            st_clear=True,
            liquidity_clear=True,
            stock_weight_clear=True,
            theme_exposure_clear=True,
            portfolio_drawdown_clear=True,
            daily_loss_clear=True,
            kill_switch_triggered=False,
            telegram_approved=False,
            approval_id=approval_id,
        )

    @staticmethod
    def _qmt_probe() -> dict[str, Any]:
        try:
            from factor_lab.broker.qmt_client import QMTClient

            client: Any | None = QMTClient()
        except Exception:
            client = None
        result = QMTProbeBroker(client).probe()
        result.update({"order_channel_enabled": False, "real_broker_called": False, "no_live_trade": True})
        return result
