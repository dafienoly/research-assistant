"""Governed Paper/Shadow/Telegram/miniQMT execution boundary.

The live broker is intentionally non-transmitting in this release.  It can
produce and validate a live-ready order envelope, but ``no_live_trade`` is an
immutable safety invariant and every submission returns a blocked result.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from .contracts import (
    ApprovedOrderEnvelope,
    DataStatus,
    OrderDraft,
    QualityStatus,
    TradingMode,
    aware_now,
    now_iso,
    sha256_payload,
)


@dataclass(slots=True)
class SafetyContext:
    data_status: str
    data_fresh: bool
    account_permission: bool
    funds_available: bool
    positions_synced: bool
    within_trading_session: bool
    price_limit_clear: bool
    suspension_clear: bool
    st_clear: bool
    liquidity_clear: bool
    stock_weight_clear: bool
    theme_exposure_clear: bool
    portfolio_drawdown_clear: bool
    daily_loss_clear: bool
    kill_switch_triggered: bool
    telegram_approved: bool
    approval_id: str


class AuditJournal:
    """Append-only JSONL ledger with a verifiable SHA-256 hash chain."""

    ZERO_HASH = "0" * 64
    RESERVED_FIELDS = {
        "event_id",
        "event",
        "timestamp",
        "payload_hash",
        "previous_event_hash",
        "event_hash",
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def append(self, event: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        payload_dict = dict(payload)
        collision = self.RESERVED_FIELDS.intersection(payload_dict)
        if collision:
            raise ValueError(f"audit payload uses reserved fields: {sorted(collision)}")
        with self._lock:
            previous_hash = self._last_event_hash()
            record = {
                "event_id": uuid.uuid4().hex,
                "event": event,
                "timestamp": now_iso(),
                "payload_hash": sha256_payload(payload_dict),
                "previous_event_hash": previous_hash,
                **payload_dict,
            }
            record["event_hash"] = sha256_payload(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return record

    def verify_chain(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"status": DataStatus.MISSING.value, "valid": False, "events": 0, "reason": "ledger_missing"}
        previous = self.ZERO_HASH
        legacy_events = 0
        events = 0
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            events += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return {
                    "status": DataStatus.BLOCKED.value,
                    "valid": False,
                    "events": events,
                    "reason": "invalid_json",
                    "line": line_number,
                }
            if "event_hash" not in record:
                legacy_events += 1
                previous = sha256_payload(record)
                continue
            if record.get("previous_event_hash") != previous:
                return {
                    "status": DataStatus.BLOCKED.value,
                    "valid": False,
                    "events": events,
                    "reason": "previous_event_hash_mismatch",
                    "line": line_number,
                }
            supplied = str(record["event_hash"])
            expected = sha256_payload({key: value for key, value in record.items() if key != "event_hash"})
            if not secrets.compare_digest(supplied, expected):
                return {
                    "status": DataStatus.BLOCKED.value,
                    "valid": False,
                    "events": events,
                    "reason": "event_hash_mismatch",
                    "line": line_number,
                }
            payload = {key: value for key, value in record.items() if key not in self.RESERVED_FIELDS}
            if record.get("payload_hash") != sha256_payload(payload):
                return {
                    "status": DataStatus.BLOCKED.value,
                    "valid": False,
                    "events": events,
                    "reason": "payload_hash_mismatch",
                    "line": line_number,
                }
            previous = supplied
        return {
            "status": DataStatus.OK.value if not legacy_events else DataStatus.PARTIAL.value,
            "valid": True,
            "events": events,
            "legacy_events": legacy_events,
            "last_event_hash": previous,
        }

    def _last_event_hash(self) -> str:
        if not self.path.exists():
            return self.ZERO_HASH
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise RuntimeError("cannot append to a corrupt audit ledger") from None
            return str(record.get("event_hash") or sha256_payload(record))
        return self.ZERO_HASH


class NonceRegistry:
    """Persist one-time approval nonce consumption using atomic create semantics."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def consume(self, nonce: str, *, approval_id: str) -> bool:
        marker = self.directory / f"{sha256_payload(nonce)}.json"
        try:
            with marker.open("x", encoding="utf-8") as handle:
                json.dump(
                    {"approval_id": approval_id, "nonce_hash": sha256_payload(nonce), "consumed_at": now_iso()},
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                )
        except FileExistsError:
            return False
        return True


