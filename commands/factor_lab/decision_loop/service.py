"""Application service composing safety, opportunity, and learning chains."""

from __future__ import annotations

from datetime import datetime

from .authorization import AuthorizationService
from .data_gate import evaluate_data_gate
from .execution import GovernedExecutionGateway, MiniQMTExecutor
from .models import DataItemStatus, Position, QuoteSnapshot
from .notifications import DualChannelNotifier
from .opportunity import OpportunityEngine
from .position_ingestion import PositionIngestionService
from .profit_guard import ProfitGuard
from .qmt_sync import QMTReconciliationService
from .review import ParameterPromotionService
from .storage import DecisionLoopStore


class DecisionLoopService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()
        self.positions = PositionIngestionService(self.store)
        self.qmt_sync = QMTReconciliationService(self.store)
        self.guard = ProfitGuard(self.store)
        self.notifications = DualChannelNotifier(self.store)
        self.authorizations = AuthorizationService(self.store)
        miniqmt = MiniQMTExecutor()
        self.execution = GovernedExecutionGateway(
            self.authorizations,
            self.store,
            miniqmt if miniqmt.is_configured() else None,
        )
        self.opportunities = OpportunityEngine()
        self.parameters = ParameterPromotionService(self.store)

    def status(self) -> dict:
        current = self.positions.current()
        today = datetime.now().astimezone().date().isoformat()
        auth = self.authorizations.current(today)
        return {
            "status": "ready" if current and current.confirmed else "blocked",
            "current_position_snapshot": current.model_dump(mode="json")
            if current
            else None,
            "daily_authorization": auth.model_dump(mode="json") if auth else None,
            "recent_events": self._recent_events(),
            "account_risk_mode": self.store.read_json("risk/current.json", default={"mode": "unknown"}),
            "data_gate": self.store.read_json("data_gate/current.json", default={"mode": "blocked", "reasons": ["not_evaluated"]}),
            "execution_readiness": self._execution_readiness(current, auth),
            "unacknowledged_event_count": self._unacknowledged_count(),
            "latest_reconciliation": self.qmt_sync.latest(),
            "capabilities": {
                "position_sources": ["csv", "clipboard", "ocr", "manual", "miniqmt"],
                "notification_channels": ["telegram", "enterprise_wechat"],
                "miniqmt_execution": "fail_closed_until_configured_and_authorized",
            },
        }

    def _unacknowledged_count(self) -> int:
        acknowledgements = {row.get("event_id") for row in self.store.read_jsonl("notifications/acknowledgements.jsonl")}
        return len({row.get("event_id") for row in self.store.read_jsonl("events/events.jsonl") if row.get("event_id") and row.get("event_id") not in acknowledgements})

    def _recent_events(self) -> list[dict]:
        acknowledgements = {
            row.get("event_id"): row
            for row in self.store.read_jsonl("notifications/acknowledgements.jsonl")
            if row.get("event_id")
        }
        return [
            {
                **event,
                "acknowledged": event.get("event_id") in acknowledgements,
                "acknowledged_at": acknowledgements.get(event.get("event_id"), {}).get("acknowledged_at"),
            }
            for event in self.store.read_jsonl("events/events.jsonl", limit=20)
        ]

    @staticmethod
    def _execution_readiness(current, auth) -> dict:
        live_enabled = __import__("os").environ.get("QMT_LIVE_TRADING_ENABLED") == "1"
        reasons = []
        if not current or not current.confirmed:
            reasons.append("confirmed_positions_missing")
        if not auth or auth.status != "active":
            reasons.append("daily_authorization_inactive")
        if not live_enabled:
            reasons.append("live_trading_disabled")
        return {"ready": not reasons, "live_enabled": live_enabled, "reasons": reasons}

    def evaluate_position(
        self,
        position: Position,
        quote: QuoteSnapshot,
        data_items: list[DataItemStatus],
        conflicts: list[dict] | None = None,
    ) -> dict:
        gate = evaluate_data_gate(data_items, conflicts, quote.observed_at)
        cards = self.guard.evaluate(position, quote, gate.mode)
        delivery = []
        for card in cards:
            delivery.append(self.notifications.notify(card))
        return {
            "data_gate": gate.model_dump(mode="json"),
            "actions": [card.model_dump(mode="json") for card in cards],
            "delivery": delivery,
        }
