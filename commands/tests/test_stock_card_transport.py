from __future__ import annotations

from PIL import Image

import gen_stock_card
from factor_lab.decision_loop.storage import DecisionLoopStore


def test_stock_card_push_queues_content_addressed_dual_channel_attachment(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DECISION_LOOP_STATE_DIR", str(tmp_path))

    ok = gen_stock_card.push_to_wechat(
        Image.new("RGB", (2, 2)),
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
    )

    assert ok is True
    outbox = DecisionLoopStore(tmp_path).read_jsonl("notifications/outbox.jsonl")
    assert {row["channel"] for row in outbox} == {"telegram", "enterprise_wechat"}
    attachments = {row["payload"]["attachment"]["relative_path"] for row in outbox}
    assert len(attachments) == 1
    attachment = tmp_path / attachments.pop()
    assert attachment.is_file()
    assert attachment.read_bytes().startswith(b"\x89PNG")