class SafetyGate:
    """Evaluate every required pre-trade safety invariant."""

    @staticmethod
    def evaluate(context: SafetyContext) -> dict[str, Any]:
        checks = {
            "data_status_ok": context.data_status == DataStatus.OK.value,
            "data_freshness": context.data_fresh,
            "account_permission": context.account_permission,
            "funds": context.funds_available,
            "positions": context.positions_synced,
            "trading_time": context.within_trading_session,
            "price_limit": context.price_limit_clear,
            "suspension": context.suspension_clear,
            "st": context.st_clear,
            "liquidity": context.liquidity_clear,
            "single_stock_weight": context.stock_weight_clear,
            "theme_exposure": context.theme_exposure_clear,
            "portfolio_drawdown": context.portfolio_drawdown_clear,
            "daily_loss": context.daily_loss_clear,
            "kill_switch": not context.kill_switch_triggered,
            "telegram_approval": context.telegram_approved,
            "approval_id_present": bool(context.approval_id),
        }
        failed = [name for name, passed in checks.items() if not passed]
        return {"passed": not failed, "checks": checks, "failed_checks": failed}


class TradingModeStateMachine:
    ALLOWED = {
        TradingMode.READ_ONLY: {TradingMode.PAPER, TradingMode.LIVE_DISABLED},
        TradingMode.PAPER: {TradingMode.READ_ONLY, TradingMode.SHADOW, TradingMode.LIVE_DISABLED},
        TradingMode.SHADOW: {TradingMode.PAPER, TradingMode.LIVE_DRY_RUN, TradingMode.LIVE_DISABLED},
        TradingMode.LIVE_DRY_RUN: {TradingMode.SHADOW, TradingMode.LIVE_APPROVAL_REQUIRED, TradingMode.LIVE_DISABLED},
        TradingMode.LIVE_APPROVAL_REQUIRED: {TradingMode.LIVE_DRY_RUN, TradingMode.LIVE_DISABLED},
        TradingMode.LIVE_ENABLED: {TradingMode.LIVE_DISABLED},
        TradingMode.LIVE_DISABLED: {TradingMode.READ_ONLY},
        TradingMode.KILL_SWITCH_TRIGGERED: {TradingMode.LIVE_DISABLED},
    }

    def __init__(self, mode: TradingMode | str = TradingMode.READ_ONLY) -> None:
        self.mode = TradingMode(mode)

    def transition(self, target: TradingMode | str, *, prerequisites: Mapping[str, bool] | None = None) -> TradingMode:
        target_mode = TradingMode(target)
        if target_mode == TradingMode.KILL_SWITCH_TRIGGERED:
            self.mode = target_mode
            return self.mode
        if target_mode == TradingMode.LIVE_ENABLED:
            raise PermissionError("LIVE_ENABLED is not reachable in the VNext no-live-trade release")
        allowed = self.ALLOWED.get(self.mode, set())
        if target_mode not in allowed:
            raise ValueError(f"invalid trading-mode transition: {self.mode.value} -> {target_mode.value}")
        if target_mode in {TradingMode.SHADOW, TradingMode.LIVE_DRY_RUN, TradingMode.LIVE_APPROVAL_REQUIRED}:
            required = {
                TradingMode.SHADOW: ("paper_stable",),
                TradingMode.LIVE_DRY_RUN: ("paper_stable", "shadow_reconciled"),
                TradingMode.LIVE_APPROVAL_REQUIRED: ("paper_stable", "shadow_reconciled", "telegram_configured"),
            }[target_mode]
            state = prerequisites or {}
            missing = [name for name in required if not state.get(name, False)]
            if missing:
                raise PermissionError(f"transition prerequisites not satisfied: {missing}")
        self.mode = target_mode
        return self.mode


