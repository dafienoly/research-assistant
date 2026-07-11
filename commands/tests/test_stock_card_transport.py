from __future__ import annotations

from PIL import Image

import gen_stock_card


def test_stock_card_push_uses_allowlisted_central_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gen_stock_card,
        "post_json",
        lambda url, payload, timeout: calls.append((url, payload, timeout))
        or {"ok": True, "response": {"errcode": 0}},
    )

    ok = gen_stock_card.push_to_wechat(
        Image.new("RGB", (2, 2)),
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
    )

    assert ok is True
    assert calls[0][1]["msgtype"] == "image"
    assert calls[0][2] == 15
