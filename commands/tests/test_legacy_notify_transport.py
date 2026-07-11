from __future__ import annotations

from pathlib import Path

import factor_lab.notification_transport as transport
import factor_lab.notify as notify
from factor_lab.decision_loop.storage import DecisionLoopStore


def test_enterprise_wechat_transport_preserves_markdown_payload(monkeypatch):
    captured = {}
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setattr(transport, "post_json", lambda url, payload: captured.update({"url": url, "payload": payload}) or {"ok": True})

    result = transport.enterprise_wechat_sender({"text": "**risk**", "format": "markdown"})

    assert result["ok"] is True
    assert captured["payload"] == {"msgtype": "markdown", "markdown": {"content": "**risk**"}}


def test_legacy_notify_queues_dual_channel_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DECISION_LOOP_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        transport,
        "post_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    assert notify._send_wecom_markdown("risk", "**content**") is True
    assert notify._send_wecom_markdown("risk", "**content**") is True
    outbox = DecisionLoopStore(tmp_path).read_jsonl("notifications/outbox.jsonl")
    assert {row["channel"] for row in outbox} == {"telegram", "enterprise_wechat"}
    assert len(outbox) == 2
    assert {row["payload"]["text"] for row in outbox} == {"**content**"}


def test_outbox_batch_append_is_idempotent(tmp_path):
    store = DecisionLoopStore(tmp_path)
    records = [({"channel": "telegram"}, "event:telegram"), ({"channel": "enterprise_wechat"}, "event:wecom")]
    _, first = store.append_unique_jsonl_batch("notifications/outbox.jsonl", records)
    _, second = store.append_unique_jsonl_batch("notifications/outbox.jsonl", records)
    assert first == 2
    assert second == 0
    assert len(store.read_jsonl("notifications/outbox.jsonl")) == 2


def test_legacy_notify_business_layer_has_no_network_sender() -> None:
    source = Path(notify.__file__).read_text(encoding="utf-8")
    assert "enterprise_wechat_sender" not in source
    assert "telegram_sender" not in source
    assert "append_unique_jsonl_batch" in source
