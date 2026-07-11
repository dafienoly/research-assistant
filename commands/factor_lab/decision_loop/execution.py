"""Governed MiniQMT interface; live execution is injected and fail-closed."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Protocol

from .authorization import AuthorizationService
from .models import AdviceMode, ExecutionRequest
from .storage import DecisionLoopStore


class OrderExecutor(Protocol):
    def place_order(self, payload: dict) -> dict: ...


class MiniQMTExecutor:
    """Narrow adapter around the existing local QMT Bridge client."""

    def __init__(self, client=None):
        if client is None:
            from factor_lab.broker.qmt_client import QMTClient

            client = QMTClient()
        self.client = client

    def is_configured(self) -> bool:
        return bool(getattr(self.client, "is_configured", lambda: False)())

    def place_order(self, payload: dict) -> dict:
        authorization_id = payload.get("authorization_id")
        if not authorization_id:
            return {"status": "error", "error": "authorization_id_missing"}
        order = {
            "order_id": payload["order_id"],
            "symbol": payload["symbol"],
            "side": payload["side"],
            "quantity": payload["quantity"],
            "limit_price": payload["limit_price"],
            "client_order_id": f"{authorization_id}:{payload['order_id']}",
        }
        return self.client.place_order(order, authorization_id)


class GovernedExecutionGateway:
    def __init__(
        self,
        authorizations: AuthorizationService | None = None,
        store: DecisionLoopStore | None = None,
        executor: OrderExecutor | None = None,
    ):
        self.store = store or DecisionLoopStore()
        self.authorizations = authorizations or AuthorizationService(self.store)
        self.executor = executor

    def submit(
        self, request: ExecutionRequest, trading_date: str, now: datetime | None = None
    ) -> dict:
        auth = self.authorizations.current(trading_date, now)
        if auth and auth.status == "active":
            auth = self.authorizations.validate_runtime(
                trading_date=trading_date,
                parameter_version=request.parameter_version,
                plan_hash=request.plan_hash,
                data_executable=request.data_mode == AdviceMode.EXECUTABLE
                or (
                    request.hard_risk_sell
                    and request.data_mode == AdviceMode.WATCH_ONLY
                ),
                audit_passed=request.audit_passed,
                risk_mode=request.risk_mode.value,
                now=now,
            )
        blocked = self._block_reason(request, auth)
        payload = {
            "order_id": request.order.order_id,
            "symbol": request.order.symbol,
            "side": request.order.side,
            "quantity": request.order.quantity,
            "limit_price": request.order.limit_price,
            "book": request.order.book.value,
            "authorization_id": auth.authorization_id if auth else None,
            "event_id": request.event_id,
            "hard_risk_sell": request.hard_risk_sell,
        }
        if blocked:
            result = {"status": "blocked", "reason": blocked, "payload": payload}
        else:
            if request.order.side == "SELL" and request.available_quantity is not None:
                payload["quantity"] = min(
                    payload["quantity"], request.available_quantity
                )
                if payload["quantity"] <= 0:
                    result = {
                        "status": "blocked",
                        "reason": "no_available_quantity",
                        "payload": payload,
                    }
                    self._audit(result)
                    return result
            if (
                self.executor is None
                or os.environ.get("QMT_LIVE_TRADING_ENABLED") != "1"
            ):
                result = {
                    "status": "blocked",
                    "reason": "miniqmt_live_not_configured",
                    "payload": payload,
                }
            else:
                response = self.executor.place_order(payload)
                result = {
                    "status": "submitted"
                    if response.get("status") == "ok"
                    else "rejected",
                    "payload": payload,
                    "broker_response": response,
                }
        self._audit(result)
        return result

    def _block_reason(self, request: ExecutionRequest, auth) -> str | None:
        protective_revoked_sell = bool(
            auth
            and auth.status == "revoked"
            and (
                str(auth.revoke_reason or "").startswith("risk_mode:")
                or auth.revoke_reason == "data_degraded"
            )
            and request.order.side == "SELL"
            and request.hard_risk_sell
            and request.event_id
            and request.data_mode != AdviceMode.BLOCKED
        )
        if not auth or (auth.status != "active" and not protective_revoked_sell):
            return "daily_authorization_inactive"
        if request.data_mode != AdviceMode.EXECUTABLE and not (
            request.hard_risk_sell and request.data_mode == AdviceMode.WATCH_ONLY
        ):
            return "data_gate_not_executable"
        if not request.audit_passed:
            return "code_audit_failed"
        if request.parameter_version != auth.plan.parameter_version:
            return "parameter_version_changed"
        if request.plan_hash != auth.plan.plan_hash:
            return "plan_hash_changed"
        if request.order.amount > auth.plan.max_order_amount:
            return "max_order_amount_exceeded"
        planned = {order.order_id: order for order in auth.plan.orders}
        if request.order.side == "BUY" and request.order.order_id not in planned:
            return "unplanned_buy_requires_new_approval"
        if request.order.order_id in planned and request.order.model_dump(
            mode="json"
        ) != planned[request.order.order_id].model_dump(mode="json"):
            return "planned_order_payload_changed"
        if (
            request.order.side == "SELL"
            and request.order.order_id not in planned
            and not request.hard_risk_sell
        ):
            return "unplanned_sell_requires_hard_risk_event"
        if request.hard_risk_sell and not request.event_id:
            return "hard_risk_sell_requires_event_id"
        submitted = [
            row
            for row in self.store.read_jsonl("execution/audit.jsonl")
            if row.get("status") == "submitted"
            and row.get("payload", {}).get("authorization_id") == auth.authorization_id
        ]
        if any(
            row.get("payload", {}).get("order_id") == request.order.order_id
            for row in submitted
        ):
            return "duplicate_order_id"
        executed_amount = sum(
            float(row["payload"].get("quantity", 0))
            * float(row["payload"].get("limit_price", 0))
            for row in submitted
        )
        if executed_amount + request.order.amount > auth.plan.max_total_amount:
            return "max_total_amount_exceeded"
        return None

    def _audit(self, result: dict) -> None:
        self.store.append_jsonl(
            "execution/audit.jsonl",
            {"timestamp": datetime.now().astimezone().isoformat(), **result},
        )
