from __future__ import annotations

import wechat_push
from factor_lab.decision_loop.storage import DecisionLoopStore


def pusher(monkeypatch, tmp_path):
    monkeypatch.setitem(wechat_push.PATHS, "intraday", tmp_path)
    monkeypatch.setitem(wechat_push.ENV, "WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setitem(wechat_push.ENV, "WECHAT_ENABLED", True)
    monkeypatch.setitem(wechat_push.ENV, "WECHAT_DRY_RUN", False)
    monkeypatch.setenv("HERMES_DECISION_LOOP_STATE_DIR", str(tmp_path / "state"))
    return wechat_push.WeChatPusher()


def test_wechat_pusher_queues_dual_channel_intent(monkeypatch, tmp_path):
    client = pusher(monkeypatch, tmp_path)

    record = client.push_notice("L3", "risk", ["688012"], "半导体", "风险", ["风险提示"])

    assert record["sent"] is False
    assert record["queued"] is True
    outbox = DecisionLoopStore(tmp_path / "state").read_jsonl("notifications/outbox.jsonl")
    assert {row["channel"] for row in outbox} == {"telegram", "enterprise_wechat"}


def test_wechat_pusher_reports_persistence_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(wechat_push, "_send_wecom_markdown", lambda *_args: False)
    client = pusher(monkeypatch, tmp_path)

    record = client.push_urgent("L4", "risk", ["688012"], "半导体", "风险", "**风险**")

    assert record["sent"] is False
    assert record["queued"] is False
    assert record["message_summary"].startswith("[FAILED]")
