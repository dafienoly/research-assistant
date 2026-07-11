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
from .review import ParameterPromotionService
from .storage import DecisionLoopStore


class DecisionLoopService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()
        self.positions = PositionIngestionService(self.store)
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
            "status": "ready",
            "current_position_snapshot": current.model_dump(mode="json")
            if current
            else None,
            "daily_authorization": auth.model_dump(mode="json") if auth else None,
            "recent_events": self.store.read_jsonl("events/events.jsonl", limit=20),
            "capabilities": {
                "position_sources": ["csv", "clipboard", "ocr", "manual", "miniqmt"],
                "notification_channels": ["telegram", "enterprise_wechat"],
                "miniqmt_execution": "fail_closed_until_configured_and_authorized",
            },
        }

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
