"""One-per-trading-day execution plan authorization with automatic revocation."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .models import DailyAuthorization, DailyExecutionPlan, PlannedOrder
from .storage import DecisionLoopStore


CST = ZoneInfo("Asia/Shanghai")


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


class AuthorizationService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()

    def create_plan(
        self,
        trading_date: str,
        strategy_summary: str,
        risk_budget: dict[str, float],
        max_order_amount: float,
        max_total_amount: float,
        orders: list[PlannedOrder],
        parameter_version: str,
        now: datetime | None = None,
    ) -> tuple[DailyAuthorization, str]:
        now = (now or datetime.now(CST)).astimezone(CST)
        plan_date = date.fromisoformat(trading_date)
        expiry = datetime.combine(plan_date, time(15, 0), tzinfo=CST)
        if expiry <= now:
            raise ValueError("daily authorization cannot be created after market close")
        plan_payload = {
            "trading_date": trading_date,
            "strategy_summary": strategy_summary,
            "risk_budget": risk_budget,
            "max_order_amount": max_order_amount,
            "max_total_amount": max_total_amount,
            "orders": [order.model_dump(mode="json") for order in orders],
            "parameter_version": parameter_version,
        }
        plan_hash = _hash(plan_payload)
        if any(order.amount > max_order_amount for order in orders):
            raise ValueError("planned order exceeds max_order_amount")
        if sum(order.amount for order in orders) > max_total_amount:
            raise ValueError("planned orders exceed max_total_amount")
        plan = DailyExecutionPlan(
            plan_id=f"plan_{trading_date.replace('-', '')}_{plan_hash[:10]}",
            plan_hash=plan_hash,
            created_at=now,
            **plan_payload,
        )
        nonce = secrets.token_urlsafe(18)
        auth = DailyAuthorization(
            authorization_id=f"auth_{uuid.uuid4().hex}",
            plan=plan,
            status="pending",
            confirmation_nonce_hash=_hash(nonce),
            expires_at=expiry,
        )
        self.store.write_json(
            f"authorization/{trading_date}.json", auth.model_dump(mode="json")
        )
        self.store.append_jsonl(
            "authorization/audit.jsonl",
            {"action": "created", **auth.model_dump(mode="json")},
        )
        return auth, nonce

    def activate(
        self,
        trading_date: str,
        nonce: str,
        displayed_plan_hash: str,
        now: datetime | None = None,
    ) -> DailyAuthorization:
        auth = self._load(trading_date)
        now = (now or datetime.now(CST)).astimezone(CST)
        if auth.status != "pending":
            raise ValueError("authorization is not pending")
        if auth.expires_at <= now:
            return self._expire(auth, now)
        if now.date().isoformat() != trading_date:
            raise ValueError("authorization can only be activated on its trading date")
        if (
            _hash(nonce) != auth.confirmation_nonce_hash
            or displayed_plan_hash != auth.plan.plan_hash
        ):
            raise ValueError("authorization confirmation mismatch")
        active = auth.model_copy(update={"status": "active", "activated_at": now})
        self._save(active, "activated")
        return active

    def current(
        self, trading_date: str, now: datetime | None = None
    ) -> DailyAuthorization | None:
        raw = self.store.read_json(f"authorization/{trading_date}.json")
        if not raw:
            return None
        auth = DailyAuthorization.model_validate(raw)
        now = (now or datetime.now(CST)).astimezone(CST)
        if auth.status in {"pending", "active"} and auth.expires_at <= now:
            return self._expire(auth, now)
        return auth

    def revoke(
        self, trading_date: str, reason: str, now: datetime | None = None
    ) -> DailyAuthorization:
        auth = self._load(trading_date)
        if auth.status in {"revoked", "expired"}:
            return auth
        revoked = auth.model_copy(
            update={
                "status": "revoked",
                "revoked_at": now or datetime.now(CST),
                "revoke_reason": reason,
            }
        )
        self._save(revoked, "revoked")
        return revoked

    def validate_runtime(
        self,
        trading_date: str,
        parameter_version: str,
        plan_hash: str,
        data_executable: bool,
        audit_passed: bool,
        risk_mode: str,
        now: datetime | None = None,
    ) -> DailyAuthorization | None:
        auth = self.current(trading_date, now)
        if not auth or auth.status != "active":
            return auth
        reason = None
        if (
            parameter_version != auth.plan.parameter_version
            or plan_hash != auth.plan.plan_hash
        ):
            reason = "parameters_or_plan_changed"
        elif not data_executable:
            reason = "data_degraded"
        elif not audit_passed:
            reason = "code_audit_failed"
        elif risk_mode != "normal":
            reason = f"risk_mode:{risk_mode}"
        return self.revoke(trading_date, reason, now) if reason else auth

    def _load(self, trading_date: str) -> DailyAuthorization:
        raw = self.store.read_json(f"authorization/{trading_date}.json")
        if not raw:
            raise KeyError("authorization not found")
        return DailyAuthorization.model_validate(raw)

    def _expire(self, auth: DailyAuthorization, now: datetime) -> DailyAuthorization:
        expired = auth.model_copy(
            update={
                "status": "expired",
                "revoked_at": now,
                "revoke_reason": "market_closed",
            }
        )
        self._save(expired, "expired")
        return expired

    def _save(self, auth: DailyAuthorization, action: str) -> None:
        self.store.write_json(
            f"authorization/{auth.plan.trading_date}.json", auth.model_dump(mode="json")
        )
        self.store.append_jsonl(
            "authorization/audit.jsonl",
            {"action": action, **auth.model_dump(mode="json")},
        )
