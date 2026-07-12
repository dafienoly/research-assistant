"""Telegram + Enterprise WeChat delivery with shared event IDs and independent receipts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
import uuid

from .models import ActionCard, Severity
from .storage import DecisionLoopStore
from factor_lab.notification_transport import (
    enterprise_wechat_sender,
    telegram_sender,
)


Sender = Callable[[dict], dict]

CLAIM_LEASE_SECONDS = 120


def _parse_timestamp(raw: object, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=fallback.tzinfo)
    return parsed


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
        """Deliver durable outbox rows with short claim locks.

        The worker must never hold the cross-process lock while a sender is
        performing network I/O.  A durable lease prevents another worker from
        claiming the same channel during the bounded send timeout; the receipt
        write is idempotent if a lease expires and a retry races with the
        original worker.
        """
        now = now or datetime.now().astimezone()
        channels: dict[str, dict] = {}
        attempted = 0
        excluded_keys: set[str] = set()
        while attempted < limit:
            selection = self._claim_next(
                event_id=event_id,
                now=now,
                excluded_keys=excluded_keys,
            )
            if selection is None:
                break
            key = str(selection["key"])
            excluded_keys.add(key)
            if selection["kind"] == "observed":
                channels[str(selection["channel"])] = selection["result"]
                continue

            claim = selection["claim"]
            channel = str(claim["channel"])
            sender = self.senders.get(channel)
            if sender is None:
                result = {"ok": False, "error": "sender_unavailable"}
            else:
                try:
                    result = sender(claim.get("payload") or {})
                except Exception as exc:  # sender isolation is intentional
                    result = {"ok": False, "error": type(exc).__name__}
            result = self._normalize_sender_result(result)
            receipt = {
                "event_id": claim.get("event_id"),
                "channel": channel,
                "delivered": bool(result.get("ok")),
                "error": result.get("error"),
                "attempt": claim["attempt"],
                "attempted_at": now.isoformat(),
                "claim_id": claim["claim_id"],
            }
            channels[channel] = self._record_receipt(claim, receipt)
            attempted += 1
        return {
            "status": "attempted" if attempted else "idle",
            "attempted": attempted,
            "channels": channels,
        }

    def _claim_next(
        self,
        *,
        event_id: str | None,
        now: datetime,
        excluded_keys: set[str],
    ) -> dict | None:
        """Claim one eligible record while holding the lock briefly."""
        with self.store.exclusive("notifications/outbox-worker", timeout=0.1):
            outbox = self.store.read_jsonl("notifications/outbox.jsonl")
            receipts = self.store.read_jsonl("notifications/delivery_receipts.jsonl")
            claims = self.store.read_jsonl("notifications/claims.jsonl")
            by_key: dict[str, list[dict]] = {}
            for receipt in receipts:
                key = f"{receipt.get('event_id')}:{receipt.get('channel')}"
                by_key.setdefault(key, []).append(receipt)
            latest_claim: dict[str, dict] = {}
            for claim in claims:
                latest_claim[str(claim.get("key"))] = claim

            for record in outbox:
                if event_id and record.get("event_id") != event_id:
                    continue
                channel = str(record.get("channel"))
                key = f"{record.get('event_id')}:{channel}"
                if key in excluded_keys:
                    continue
                history = by_key.get(key, [])
                delivered = next(
                    (item for item in reversed(history) if item.get("delivered")),
                    None,
                )
                if delivered:
                    return {
                        "kind": "observed",
                        "key": key,
                        "channel": channel,
                        "result": delivered,
                    }
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
                    return {
                        "kind": "observed",
                        "key": key,
                        "channel": channel,
                        "result": {**dead, "delivered": False, "dead_letter": True},
                    }
                if history:
                    last_attempt = _parse_timestamp(history[-1].get("attempted_at"), now)
                    delay = min(300, 5 * (2 ** max(0, attempt - 2)))
                    if now < last_attempt + timedelta(seconds=delay):
                        return {
                            "kind": "observed",
                            "key": key,
                            "channel": channel,
                            "result": {**history[-1], "retry_after_seconds": delay},
                        }

                active = latest_claim.get(key)
                if active and self._claim_active(active, history, now):
                    return {
                        "kind": "observed",
                        "key": key,
                        "channel": channel,
                        "result": {
                            **active,
                            "status": "in_flight",
                            "delivered": False,
                        },
                    }
                claim = {
                    "claim_id": f"claim_{uuid.uuid4().hex}",
                    "key": key,
                    "event_id": record.get("event_id"),
                    "channel": channel,
                    "payload": record.get("payload") or {},
                    "attempt": attempt,
                    "claimed_at": now.isoformat(),
                    "lease_until": (now + timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat(),
                }
                self.store.append_jsonl("notifications/claims.jsonl", claim)
                return {"kind": "claim", "key": key, "claim": claim}
        return None

    @staticmethod
    def _claim_active(claim: dict, history: list[dict], now: datetime) -> bool:
        claim_id = str(claim.get("claim_id", ""))
        try:
            attempt = int(claim.get("attempt", 0) or 0)
        except (TypeError, ValueError):
            attempt = 0
        for row in history:
            if claim_id and str(row.get("claim_id", "")) == claim_id:
                return False
            try:
                row_attempt = int(row.get("attempt", -1) or -1)
            except (TypeError, ValueError):
                row_attempt = -1
            if row_attempt == attempt and row.get("attempted_at"):
                return False
        return _parse_timestamp(claim.get("lease_until"), now - timedelta(seconds=1)) > now

    def _record_receipt(self, claim: dict, receipt: dict) -> dict:
        """Write one idempotent result after the network call completes."""
        key = str(claim["key"])
        with self.store.exclusive("notifications/outbox-worker", timeout=0.1):
            path, created = self.store.append_unique_jsonl(
                "notifications/delivery_receipts.jsonl",
                receipt,
                f"delivery:{key}:{claim['attempt']}",
            )
            if created:
                return receipt
            relative = str(path.relative_to(self.store.root))
            for row in reversed(self.store.read_jsonl(relative)):
                if row.get("idempotency_key") == f"delivery:{key}:{claim['attempt']}":
                    return row
        return receipt

    def flush_l2_digest(self) -> dict:
        events = self.store.read_jsonl("notifications/l2_digest.jsonl")
        if not events:
            return {"status": "empty", "count": 0}
        state_before = self.store.read_json(
            "notifications/l2_digest_state.json", default={"channels": {}}
        )
        pending_before = [
            len(events) - self._l2_cursor(state_before.get("channels", {}).get(channel, 0))
            for channel in self.senders
        ]
        if not pending_before or not any(count > 0 for count in pending_before):
            return {"status": "empty", "count": 0}
        batch_count = max(pending_before)
        outcomes = {}
        now = datetime.now().astimezone()
        for channel, sender in self.senders.items():
            claim = self._reserve_l2_digest(channel, len(events), now)
            if not claim:
                continue
            pending = events[claim["cursor"]:claim["to"]]
            digest_id = claim["digest_id"]
            lines = ["Hermes L2 风险摘要"] + [
                f"- {row['event_id']} {row.get('symbol') or '组合'}: {row['reason']}"
                for row in pending
            ]
            payload = {"event_id": digest_id, "text": "\n".join(lines)}
            try:
                result = sender(payload)
            except Exception as exc:
                result = {"ok": False, "error": type(exc).__name__}
            result = self._normalize_sender_result(result)
            receipt = {
                "event_id": digest_id,
                "channel": channel,
                "delivered": bool(result.get("ok")),
                "error": result.get("error"),
                "attempted_at": now.isoformat(),
                "digest_from": claim["cursor"],
                "digest_to": claim["to"],
                "claim_id": claim["claim_id"],
            }
            outcomes[channel] = self._record_l2_receipt(claim, receipt)
            self._finish_l2_digest(claim, outcomes[channel])
        state = self.store.read_json("notifications/l2_digest_state.json", default={"channels": {}})
        pending_counts = [
            len(events) - self._l2_cursor(state.get("channels", {}).get(channel, 0))
            for channel in self.senders
        ]
        delivered_count = sum(1 for item in outcomes.values() if item.get("delivered"))
        if not any(count > 0 for count in pending_counts):
            status = "delivered"
        elif delivered_count == len(outcomes) and delivered_count:
            status = "partial" if any(count > 0 for count in pending_counts) else "delivered"
        else:
            status = "retry_pending" if not delivered_count else "partial"
        return {"status": status, "count": batch_count, "channels": outcomes}

    @staticmethod
    def _l2_cursor(raw: object) -> int:
        try:
            if isinstance(raw, dict):
                return max(0, int(raw.get("cursor", 0)))
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize_sender_result(result: object) -> dict:
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "invalid_sender_result"}

    def _reserve_l2_digest(
        self, channel: str, total: int, now: datetime
    ) -> dict | None:
        holder: dict[str, dict] = {}

        def mutate(state: dict) -> dict:
            channels = dict(state.get("channels") or {})
            raw = channels.get(channel, 0)
            cursor = self._l2_cursor(raw)
            active = raw.get("in_flight") if isinstance(raw, dict) else None
            if active and _parse_timestamp(active.get("lease_until"), now) > now:
                return state
            if cursor >= total:
                return state
            claim = {
                "claim_id": f"l2claim_{uuid.uuid4().hex}",
                "digest_id": f"digest_{channel}_{cursor}_{total}",
                "channel": channel,
                "cursor": cursor,
                "to": total,
                "claimed_at": now.isoformat(),
                "lease_until": (now + timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat(),
            }
            channels[channel] = {"cursor": cursor, "in_flight": claim}
            holder["claim"] = claim
            return {**state, "channels": channels}

        self.store.update_json(
            "notifications/l2_digest_state.json", {"channels": {}}, mutate
        )
        return holder.get("claim")

    def _record_l2_receipt(self, claim: dict, receipt: dict) -> dict:
        key = f"delivery:{claim['digest_id']}:{claim['channel']}"
        with self.store.exclusive("notifications/l2-digest-receipt", timeout=0.1):
            path, created = self.store.append_unique_jsonl(
                "notifications/delivery_receipts.jsonl", receipt, key
            )
            if created:
                return receipt
            relative = str(path.relative_to(self.store.root))
            for row in reversed(self.store.read_jsonl(relative)):
                if row.get("idempotency_key") == key:
                    return row
        return receipt

    def _finish_l2_digest(self, claim: dict, receipt: dict) -> None:
        def mutate(state: dict) -> dict:
            channels = dict(state.get("channels") or {})
            raw = channels.get(claim["channel"], {})
            if not isinstance(raw, dict):
                return state
            active = raw.get("in_flight") or {}
            if active.get("claim_id") != claim["claim_id"]:
                return state
            cursor = self._l2_cursor(raw)
            if receipt.get("delivered"):
                cursor = max(cursor, int(claim["to"]))
            channels[claim["channel"]] = {
                "cursor": cursor,
                "last_receipt": receipt,
            }
            return {**state, "channels": channels}

        self.store.update_json(
            "notifications/l2_digest_state.json", {"channels": {}}, mutate
        )

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
