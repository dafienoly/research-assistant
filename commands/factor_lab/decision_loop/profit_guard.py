"""Stateful profit high-water guard and structural-break confirmation."""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta

from .models import ActionCard, AdviceMode, Position, QuoteSnapshot, Severity
from .storage import DecisionLoopStore


class ProfitGuard:
    def __init__(
        self,
        store: DecisionLoopStore | None = None,
        structure_confirm_minutes: int = 10,
    ):
        self.store = store or DecisionLoopStore()
        self.structure_confirm_minutes = structure_confirm_minutes

    def evaluate(
        self, position: Position, quote: QuoteSnapshot, advice_mode: AdviceMode
    ) -> list[ActionCard]:
        day = quote.observed_at.astimezone().date().isoformat()
        key = f"{position.symbol}:{position.book.value}"
        states = self.store.read_json(f"guard/{day}.json", default={})
        state = states.get(key, {})
        current_return = (
            (quote.last_price / position.cost_price - 1.0) * 100
            if position.cost_price
            else 0.0
        )
        peak_return = max(
            float(state.get("peak_return_pct", current_return)), current_return
        )
        morning_low = state.get("morning_low")
        if quote.observed_at.astimezone().time() <= time(11, 30):
            morning_low = (
                quote.last_price
                if morning_low is None
                else min(float(morning_low), quote.last_price)
            )
        giveback = max(0.0, peak_return - current_return)
        events: list[ActionCard] = []

        if giveback >= 2 and not state.get("warned"):
            events.append(
                self._card(
                    position,
                    quote,
                    Severity.L2,
                    "warn",
                    current_return,
                    peak_return,
                    giveback,
                    advice_mode,
                    "最高浮盈回撤达到2个百分点",
                )
            )
            state["warned"] = True
        if giveback >= 3 and not state.get("halved"):
            quantity = min(position.available_quantity, max(0, position.quantity // 2))
            events.append(
                self._card(
                    position,
                    quote,
                    Severity.L3,
                    "reduce_half",
                    current_return,
                    peak_return,
                    giveback,
                    advice_mode,
                    "最高浮盈回撤达到3个百分点，减半交易仓",
                    quantity,
                )
            )
            state["halved"] = True

        broken = bool(
            (morning_low is not None and quote.last_price < float(morning_low))
            or (quote.vwap and quote.last_price < quote.vwap)
        )
        if state.get("halved") and broken:
            break_since = (
                datetime.fromisoformat(state["break_since"])
                if state.get("break_since")
                else quote.observed_at
            )
            state["break_since"] = break_since.isoformat()
            if quote.observed_at - break_since >= timedelta(
                minutes=self.structure_confirm_minutes
            ) and not state.get("exited"):
                events.append(
                    self._card(
                        position,
                        quote,
                        Severity.L4,
                        "exit_remaining",
                        current_return,
                        peak_return,
                        giveback,
                        advice_mode,
                        "跌破上午低点或VWAP且10分钟未收回，退出剩余交易仓",
                        position.available_quantity,
                    )
                )
                state["exited"] = True
        else:
            state.pop("break_since", None)

        volume_confirmed = (
            quote.average_volume is not None
            and quote.volume >= quote.average_volume * 1.2
        )
        if (
            state.get("exited")
            and quote.vwap
            and quote.last_price >= quote.vwap
            and volume_confirmed
            and not state.get("reentry_noted")
        ):
            events.append(
                self._card(
                    position,
                    quote,
                    Severity.L2,
                    "reentry_eligible",
                    current_return,
                    peak_return,
                    giveback,
                    advice_mode,
                    "放量重新站回VWAP，仅恢复重新介入资格",
                )
            )
            state["reentry_noted"] = True

        state.update(
            {
                "peak_return_pct": peak_return,
                "morning_low": morning_low,
                "last_price": quote.last_price,
                "last_seen": quote.observed_at.isoformat(),
            }
        )
        states[key] = state
        self.store.write_json(f"guard/{day}.json", states)
        for event in events:
            self.store.append_jsonl(
                "events/events.jsonl", event.model_dump(mode="json")
            )
        return events

    @staticmethod
    def _card(
        position,
        quote,
        severity,
        action,
        current,
        peak,
        giveback,
        mode,
        reason,
        quantity=None,
    ):
        fingerprint = f"{quote.observed_at.date()}|{position.symbol}|{position.book.value}|{action}"
        event_id = "evt_" + hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
        return ActionCard(
            event_id=event_id,
            severity=severity,
            symbol=position.symbol,
            book=position.book,
            action=action,
            quantity=quantity,
            reason=reason,
            current_return_pct=round(current, 4),
            peak_return_pct=round(peak, 4),
            giveback_points=round(giveback, 4),
            advice_mode=mode,
            generated_at=quote.observed_at,
            evidence=[
                {
                    "source": quote.source,
                    "as_of": quote.observed_at.isoformat(),
                    "freshness_seconds": quote.freshness_seconds,
                    "last_price": quote.last_price,
                    "vwap": quote.vwap,
                },
            ],
        )
