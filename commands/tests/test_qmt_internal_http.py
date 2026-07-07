"""QMT internal HTTP executor tests."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from factor_lab.broker.qmt_internal_http_client import QMTInternalHTTPClient
from factor_lab.broker.qmt_internal_execution_adapter import QMTInternalExecutionAdapter
from factor_lab.risk.kill_switch import KillSwitch


class FakeInternalHTTPClient:
    def __init__(self):
        self.placed_batches = []
        self.orders = []
        self.fills = []

    def health(self):
        return {"status": "ok", "data": {"connected": True, "live_trading_enabled": True}, "error": ""}

    def state(self):
        return {"status": "ok", "data": {"queue_length": 0}, "error": ""}

    def get_orders(self):
        return {"status": "ok", "data": self.orders, "error": ""}

    def get_fills(self):
        return {"status": "ok", "data": self.fills, "error": ""}

    def place_orders(self, approval_id, orders, batch_id=""):
        self.placed_batches.append((approval_id, orders, batch_id))
        response_orders = []
        for order in orders:
            row = dict(order)
            row["status"] = "queued"
            self.orders.append(row)
            response_orders.append({"client_order_id": order["client_order_id"], "status": "queued"})
        return {
            "status": "ok",
            "data": {"accepted": len(response_orders), "rejected": 0, "orders": response_orders},
            "error": "",
        }

    def cancel_order(self, approval_id, qmt_order_id):
        return {"status": "ok", "data": {"approval_id": approval_id, "qmt_order_id": qmt_order_id}, "error": ""}

    def disable_live(self):
        return {"status": "ok", "data": {"live_trading_enabled": False}, "error": ""}


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _fixtures(tmp, shares=100):
    orders_path = os.path.join(tmp, "order_preview.json")
    approval_path = os.path.join(tmp, "approval_summary.json")
    order = {
        "order_id": "ORD_B_001",
        "symbol": "000001",
        "name": "平安银行",
        "side": "buy",
        "order_shares": shares,
        "reference_price": 10.0,
        "limit_price": 10.05,
        "estimated_amount": 1005.0,
        "tradable": True,
    }
    _write_json(orders_path, {"orders": [order]})
    _write_json(approval_path, {"orders": [{**order, "approval_status": "approved_for_manual_entry"}]})
    return orders_path, approval_path


def test_internal_client_requires_token():
    client = QMTInternalHTTPClient(base_url="http://127.0.0.1:18765", token="")
    result = client.health()
    assert result["status"] == "error"
    assert "QMT_INTERNAL_HTTP_TOKEN" in result["error"]


def test_internal_place_requires_live_env(monkeypatch):
    monkeypatch.delenv("QMT_LIVE_TRADING_ENABLED", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        fake = FakeInternalHTTPClient()
        adapter = QMTInternalExecutionAdapter(client=fake, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["queued"] == 0
        assert result["summary"]["blocked"] == 1
        assert fake.placed_batches == []


def test_internal_place_approved_queues(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        fake = FakeInternalHTTPClient()
        adapter = QMTInternalExecutionAdapter(client=fake, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["queued"] == 1
        sent = fake.placed_batches[0][1][0]
        assert sent["client_order_id"].endswith(":ORD_B_001")
        assert sent["symbol"] == "000001.SZ"
        assert os.path.exists(os.path.join(tmp, "order_book.json"))
        assert os.path.exists(os.path.join(tmp, "qmt_execution_audit.jsonl"))


def test_internal_duplicate_client_order_is_not_placed(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        fake = FakeInternalHTTPClient()
        fake.orders = [{"client_order_id": f"{approval_path}:ORD_B_001", "status": "sent"}]
        adapter = QMTInternalExecutionAdapter(client=fake, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["duplicate_existing"] == 1
        assert fake.placed_batches == []


def test_internal_lot_size_blocks(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp, shares=50)
        adapter = QMTInternalExecutionAdapter(client=FakeInternalHTTPClient(), output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["blocked"] == 1
        assert result["results"][0]["code"] == "lot_blocked"


def test_internal_kill_switch_blocks(monkeypatch):
    monkeypatch.setenv("QMT_LIVE_TRADING_ENABLED", "1")
    with tempfile.TemporaryDirectory() as tmp:
        orders_path, approval_path = _fixtures(tmp)
        ks = KillSwitch()
        ks.trigger("test", "blocked")
        adapter = QMTInternalExecutionAdapter(client=FakeInternalHTTPClient(), kill_switch=ks, output_dir=tmp)
        result = adapter.place_approved_orders(approval_path, orders_path)
        assert result["summary"]["blocked"] == 1
        assert "kill switch" in result["results"][0]["reason"]


def test_internal_sync_maps_filled_and_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        fake = FakeInternalHTTPClient()
        fake.orders = [
            {
                "client_order_id": "approval_001:ORD_B_001",
                "symbol": "000001.SZ",
                "side": "buy",
                "quantity": 100,
                "price": 10.05,
                "status": "filled",
            },
            {
                "client_order_id": "approval_001:ORD_S_001",
                "symbol": "600519.SH",
                "side": "sell",
                "quantity": 100,
                "price": 1500.0,
                "status": "rejected",
            },
        ]
        fake.fills = [{"client_order_id": "approval_001:ORD_B_001", "filled_quantity": 100, "price": 10.05}]
        adapter = QMTInternalExecutionAdapter(client=fake, output_dir=tmp)
        result = adapter.sync()
        assert result["status"] == "ok"
        assert adapter.order_book.get_order("ORD_B_001").status == "filled"
        assert adapter.order_book.get_order("ORD_S_001").status == "rejected"
        assert os.path.exists(os.path.join(tmp, "qmt_internal_sync.json"))
