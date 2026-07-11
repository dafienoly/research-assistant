from __future__ import annotations

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
