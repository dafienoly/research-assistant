from __future__ import annotations

import factor_lab.notification_transport as transport
import factor_lab.notify as notify


def test_enterprise_wechat_transport_preserves_markdown_payload(monkeypatch):
    captured = {}
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setattr(transport, "post_json", lambda url, payload: captured.update({"url": url, "payload": payload}) or {"ok": True})

    result = transport.enterprise_wechat_sender({"text": "**risk**", "format": "markdown"})

    assert result["ok"] is True
    assert captured["payload"] == {"msgtype": "markdown", "markdown": {"content": "**risk**"}}


def test_legacy_notify_delegates_to_central_transport_and_keeps_boolean(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "enterprise_wechat_sender", lambda payload: calls.append(payload) or {"ok": True})

    assert notify._send_wecom_markdown("risk", "**content**") is True
    assert calls == [{"text": "**content**", "format": "markdown"}]
