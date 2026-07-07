"""QMT bridge/client/execution adapter tests."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from factor_lab.broker.qmt_client import QMTClient
from factor_lab.broker.qmt_execution_adapter import QMTExecutionAdapter, QMTLivePolicy
from factor_lab.risk.kill_switch import KillSwitch


class FakeQMTClient:
    def __init__(self):
        self.placed = []
        self.cancelled = []
        self.existing_orders = []

    def health(self):
        return {"status": "ok", "data": {"connected": True}, "error": ""}

    def get_account(self):
        return {"status": "ok", "data": {"cash": 50000, "total_asset": 100000}, "error": ""}

    def get_positions(self):
        return {
            "status": "ok",
            "data": [
                {"symbol": "000002", "shares": 1000, "available_shares": 1000},
            ],
            "error": "",
        }

    def get_orders(self):
        return {"status": "ok", "data": self.existing_orders, "error": ""}

    def get_trades(self):
        return {"status": "ok", "data": [{"order_id": "ORD_B_001", "shares": 100, "price": 10.1}], "error": ""}

    def place_order(self, order, approval_id):
        self.placed.append((order, approval_id))
        return {
            "status": "ok",
            "data": {"qmt_order_id": f"QMT_{len(self.placed):03d}", "result": {"qmt_order_id": f"QMT_{len(self.placed):03d}"}},
            "error": "",
        }

    def cancel_order(self, qmt_order_id, approval_id):
        self.cancelled.append((qmt_order_id, approval_id))
        return {"status": "ok", "data": {"qmt_order_id": qmt_order_id, "cancelled": True}, "error": ""}


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _fixtures(tmp):
    orders_path = os.path.join(tmp, "order_preview.json")
    approval_path = os.path.join(tmp, "approval_summary.json")
    order = {
        "order_id": "ORD_B_001",
        "symbol": "000001",
        "name": "平安银行",
        "side": "buy",
        "order_shares": 100,
        "reference_price": 10.0,
        "limit_price": 10.05,
        "estimated_amount": 1005.0,
        "tradable": True,
    }
    _write_json(orders_path, {"orders": [order]})
    _write_json(approval_path, {"orders": [{**order, "approval_status": "approved_for_manual_entry"}]})
    return orders_path, approval_path


def test_qmt_client_unconfigured():
    client = QMTClient(base_url="")
    result = client.health()
    assert result["status"] == "error"
    assert "QMT_BRIDGE_BASE_URL" in result["error"]


def test_place_requires_live_env(monkeypatch):
    monkeypatch.delenv("QMT_LIVE_TRADING_ENABLED", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        adapter = QMTExecutionAdapter(client=FakeQMTClient(), output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["submitted"] == 0
        assert result["summary"]["blocked"] == 1
        assert "QMT_LIVE_TRADING_ENABLED" in result["results"][0]["reason"]


def test_place_approved_order(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        fake = FakeQMTClient()
        adapter = QMTExecutionAdapter(client=fake, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["submitted"] == 1
        assert fake.placed[0][0]["client_order_id"].endswith(":ORD_B_001")
        assert os.path.exists(os.path.join(tmp, "order_book.json"))
        assert os.path.exists(os.path.join(tmp, "qmt_execution_audit.jsonl"))


def test_duplicate_client_order_is_not_placed(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        fake = FakeQMTClient()
        fake.existing_orders = [{"client_order_id": f"{approval_path}:ORD_B_001", "qmt_order_id": "QMT_EXISTING"}]
        adapter = QMTExecutionAdapter(client=fake, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["duplicate_existing"] == 1
        assert fake.placed == []


def test_kill_switch_blocks_place(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        ks = KillSwitch()
        ks.trigger("test", "test trigger")
        adapter = QMTExecutionAdapter(client=FakeQMTClient(), kill_switch=ks, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["submitted"] == 0
        assert result["summary"]["blocked"] == 1
        assert "kill switch" in result["results"][0]["reason"]


def test_order_risk_blocks_large_order(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        policy = QMTLivePolicy(max_order_value=100.0)
        adapter = QMTExecutionAdapter(client=FakeQMTClient(), policy=policy, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["submitted"] == 0
        assert result["results"][0]["code"] == "max_order_value"


def test_sync_writes_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        adapter = QMTExecutionAdapter(client=FakeQMTClient(), output_dir=tmp)
        result = adapter.sync()
        assert result["status"] == "ok"
        for name in ["qmt_sync.json", "qmt_positions.csv", "qmt_orders.csv", "qmt_trades.csv", "order_book.json"]:
            assert os.path.exists(os.path.join(tmp, name))
