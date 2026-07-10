"""Governed Paper/Shadow/Telegram/miniQMT execution boundary.

The live broker is intentionally non-transmitting in this release.  It can
produce and validate a live-ready order envelope, but ``no_live_trade`` is an
immutable safety invariant and every submission returns a blocked result.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .contracts import DataStatus, TradingMode, now_iso


@dataclass(slots=True)
class OrderDraft:
    approval_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float | None
    strategy_source: str
    rationale: str
    regime: str
    semiconductor_state: str
    model_score: float | None
    portfolio_impact: dict[str, Any]
    risk_summary: list[str]
    data_freshness: str
    account_permission: str
    alternative_etf: str | None = None
    watch_only: bool = False
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = {"event_id": uuid.uuid4().hex, "event": event, "timestamp": now_iso(), **dict(payload)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record


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
        raise NotImplementedError("broker implementations must enforce the VNext safety gate")


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

    def __init__(self, directory: str | Path, journal: AuditJournal | None = None) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = journal or AuditJournal(self.directory / "approval_audit.jsonl")

    def create(self, order: OrderDraft, *, kill_switch: bool, miniqmt_mode: str) -> dict[str, Any]:
        record = {
            "approval_id": order.approval_id,
            "status": "PENDING",
            "order_draft": order.to_dict(),
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
        self.journal.append("approval_created", {"approval_id": order.approval_id})
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
        if record["status"] not in {"PENDING", "DELAYED", "MODIFIED"}:
            raise ValueError(f"approval is already final: {record['status']}")
        if normalized == "APPROVE" and (record.get("kill_switch_triggered") or record.get("watch_only")):
            raise PermissionError("cannot approve a kill-switch or watch-only order")
        record["status"] = {
            "APPROVE": "APPROVED",
            "REJECT": "REJECTED",
            "MODIFY": "MODIFIED",
            "DELAY": "DELAYED",
        }[normalized]
        record["approver"] = approver
        record["approval_reason"] = reason
        record["approval_time"] = now_iso()
        record["updated_at"] = now_iso()
        if normalized == "MODIFY":
            record["modifications"] = dict(modifications or {})
            record["requires_reapproval"] = True
        self._write(record)
        self.journal.append("approval_decision", {"approval_id": approval_id, "action": normalized, "approver": approver})
        return record

    def is_approved(self, approval_id: str) -> bool:
        try:
            record = self.get(approval_id)
        except FileNotFoundError:
            return False
        return record.get("status") == "APPROVED" and not record.get("requires_reapproval", False)

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
    """Create order drafts and route only to permitted non-live brokers."""

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
        )
        self.journal.append("order_draft_created", {"mode": self.mode.value, "order": draft.to_dict()})
        return draft

    def submit(self, broker: Broker, order: OrderDraft, context: SafetyContext) -> dict[str, Any]:
        if context.kill_switch_triggered:
            result = {"status": "BLOCKED", "reason": "kill_switch", "real_broker_called": False}
        elif context.data_status != DataStatus.OK.value or not context.data_fresh:
            result = {"status": "BLOCKED", "reason": "data_quality_or_freshness", "real_broker_called": False}
        elif self.mode == TradingMode.PAPER and isinstance(broker, PaperBroker):
            result = broker.submit(order, context)
        elif self.mode == TradingMode.SHADOW and isinstance(broker, ShadowBroker):
            result = broker.submit(order, context)
        elif self.mode == TradingMode.LIVE_DRY_RUN:
            result = {
                "status": "LIVE_DRY_RUN",
                "approval_id": order.approval_id,
                "order_envelope": order.to_dict(),
                "safety_gate": SafetyGate.evaluate(context),
                "real_broker_called": False,
            }
        else:
            result = {
                "status": "BLOCKED",
                "reason": f"broker {getattr(broker, 'name', type(broker).__name__)} not allowed in {self.mode.value}",
                "real_broker_called": False,
            }
        self.journal.append("execution_route", {"mode": self.mode.value, "approval_id": order.approval_id, "result": result})
        return result
