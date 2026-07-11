"""Telegram + Enterprise WeChat delivery with shared event IDs and independent receipts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from .models import ActionCard, Severity
from .storage import DecisionLoopStore
from factor_lab.notification_transport import (
    enterprise_wechat_sender,
    telegram_sender,
)


Sender = Callable[[dict], dict]
class DualChannelNotifier:
    def __init__(
        self,
        store: DecisionLoopStore | None = None,
        senders: dict[str, Sender] | None = None,
    ):
        self.store = store or DecisionLoopStore()
        self.senders = senders or {
            "telegram": telegram_sender,
            "enterprise_wechat": enterprise_wechat_sender,
        }

    def notify(self, event: ActionCard) -> dict:
        queued = self.enqueue(event)
        if event.severity == Severity.L2:
            return queued
        delivered = self.deliver_pending(event_id=event.event_id)
        return {
            "event_id": event.event_id,
            "delivery": "attempted",
            "channels": delivered.get("channels", {}),
        }

    def enqueue(self, event: ActionCard) -> dict:
        """Persist notification work without performing network I/O."""
        self.store.append_unique_jsonl(
            "notifications/events.jsonl",
            event.model_dump(mode="json"),
            f"event:{event.event_id}",
        )
        if event.severity == Severity.L2:
            self.store.append_unique_jsonl(
                "notifications/l2_digest.jsonl",
                event.model_dump(mode="json"),
                f"l2:{event.event_id}",
            )
            return {
                "event_id": event.event_id,
                "delivery": "digest_queued",
                "channels": {},
            }
        payload = {"event_id": event.event_id, "text": self._format(event)}
        queued_at = datetime.now().astimezone().isoformat()
        outcomes = {}
        for channel in self.senders:
            key = f"{event.event_id}:{channel}"
            _, created = self.store.append_unique_jsonl(
                "notifications/outbox.jsonl",
                {
                    "event_id": event.event_id,
                    "channel": channel,
                    "payload": payload,
                    "queued_at": queued_at,
                    "max_attempts": 5,
                },
                key,
            )
            outcomes[channel] = {"queued": True, "created": created}
        return {"event_id": event.event_id, "delivery": "outbox_queued", "channels": outcomes}

    def deliver_pending(
        self,
        *,
        event_id: str | None = None,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict:
        """Deliver durable outbox rows with per-channel idempotency and retry state."""
        now = now or datetime.now().astimezone()
        with self.store.exclusive("notifications/outbox-worker", timeout=0.1):
            outbox = self.store.read_jsonl("notifications/outbox.jsonl")
            receipts = self.store.read_jsonl("notifications/delivery_receipts.jsonl")
            by_key: dict[str, list[dict]] = {}
            for receipt in receipts:
                key = f"{receipt.get('event_id')}:{receipt.get('channel')}"
                by_key.setdefault(key, []).append(receipt)
            channels: dict[str, dict] = {}
            attempted = 0
            for record in outbox:
                if attempted >= limit:
                    break
                if event_id and record.get("event_id") != event_id:
                    continue
                channel = str(record.get("channel"))
                key = f"{record.get('event_id')}:{channel}"
                history = by_key.get(key, [])
                delivered = next((item for item in reversed(history) if item.get("delivered")), None)
                if delivered:
                    channels[channel] = delivered
                    continue
                max_attempts = int(record.get("max_attempts", 5))
                attempt = len(history) + 1
                if attempt > max_attempts:
                    dead = {
                        "event_id": record.get("event_id"),
                        "channel": channel,
                        "attempts": len(history),
                        "dead_lettered_at": now.isoformat(),
                    }
                    self.store.append_unique_jsonl(
                        "notifications/dead_letter.jsonl", dead, f"dead:{key}"
                    )
                    channels[channel] = {**dead, "delivered": False, "dead_letter": True}
                    continue
                if history:
                    last_raw = history[-1].get("attempted_at")
                    try:
                        last_attempt = datetime.fromisoformat(str(last_raw))
                    except (TypeError, ValueError):
                        last_attempt = now - timedelta(days=1)
                    delay = min(300, 5 * (2 ** max(0, attempt - 2)))
                    if now < last_attempt + timedelta(seconds=delay):
                        channels[channel] = {**history[-1], "retry_after_seconds": delay}
                        continue
                sender = self.senders.get(channel)
                if sender is None:
                    result = {"ok": False, "error": "sender_unavailable"}
                else:
                    try:
                        result = sender(record.get("payload") or {})
                    except Exception as exc:  # sender isolation is intentional
                        result = {"ok": False, "error": type(exc).__name__}
                receipt = {
                    "event_id": record.get("event_id"),
                    "channel": channel,
                    "delivered": bool(result.get("ok")),
                    "error": result.get("error"),
                    "attempt": attempt,
                    "attempted_at": now.isoformat(),
                }
                self.store.append_unique_jsonl(
                    "notifications/delivery_receipts.jsonl",
                    receipt,
                    f"delivery:{key}:{attempt}",
                )
                channels[channel] = receipt
                attempted += 1
        return {
            "status": "attempted" if attempted else "idle",
            "attempted": attempted,
            "channels": channels,
        }

    def flush_l2_digest(self) -> dict:
        events = self.store.read_jsonl("notifications/l2_digest.jsonl")
        state = self.store.read_json("notifications/l2_digest_state.json", default={"channels": {}})
        cursors = state.get("channels", {})
        pending_counts = [len(events) - int(cursors.get(channel, 0)) for channel in self.senders]
        if not any(count > 0 for count in pending_counts):
            return {"status": "empty", "count": 0}
        outcomes = {}
        next_cursors = dict(cursors)
        for channel, sender in self.senders.items():
            cursor = int(cursors.get(channel, 0))
            pending = events[cursor:]
            if not pending:
                continue
            digest_id = f"digest_{channel}_{cursor}_{len(events)}"
            lines = ["Hermes L2 风险摘要"] + [
                f"- {row['event_id']} {row.get('symbol') or '组合'}: {row['reason']}"
                for row in pending
            ]
            payload = {"event_id": digest_id, "text": "\n".join(lines)}
            try:
                result = sender(payload)
            except Exception as exc:
                result = {"ok": False, "error": type(exc).__name__}
            receipt = {
                "event_id": digest_id,
                "channel": channel,
                "delivered": bool(result.get("ok")),
                "error": result.get("error"),
                "attempted_at": datetime.now().astimezone().isoformat(),
                "digest_from": cursor,
                "digest_to": len(events),
            }
            self.store.append_unique_jsonl(
                "notifications/delivery_receipts.jsonl",
                receipt,
                f"delivery:{digest_id}:{channel}",
            )
            outcomes[channel] = receipt
            if receipt["delivered"]:
                next_cursors[channel] = len(events)
        self.store.write_json("notifications/l2_digest_state.json", {"channels": next_cursors})
        delivered_count = sum(1 for item in outcomes.values() if item.get("delivered"))
        status = "delivered" if delivered_count == len(outcomes) else "partial" if delivered_count else "retry_pending"
        return {"status": status, "count": max(pending_counts), "channels": outcomes}

    def acknowledge(self, event_id: str, actor: str) -> dict:
        known = any(
            row.get("event_id") == event_id
            for ledger in ("events/events.jsonl", "notifications/events.jsonl")
            for row in self.store.read_jsonl(ledger)
        )
        if not known:
            return {"status": "not_found", "event_id": event_id}
        existing = next(
            (row for row in self.store.read_jsonl("notifications/acknowledgements.jsonl") if row.get("event_id") == event_id),
            None,
        )
        if existing:
            return existing
        record = {
            "event_id": event_id,
            "actor": actor,
            "acknowledged_at": datetime.now().astimezone().isoformat(),
            "closes_channels": list(self.senders),
        }
        self.store.append_unique_jsonl(
            "notifications/acknowledgements.jsonl", record, f"ack:{event_id}"
        )
        return record

    @staticmethod
    def _format(event: ActionCard) -> str:
        return (
            f"[{event.severity.value}] Hermes 风险操作卡\n"
            f"event_id: {event.event_id}\n"
            f"标的: {event.symbol or '组合'} / {event.book.value if event.book else '-'}\n"
            f"动作: {event.action} {event.quantity or ''}\n"
            f"原因: {event.reason}\n"
            f"模式: {event.advice_mode.value}\n"
            f"时间: {event.generated_at.isoformat()}"
        )
