from __future__ import annotations

import wechat_push


def pusher(monkeypatch, tmp_path):
    monkeypatch.setitem(wechat_push.PATHS, "intraday", tmp_path)
    monkeypatch.setitem(wechat_push.ENV, "WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setitem(wechat_push.ENV, "WECHAT_ENABLED", True)
    monkeypatch.setitem(wechat_push.ENV, "WECHAT_DRY_RUN", False)
    return wechat_push.WeChatPusher()


def test_wechat_pusher_uses_central_transport(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        wechat_push,
        "post_json",
        lambda url, payload, timeout: calls.append((url, payload, timeout))
        or {"ok": True, "response": {"errcode": 0}},
    )
    client = pusher(monkeypatch, tmp_path)

    record = client.push_notice("L3", "risk", ["688012"], "半导体", "风险", ["风险提示"])

    assert record["sent"] is True
    assert calls[0][1]["msgtype"] == "text"


def test_wechat_pusher_reports_central_transport_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(wechat_push, "post_json", lambda *_args, **_kwargs: {"ok": False, "error": "timeout"})
    client = pusher(monkeypatch, tmp_path)

    record = client.push_urgent("L4", "risk", ["688012"], "半导体", "风险", "**风险**")

    assert record["sent"] is False
    assert record["message_summary"].startswith("[FAILED]")
