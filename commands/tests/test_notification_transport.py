from __future__ import annotations

import hashlib

import factor_lab.notification_transport as transport
from factor_lab.notification_transport import post_json
from factor_lab.vnext.execution import TelegramApprovalGate
from commands.tests.test_vnext import order


def test_transport_rejects_non_allowlisted_endpoint_without_network():
    assert post_json("http://api.telegram.org/test", {"text": "x"}) == {
        "ok": False,
        "error": "endpoint_not_allowed",
    }
    assert post_json("https://example.com/test", {"text": "x"}) == {
        "ok": False,
        "error": "endpoint_not_allowed",
    }


def test_vnext_approval_uses_injected_central_transport(tmp_path):
    payloads = []

    def sender(payload):
        payloads.append(payload)
        return {"ok": True, "status_code": 200}

    gate = TelegramApprovalGate(tmp_path, sender=sender)
    record = gate.create(order(), kill_switch=False, miniqmt_mode="PAPER")
    result = gate.send(record["approval_id"], dry_run=False)
    assert result["status"] == "SENT"
    assert payloads[0]["event_id"] == record["approval_id"]


def test_vnext_approval_maps_missing_credentials_fail_closed(tmp_path):
    gate = TelegramApprovalGate(
        tmp_path,
        sender=lambda _payload: {"ok": False, "error": "not_configured"},
    )
    record = gate.create(order(), kill_switch=False, miniqmt_mode="PAPER")
    result = gate.send(record["approval_id"], dry_run=False)
    assert result["status"] == "MISSING"
    assert result["sent"] is False


def test_attachment_senders_verify_state_root_and_sha(monkeypatch, tmp_path):
    image = b"\x89PNG\r\n\x1a\ncontent"
    attachment = tmp_path / "notifications" / "attachments" / "card.png"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(image)
    payload = {
        "text": "card",
        "attachment": {
            "relative_path": "notifications/attachments/card.png",
            "sha256": hashlib.sha256(image).hexdigest(),
            "mime": "image/png",
        },
    }
    monkeypatch.setenv("HERMES_DECISION_LOOP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    wechat = {}
    telegram = {}
    monkeypatch.setattr(
        transport,
        "post_json",
        lambda url, body: wechat.update({"url": url, "body": body}) or {"ok": True},
    )
    monkeypatch.setattr(
        transport,
        "_post_multipart",
        lambda url, fields, filename, data: telegram.update(
            {"url": url, "fields": fields, "filename": filename, "data": data}
        ) or {"ok": True},
    )
    assert transport.enterprise_wechat_sender(payload)["ok"] is True
    assert wechat["body"]["msgtype"] == "image"
    assert transport.telegram_sender(payload)["ok"] is True
    assert telegram["data"] == image
    assert telegram["fields"]["caption"] == "card"


def test_attachment_sender_rejects_path_escape(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DECISION_LOOP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    result = transport.telegram_sender(
        {
            "text": "x",
            "attachment": {
                "relative_path": "../secret.png",
                "sha256": "0" * 64,
                "mime": "image/png",
            },
        }
    )
    assert result == {"ok": False, "error": "invalid_attachment"}
