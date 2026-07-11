"""Telegram + Enterprise WeChat delivery with shared event IDs and independent receipts."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable

from .models import ActionCard, Severity
from .storage import DecisionLoopStore


Sender = Callable[[dict], dict]
ALLOWED_NOTIFICATION_HOSTS = {
    "api.telegram.org",
    "qyapi.weixin.qq.com",
    "work.weixin.qq.com",
}


def _post_json(url: str, payload: dict, timeout: int = 8) -> dict:
    endpoint = urllib.parse.urlsplit(url)
    if (
        endpoint.scheme != "https"
        or endpoint.hostname not in ALLOWED_NOTIFICATION_HOSTS
        or endpoint.username
        or endpoint.password
    ):
        return {"ok": False, "error": "endpoint_not_allowed"}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # The HTTPS scheme and exact hostname allow-list are enforced above.
        with urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            request, timeout=timeout
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {
                "ok": response.status < 300,
                "status_code": response.status,
                "response": body,
            }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def enterprise_wechat_sender(payload: dict) -> dict:
    webhook = os.environ.get("WECHAT_WEBHOOK_URL") or os.environ.get(
        "WECOM_WEBHOOK_URL"
    )
    if not webhook:
        return {"ok": False, "error": "not_configured"}
    content = payload["text"]
    return _post_json(webhook, {"msgtype": "text", "text": {"content": content}})


def telegram_sender(payload: dict) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"ok": False, "error": "not_configured"}
    return _post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": payload["text"], "disable_web_page_preview": True},
    )


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
        if event.severity == Severity.L2:
            self.store.append_jsonl(
                "notifications/l2_digest.jsonl", event.model_dump(mode="json")
            )
            return {
                "event_id": event.event_id,
                "delivery": "digest_queued",
                "channels": {},
            }
        payload = {"event_id": event.event_id, "text": self._format(event)}
        outcomes: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=len(self.senders) or 1) as pool:
            futures = {
                pool.submit(sender, payload): channel
                for channel, sender in self.senders.items()
            }
            for future in as_completed(futures):
                channel = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # sender isolation is intentional
                    result = {"ok": False, "error": type(exc).__name__}
                receipt = {
                    "event_id": event.event_id,
                    "channel": channel,
                    "delivered": bool(result.get("ok")),
                    "error": result.get("error"),
                    "attempted_at": datetime.now().astimezone().isoformat(),
                }
                outcomes[channel] = receipt
                self.store.append_jsonl(
                    "notifications/delivery_receipts.jsonl", receipt
                )
        return {
            "event_id": event.event_id,
            "delivery": "attempted",
            "channels": outcomes,
        }

    def flush_l2_digest(self) -> dict:
        events = self.store.read_jsonl("notifications/l2_digest.jsonl")
        delivered = self.store.read_json(
            "notifications/l2_digest_state.json", default={"count": 0}
        )
        pending = events[int(delivered.get("count", 0)) :]
        if not pending:
            return {"status": "empty", "count": 0}
        lines = ["Hermes L2 风险摘要"] + [
            f"- {row['event_id']} {row.get('symbol') or '组合'}: {row['reason']}"
            for row in pending
        ]
        synthetic = ActionCard.model_validate(
            {
                **pending[-1],
                "event_id": "digest_"
                + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S"),
                "severity": "L3",
                "reason": "L2摘要",
            }
        )
        payload = {"event_id": synthetic.event_id, "text": "\n".join(lines)}
        outcomes = {}
        for channel, sender in self.senders.items():
            try:
                outcomes[channel] = sender(payload)
            except Exception as exc:
                outcomes[channel] = {"ok": False, "error": type(exc).__name__}
        self.store.write_json(
            "notifications/l2_digest_state.json",
            {"count": len(events), "last_event_id": synthetic.event_id},
        )
        return {"status": "attempted", "count": len(pending), "channels": outcomes}

    def acknowledge(self, event_id: str, actor: str) -> dict:
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
