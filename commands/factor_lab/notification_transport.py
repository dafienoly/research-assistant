"""Central outbound transport for Hermes notification channels."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


ALLOWED_NOTIFICATION_HOSTS = {
    "api.telegram.org",
    "qyapi.weixin.qq.com",
    "work.weixin.qq.com",
}


def post_json(url: str, payload: dict, timeout: int = 8) -> dict:
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
        with urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            request, timeout=timeout
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"ok": response.status < 300, "status_code": response.status, "response": body}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def enterprise_wechat_sender(payload: dict) -> dict:
    webhook = os.environ.get("WECHAT_WEBHOOK_URL") or os.environ.get("WECOM_WEBHOOK_URL")
    if not webhook:
        return {"ok": False, "error": "not_configured"}
    if payload.get("format") == "markdown":
        body = {"msgtype": "markdown", "markdown": {"content": payload["text"]}}
    else:
        body = {"msgtype": "text", "text": {"content": payload["text"]}}
    return post_json(webhook, body)


def telegram_sender(payload: dict) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"ok": False, "error": "not_configured"}
    return post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": payload["text"], "disable_web_page_preview": True},
    )