class Broker(Protocol):
    name: str

    def submit(self, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        """Submit through a concrete governed broker implementation."""
        raise TypeError("Broker Protocol cannot submit directly")


class PaperBroker:
    name = "PaperBroker"

    def __init__(self, journal: AuditJournal) -> None:
        self.journal = journal

    def submit(self, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        if order.watch_only:
            result = {"status": "BLOCKED", "reason": "watch_only", "broker": self.name}
        else:
            result = {
                "status": "PAPER_FILLED",
                "broker": self.name,
                "approval_id": order.approval_id,
                "symbol": order.symbol,
                "quantity": order.quantity,
                "price": order.limit_price,
                "real_broker_called": False,
                "timestamp": now_iso(),
            }
        self.journal.append("paper_submit", {"order": order.to_dict(), "result": result})
        return result


class ShadowBroker:
    name = "ShadowBroker"

    def __init__(self, journal: AuditJournal) -> None:
        self.journal = journal

    def submit(self, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        result = {
            "status": "SHADOW_RECORDED" if not order.watch_only else "BLOCKED",
            "reason": None if not order.watch_only else "watch_only",
            "broker": self.name,
            "approval_id": order.approval_id,
            "real_broker_called": False,
            "timestamp": now_iso(),
        }
        self.journal.append("shadow_submit", {"order": order.to_dict(), "result": result})
        return result


class LiveDryRunBroker:
    """Explicit non-transmitting adapter for live-shaped certification runs."""

    name = "LiveDryRunBroker"
    no_live_trade = True

    def submit(self, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        return {
            "status": "LIVE_DRY_RUN",
            "approval_id": order.approval_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "real_broker_called": False,
            "no_live_trade": True,
        }


class MiniQMTReadOnlyBroker:
    name = "MiniQMTReadOnlyBroker"

    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def probe(self) -> dict[str, Any]:
        if self.client is None:
            return {"status": DataStatus.MISSING.value, "connected": False, "reason": "QMT client unavailable"}
        if hasattr(self.client, "is_configured") and not self.client.is_configured():
            return {
                "status": DataStatus.MISSING.value,
                "connected": False,
                "reason": "QMT_BRIDGE_BASE_URL is not configured",
                "order_channel_enabled": False,
            }
        try:
            health = self.client.health() if hasattr(self.client, "health") else {"status": "unknown"}
            account = self.client.get_account() if hasattr(self.client, "get_account") else None
            positions = self.client.get_positions() if hasattr(self.client, "get_positions") else None
            healthy = not isinstance(health, dict) or health.get("status") not in {"error", "unavailable"}
            return {
                "status": DataStatus.OK.value if healthy else DataStatus.PARTIAL.value,
                "connected": healthy,
                "account_readable": account is not None,
                "positions_readable": positions is not None,
                "order_channel_enabled": False,
                "health": health,
            }
        except Exception as exc:
            return {
                "status": DataStatus.PARTIAL.value,
                "connected": False,
                "reason": type(exc).__name__,
                "order_channel_enabled": False,
            }

    def submit(self, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        return {"status": "BLOCKED", "reason": "read_only_broker", "real_broker_called": False}


class QMTProbeBroker(MiniQMTReadOnlyBroker):
    name = "QMTProbeBroker"


class MiniQMTLiveBroker:
    """Live-ready envelope validator; transmission is disabled by construction."""

    name = "MiniQMTLiveBroker"
    no_live_trade = True
    live_enabled = False

    def __init__(self, client: Any | None = None, journal: AuditJournal | None = None) -> None:
        self.client = client
        self.journal = journal

    def submit(self, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        # A valid signed envelope is the approval evidence.  Never trust a raw
        # input boolean to manufacture approval, and do not require callers to
        # duplicate the cryptographic result in SafetyContext.
        gate = SafetyGate.evaluate(context)
        result = {
            "status": "BLOCKED",
            "reason": "no_live_trade_safety_invariant",
            "gate": gate,
            "no_live_trade": True,
            "live_enabled": False,
            "real_broker_called": False,
            "approval_id": order.approval_id,
        }
        if self.journal:
            self.journal.append("live_blocked", {"order": order.to_dict(), "result": result})
        return result


class TelegramApprovalGate:
    VALID_ACTIONS = {"APPROVE", "REJECT", "MODIFY", "DELAY"}

    def __init__(
        self,
        directory: str | Path,
        journal: AuditJournal | None = None,
        *,
        signing_secret: str | None = None,
        approval_ttl_seconds: int = 300,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = journal or AuditJournal(self.directory / "approval_audit.jsonl")
        self.signing_secret = signing_secret or os.environ.get("HERMES_APPROVAL_SIGNING_KEY", "")
        if approval_ttl_seconds < 1:
            raise ValueError("approval_ttl_seconds must be positive")
        self.approval_ttl_seconds = approval_ttl_seconds

    def create(self, order: OrderDraft, *, kill_switch: bool, miniqmt_mode: str) -> dict[str, Any]:
        record = {
            "approval_id": order.approval_id,
            "status": "PENDING",
            "order_draft": order.to_dict(),
            "order_draft_id": order.order_draft_id,
            "order_draft_hash": order.draft_hash,
            "expires_at": order.expires_at.isoformat(),
            "one_time_nonce": secrets.token_urlsafe(24),
            "signature_status": "PENDING",
            "execution_eligible": False,
            "trading_reason": order.rationale,
            "regime": order.regime,
            "semiconductor_mainline_state": order.semiconductor_state,
            "strategy_source": order.strategy_source,
            "model_score": order.model_score,
            "portfolio_impact": order.portfolio_impact,
            "data_freshness": order.data_freshness,
            "account_permission": order.account_permission,
            "position_change": {"symbol": order.symbol, "quantity_delta": order.quantity},
            "risk_summary": order.risk_summary,
            "kill_switch_triggered": kill_switch,
            "alternative_etf": order.alternative_etf,
            "watch_only": order.watch_only,
            "miniqmt_mode": miniqmt_mode,
            "available_actions": sorted(self.VALID_ACTIONS),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        self._write(record)
        self.journal.append(
            "approval_created",
            {
                "approval_id": order.approval_id,
                "order_draft_id": order.order_draft_id,
                "order_draft_hash": order.draft_hash,
            },
        )
        return record

    def format_message(self, record: Mapping[str, Any]) -> str:
        order = record["order_draft"]
        return "\n".join(
            [
                f"Hermes 交易审批 {record['approval_id']}",
                f"订单草案: {order['side']} {order['symbol']} x {order['quantity']} @ {order['limit_price']}",
                f"交易理由: {record['trading_reason']}",
                f"Regime: {record['regime']}",
                f"半导体主线: {record['semiconductor_mainline_state']}",
                f"策略来源: {record['strategy_source']}",
                f"模型分数: {record['model_score']}",
                f"组合影响: {json.dumps(record['portfolio_impact'], ensure_ascii=False)}",
                f"数据新鲜度: {record['data_freshness']}",
                f"账户权限: {record['account_permission']}",
                f"仓位变化: {json.dumps(record['position_change'], ensure_ascii=False)}",
                f"风险摘要: {'; '.join(record['risk_summary']) or '无'}",
                f"Kill Switch: {record['kill_switch_triggered']}",
                f"ETF 替代: {record['alternative_etf']}",
                f"Watch-only: {record['watch_only']}",
                f"miniQMT: {record['miniqmt_mode']}",
                "动作: Approve / Reject / Modify / Delay",
            ]
        )

    def send(self, approval_id: str, *, dry_run: bool = True) -> dict[str, Any]:
        record = self.get(approval_id)
        message = self.format_message(record)
        if dry_run:
            result = {"status": "DRY_RUN", "approval_id": approval_id, "message": message, "sent": False}
            self.journal.append("telegram_dry_run", result)
            return result
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            result = {"status": DataStatus.MISSING.value, "sent": False, "reason": "Telegram credentials missing"}
            self.journal.append("telegram_send_blocked", {"approval_id": approval_id, **result})
            return result
        import urllib.parse
        import urllib.request

        body = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                sent = response.status == 200
            result = {"status": "SENT" if sent else "FAILED", "sent": sent, "approval_id": approval_id}
        except Exception as exc:
            result = {"status": "FAILED", "sent": False, "approval_id": approval_id, "reason": type(exc).__name__}
        self.journal.append("telegram_send", result)
        return result

    def decide(
        self,
        approval_id: str,
        action: str,
        *,
        approver: str,
        reason: str,
        modifications: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = action.upper()
        if normalized not in self.VALID_ACTIONS:
            raise ValueError(f"invalid approval action: {action}")
        record = self.get(approval_id)
        if record["status"] not in {"PENDING", "DELAYED"}:
            raise ValueError(f"approval is already final: {record['status']}")
        if normalized == "APPROVE" and (record.get("kill_switch_triggered") or record.get("watch_only")):
            raise PermissionError("cannot approve a kill-switch or watch-only order")
        order = OrderDraft.model_validate(record["order_draft"])
        if order.draft_hash != record.get("order_draft_hash"):
            raise PermissionError("cannot approve an order whose hash changed")
        if aware_now() >= order.expires_at:
            raise PermissionError("cannot approve an expired order draft")
        record["status"] = {
            "APPROVE": "APPROVED" if self.signing_secret else "APPROVED_UNSIGNABLE",
            "REJECT": "REJECTED",
            "MODIFY": "INVALIDATED_BY_MODIFICATION",
            "DELAY": "DELAYED",
        }[normalized]
        record["approver"] = approver
        record["approval_reason"] = reason
        record["approval_time"] = now_iso()
        record["updated_at"] = now_iso()
        if normalized == "MODIFY":
            record["modifications"] = dict(modifications or {})
            record["requires_reapproval"] = True
            record["invalidated_order_draft_hash"] = record["order_draft_hash"]
            record["execution_eligible"] = False
            record["signature_status"] = "INVALIDATED"
        elif normalized == "APPROVE" and self.signing_secret:
            envelope = ApprovedOrderEnvelope.sign(
                order_draft=order,
                approved_by=approver,
                allowed_mode=record.get("miniqmt_mode", TradingMode.PAPER.value),
                risk_snapshot_id=str(record.get("risk_snapshot_id") or f"risk_{approval_id}"),
                secret=self.signing_secret,
                ttl_seconds=self.approval_ttl_seconds,
                one_time_nonce=str(record["one_time_nonce"]),
                kill_switch_snapshot=bool(record.get("kill_switch_triggered")),
            )
            record["approved_envelope"] = envelope.to_dict()
            record["signature_status"] = "SIGNED"
            record["execution_eligible"] = True
        elif normalized == "APPROVE":
            record["signature_status"] = "MISSING"
            record["missing_evidence"] = ["HERMES_APPROVAL_SIGNING_KEY"]
            record["execution_eligible"] = False
        elif normalized == "DELAY":
            record["requires_revalidation"] = True
            record["execution_eligible"] = False
        self._write(record)
        self.journal.append(
            "approval_decision",
            {
                "approval_id": approval_id,
                "action": normalized,
                "approver": approver,
                "order_draft_hash": record["order_draft_hash"],
                "execution_eligible": record.get("execution_eligible", False),
            },
        )
        return record

    def is_approved(self, approval_id: str) -> bool:
        try:
            record = self.get(approval_id)
        except FileNotFoundError:
            return False
        if record.get("status") != "APPROVED" or record.get("requires_reapproval", False):
            return False
        if not self.signing_secret or not record.get("approved_envelope"):
            return False
        try:
            envelope = ApprovedOrderEnvelope.model_validate(record["approved_envelope"])
        except ValueError:
            return False
        valid, _ = envelope.verify(self.signing_secret)
        return valid and bool(record.get("execution_eligible"))

    def get_envelope(self, approval_id: str) -> ApprovedOrderEnvelope:
        record = self.get(approval_id)
        if not self.is_approved(approval_id):
            raise PermissionError("approval is not a valid signed executable envelope")
        return ApprovedOrderEnvelope.model_validate(record["approved_envelope"])

    def list(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted(self.directory.glob("approval_*.json"), reverse=True):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def get(self, approval_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
            raise ValueError("invalid approval id")
        path = self.directory / f"approval_{approval_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"approval not found: {approval_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: Mapping[str, Any]) -> None:
        approval_id = str(record["approval_id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
            raise ValueError("invalid approval id")
        path = self.directory / f"approval_{approval_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(dict(record), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


class GovernedExecutionEngine:
    """Create drafts and accept only signed ApprovedOrderEnvelope submissions."""

    def __init__(self, mode: TradingMode | str, journal: AuditJournal) -> None:
        self.mode = TradingMode(mode)
        self.journal = journal

    def create_order_draft(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: float | None,
        strategy_source: str,
        rationale: str,
        regime: str,
        semiconductor_state: str,
        model_score: float | None,
        portfolio_impact: Mapping[str, Any],
        risk_summary: list[str],
        data_freshness: str,
        account_permission: str,
        positions: Mapping[str, Any] | None,
        alternative_etf: str | None = None,
        watch_only: bool = False,
        portfolio_run_id: str = "legacy_unbound",
        account_snapshot_id: str = "legacy_unbound",
        position_snapshot_id: str = "legacy_unbound",
        data_snapshot_id: str = "legacy_unbound",
        quality_status: QualityStatus | str = QualityStatus.BACKTEST_ONLY,
    ) -> OrderDraft:
        normalized_side = side.upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if normalized_side == "SELL" and positions is None:
            raise PermissionError("sell draft requires a real positions input")
        if normalized_side == "SELL" and float((positions or {}).get(symbol, 0)) < quantity:
            raise PermissionError("sell quantity exceeds the real position")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        draft = OrderDraft(
            approval_id=f"appr_{uuid.uuid4().hex[:16]}",
            symbol=symbol,
            side=normalized_side,
            quantity=int(quantity),
            limit_price=float(limit_price) if limit_price is not None else None,
            strategy_source=strategy_source,
            rationale=rationale,
            regime=regime,
            semiconductor_state=semiconductor_state,
            model_score=model_score,
            portfolio_impact=dict(portfolio_impact),
            risk_summary=list(risk_summary),
            data_freshness=data_freshness,
            account_permission=account_permission,
            alternative_etf=alternative_etf,
            watch_only=watch_only,
            portfolio_run_id=portfolio_run_id,
            account_snapshot_id=account_snapshot_id,
            position_snapshot_id=position_snapshot_id,
            data_snapshot_id=data_snapshot_id,
            quality_status=quality_status,
        )
        self.journal.append("order_draft_created", {"mode": self.mode.value, "order": draft.to_dict()})
        return draft

    def submit(
        self,
        broker: Broker,
        envelope: ApprovedOrderEnvelope,
        context: SafetyContext,
        *,
        signing_secret: str,
        nonce_registry: NonceRegistry | None = None,
    ) -> dict[str, Any]:
        guard = ExecutionGuard(
            journal=self.journal,
            nonce_registry=nonce_registry or NonceRegistry(self.journal.path.parent / "consumed_nonces"),
        )
        authorization = guard.authorize(
            envelope,
            context,
            mode=self.mode,
            signing_secret=signing_secret,
        )
        if not authorization["passed"]:
            result = {
                "status": "BLOCKED",
                "reason": authorization["reason"],
                "guard": authorization,
                "real_broker_called": False,
            }
        elif self.mode == TradingMode.PAPER and isinstance(broker, PaperBroker):
            result = broker.submit(envelope.order_draft, context)
        elif self.mode == TradingMode.SHADOW and isinstance(broker, ShadowBroker):
            result = broker.submit(envelope.order_draft, context)
        elif self.mode == TradingMode.LIVE_DRY_RUN:
            result = {
                "status": "LIVE_DRY_RUN",
                "approval_id": envelope.approval_id,
                "approved_order_envelope": envelope.to_dict(),
                "execution_guard": authorization,
                "real_broker_called": False,
            }
        else:
            result = {
                "status": "BLOCKED",
                "reason": f"broker {getattr(broker, 'name', type(broker).__name__)} not allowed in {self.mode.value}",
                "real_broker_called": False,
            }
        self.journal.append(
            "execution_route",
            {"mode": self.mode.value, "approval_id": getattr(envelope, "approval_id", ""), "result": result},
        )
        return result


class ExecutionGuard:
    """Single authorization boundary between signed approvals and broker adapters."""

    def __init__(self, *, journal: AuditJournal, nonce_registry: NonceRegistry) -> None:
        self.journal = journal
        self.nonce_registry = nonce_registry

    def authorize(
        self,
        envelope: ApprovedOrderEnvelope,
        context: SafetyContext,
        *,
        mode: TradingMode | str,
        signing_secret: str,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(envelope, ApprovedOrderEnvelope):
            return self._blocked("approved_order_envelope_required", approval_id="")
        current_mode = TradingMode(mode)
        if current_mode in {TradingMode.LIVE_ENABLED, TradingMode.LIVE_APPROVAL_REQUIRED}:
            return self._blocked("live_send_disabled", approval_id=envelope.approval_id)
        if current_mode not in {TradingMode.PAPER, TradingMode.SHADOW, TradingMode.LIVE_DRY_RUN}:
            return self._blocked("mode_not_executable", approval_id=envelope.approval_id)
        valid, reason = envelope.verify(signing_secret, at=at)
        if not valid:
            return self._blocked(reason, approval_id=envelope.approval_id)
        if envelope.allowed_mode != current_mode:
            return self._blocked("approval_mode_mismatch", approval_id=envelope.approval_id)
        if context.approval_id != envelope.approval_id:
            return self._blocked("approval_id_mismatch", approval_id=envelope.approval_id)
        if context.kill_switch_triggered:
            return self._blocked("kill_switch", approval_id=envelope.approval_id)
        order = envelope.order_draft
        if order.watch_only:
            return self._blocked("watch_only", approval_id=envelope.approval_id)
        if order.quality_status != QualityStatus.OK:
            return self._blocked("order_quality_not_executable", approval_id=envelope.approval_id)
        required_lineage = {
            "portfolio_run_id": order.portfolio_run_id,
            "account_snapshot_id": order.account_snapshot_id,
            "position_snapshot_id": order.position_snapshot_id,
            "data_snapshot_id": order.data_snapshot_id,
        }
        missing_lineage = [name for name, value in required_lineage.items() if not value or value == "legacy_unbound"]
        if missing_lineage:
            return self._blocked(
                "order_lineage_incomplete",
                approval_id=envelope.approval_id,
                failed_checks=missing_lineage,
            )
        if order.account_permission.upper() not in {"OK", "ALLOWED", "TRADABLE"}:
            return self._blocked("account_permission", approval_id=envelope.approval_id)
        # A valid signed envelope is the approval evidence. Never trust a raw
        # input boolean to manufacture approval, and do not require callers to
        # duplicate the cryptographic result in SafetyContext.
        gate = SafetyGate.evaluate(replace(context, telegram_approved=True))
        if not gate["passed"]:
            return self._blocked(
                "safety_gate_failed",
                approval_id=envelope.approval_id,
                failed_checks=gate["failed_checks"],
            )
        if not self.nonce_registry.consume(envelope.one_time_nonce, approval_id=envelope.approval_id):
            return self._blocked("approval_nonce_reused", approval_id=envelope.approval_id)
        result = {
            "passed": True,
            "reason": "approved_order_envelope_authorized",
            "approval_id": envelope.approval_id,
            "order_draft_hash": envelope.order_draft_hash,
            "mode": current_mode.value,
            "nonce_consumed": True,
            "no_live_trade": True,
        }
        self.journal.append("execution_guard_authorized", result)
        return result

    def _blocked(
        self,
        reason: str,
        *,
        approval_id: str,
        failed_checks: list[str] | None = None,
    ) -> dict[str, Any]:
        result = {
            "passed": False,
            "reason": reason,
            "approval_id": approval_id,
            "failed_checks": failed_checks or [],
            "nonce_consumed": False,
            "no_live_trade": True,
        }
        self.journal.append("execution_guard_blocked", result)
        return result
