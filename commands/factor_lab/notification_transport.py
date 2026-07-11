"""Central outbound transport for Hermes notification channels."""

from __future__ import annotations

import json
import base64
import hashlib
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ALLOWED_NOTIFICATION_HOSTS = {
    "api.telegram.org",
    "qyapi.weixin.qq.com",
    "work.weixin.qq.com",
}
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024


def _attachment_bytes(payload: dict) -> tuple[bytes, str] | None:
    metadata = payload.get("attachment")
    if not isinstance(metadata, dict) or metadata.get("mime") != "image/png":
        return None
    relative = str(metadata.get("relative_path", ""))
    path = urllib.parse.unquote(relative)
    if not path or Path(path).is_absolute() or ".." in Path(path).parts:
        return None
    root = Path(
        os.environ.get(
            "HERMES_DECISION_LOOP_STATE_DIR",
            Path.home() / ".hermes/state/research-assistant/decision-loop",
        )
    ).resolve()
    source = (root / path).resolve()
    if root not in source.parents or not source.is_file():
        return None
    data = source.read_bytes()
    expected = str(metadata.get("sha256", ""))
    if not data or len(data) > MAX_ATTACHMENT_BYTES or hashlib.sha256(data).hexdigest() != expected:
        return None
    return data, source.name


def _post_multipart(url: str, fields: dict[str, str], filename: str, data: bytes, timeout: int = 8) -> dict:
    endpoint = urllib.parse.urlsplit(url)
    if endpoint.scheme != "https" or endpoint.hostname != "api.telegram.org" or endpoint.username or endpoint.password:
        return {"ok": False, "error": "endpoint_not_allowed"}
    boundary = f"----Hermes{secrets.token_hex(12)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode(),
        ])
    chunks.extend([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\nContent-Type: image/png\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        url,
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep
            body = json.loads(response.read().decode("utf-8"))
            return {"ok": response.status < 300 and bool(body.get("ok", True)), "status_code": response.status, "response": body}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__}


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
    attachment = _attachment_bytes(payload)
    if payload.get("attachment") and attachment is None:
        return {"ok": False, "error": "invalid_attachment"}
    if attachment:
        image, _ = attachment
        body = {
            "msgtype": "image",
            "image": {
                "base64": base64.b64encode(image).decode("ascii"),
                "md5": hashlib.md5(image, usedforsecurity=False).hexdigest(),
            },
        }
    elif payload.get("format") == "markdown":
        body = {"msgtype": "markdown", "markdown": {"content": payload["text"]}}
    else:
        body = {"msgtype": "text", "text": {"content": payload["text"]}}
    return post_json(webhook, body)


def telegram_sender(payload: dict) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"ok": False, "error": "not_configured"}
    attachment = _attachment_bytes(payload)
    if payload.get("attachment") and attachment is None:
        return {"ok": False, "error": "invalid_attachment"}
    if attachment:
        image, filename = attachment
        return _post_multipart(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            {"chat_id": chat_id, "caption": str(payload.get("text", ""))[:1024]},
            filename,
            image,
        )
    return post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": payload["text"], "disable_web_page_preview": True},
    )
