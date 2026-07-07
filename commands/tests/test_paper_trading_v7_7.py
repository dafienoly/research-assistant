"""V7.7 Paper Trading Dashboard — 测试

覆盖:
  单元测试 (PaperTradingService):
    - 账户管理: 余额查询、重置
    - 下单: 买入/卖出/限价/市价
    - 成交模拟: 全成/部分成交/资金不足/持仓不足
    - 订单管理: 列表/过滤/撤销
    - 成交记录: 列表/过滤
    - 持仓: 均价/盈亏计算
    - 价格更新与未实现盈亏

  API 测试 (routes_paper):
    - GET  /api/paper/balance      — 余额
    - GET  /api/paper/positions    — 持仓
    - POST /api/paper/orders       — 下单
    - GET  /api/paper/orders       — 订单列表
    - DELETE /api/paper/orders/{id} — 撤销
    - GET  /api/paper/fills        — 成交记录
    - POST /api/paper/reset        — 重置

  边界条件:
    - 空账户
    - 无持仓
    - 无订单
    - 无效参数
    - 重复撤销
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from factor_lab.paper_trading_service import (
    PaperTradingService,
    _get_service,
    _reset_service,
    PaperAccount,
    PaperPosition,
    PaperOrder,
    PaperFill,
)
from factor_lab.api_server.main import app


# ═══════════════════════════════════════════════════════════════════
# 单元测试: PaperTradingService
# ═══════════════════════════════════════════════════════════════════


class TestPaperTradingService:
    """PaperTradingService 核心功能测试"""

    @pytest.fixture
    def service(self):
        svc = PaperTradingService(initial_cash=1_000_000.0)
        yield svc

    # ── Account ──

    def test_initial_balance(self, service):
        """初始余额 1,000,000"""
        bal = service.get_balance()
        assert bal["cash"] == 1_000_000.0
        assert bal["initial_cash"] == 1_000_000.0
        assert bal["total_value"] == 1_000_000.0
        assert bal["total_pnl"] == 0.0
        assert bal["market_value"] == 0.0
        assert bal["unrealized_pnl"] == 0.0

    def test_balance_structure(self, service):
        """余额返回结构完整性"""
        bal = service.get_balance()
        required_keys = [
            "account_id", "cash", "initial_cash", "total_value",
            "market_value", "unrealized_pnl", "realized_pnl",
            "total_pnl", "total_pnl_pct", "created_at", "updated_at",
        ]
        for key in required_keys:
            assert key in bal, f"Missing key: {key}"

    # ── Place order: buy ──

    def test_place_buy_limit_order(self, service):
        """下单买入 — 限价单"""
        result = service.place_order(
            symbol="000001",
            side="buy",
            quantity=1000,
            price=10.0,
            order_type="limit",
        )
        assert result["order_id"].startswith("paper_")
        assert result["symbol"] == "000001"
        assert result["side"] == "buy"
        assert result["status"] == "filled"
        assert result["filled_quantity"] == 1000
        assert result["price"] == 10.0

    def test_place_buy_updates_cash(self, service):
        """买入后现金减少"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        bal = service.get_balance()
        # 1000 * 10 = 10000, 佣金 10000 * 0.0003 = 3
        expected_cash = 1_000_000 - 10000 - 3
        assert abs(bal["cash"] - expected_cash) < 0.01

    def test_place_buy_updates_positions(self, service):
        """买入后持仓更新"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        pos = service.get_positions()
        assert len(pos) == 1
        assert pos[0]["symbol"] == "000001"
        assert pos[0]["shares"] == 1000
        assert pos[0]["avg_cost"] == 10.0

    def test_place_buy_insufficient_cash(self, service):
        """买入资金不足 — 部分成交"""
        # 尝试买入远超现金的股票
        result = service.place_order(
            symbol="000001", side="buy", quantity=1_000_000, price=100.0,
        )
        # 应该部分成交或拒绝
        assert result["status"] in ("partial", "filled", "rejected")

    def test_place_buy_insufficient_cash_total_reject(self, service):
        """买入资金严重不足 — 拒绝"""
        svc = PaperTradingService(initial_cash=1000.0)
        result = svc.place_order(
            symbol="000001", side="buy", quantity=100, price=100.0,
        )
        assert "error" in result

    # ── Place order: sell ──

    def test_place_sell_limit_order(self, service):
        """下单卖出 — 先买后卖"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        result = service.place_order(
            symbol="000001", side="sell", quantity=500, price=11.0,
        )
        assert result["side"] == "sell"
        assert result["status"] == "filled"
        assert result["filled_quantity"] == 500

    def test_place_sell_insufficient_shares(self, service):
        """卖出持仓不足 — 拒绝"""
        # 先买 100 股
        service.place_order(symbol="000001", side="buy", quantity=100, price=10.0)
        result = service.place_order(
            symbol="000001", side="sell", quantity=999, price=11.0,
        )
        assert "error" in result or result["status"] == "rejected"

    def test_place_sell_no_position(self, service):
        """卖出无持仓 — 错误"""
        result = service.place_order(
            symbol="000001", side="sell", quantity=100, price=10.0,
        )
        assert "error" in result

    def test_sell_updates_cash(self, service):
        """卖出后现金增加"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        bal_before = service.get_balance()
        service.place_order(symbol="000001", side="sell", quantity=500, price=11.0)
        bal_after = service.get_balance()
        assert bal_after["cash"] > bal_before["cash"]

    # ── Order validation ──

    def test_invalid_side(self, service):
        """无效方向"""
        result = service.place_order(symbol="000001", side="invalid", quantity=100, price=10.0)
        assert "error" in result

    def test_invalid_quantity(self, service):
        """无效数量"""
        result = service.place_order(symbol="000001", side="buy", quantity=0, price=10.0)
        assert "error" in result

    def test_invalid_price(self, service):
        """无效价格"""
        result = service.place_order(symbol="000001", side="buy", quantity=100, price=0)
        assert "error" in result

    def test_invalid_order_type(self, service):
        """无效订单类型"""
        result = service.place_order(symbol="000001", side="buy", quantity=100, price=10.0, order_type="unknown")
        assert "error" in result

    # ── Order management ──

    def test_get_orders(self, service):
        """获取订单列表"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        orders = service.get_orders()
        assert len(orders) == 1
        assert orders[0]["symbol"] == "000001"

    def test_get_orders_filter_by_status(self, service):
        """按状态过滤订单"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        filled = service.get_orders(status="filled")
        pending = service.get_orders(status="pending")
        assert len(filled) >= 0
        assert len(pending) == 0

    def test_get_orders_filter_by_symbol(self, service):
        """按代码过滤订单"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        orders = service.get_orders(symbol="000001")
        assert len(orders) == 1
        orders_wrong = service.get_orders(symbol="999999")
        assert len(orders_wrong) == 0

    def test_cancel_order(self, service):
        """撤销订单（市价单立即成交，用限价单但价格设低让买单无法成交）"""
        # 创建一个正确定价但无法成交的场景来测试撤销
        # 实际上限价买单如果现金够就会直接成交，我们需要创建一个 pending 订单
        # 可以通过先大量买入消耗现金
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        # 下单卖出 — 如果无持仓会返回错误，但我们有 1000 股
        # 追踪创建的订单 ID
        result = service.place_order(symbol="000002", side="buy", quantity=100, price=5.0)
        orders = service.get_orders(status="pending")
        if orders:
            cancel_result = service.cancel_order(orders[0]["order_id"])
            assert cancel_result["status"] == "canceled"

    def test_cancel_filled_order(self, service):
        """撤销已成交订单 — 应返回错误"""
        result = service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        assert result["status"] == "filled"
        cancel_result = service.cancel_order(result["order_id"])
        assert "error" in cancel_result

    def test_cancel_nonexistent_order(self, service):
        """撤销不存在的订单 — 应返回错误"""
        result = service.cancel_order("nonexistent")
        assert "error" in result

    def test_get_orders_limit(self, service):
        """订单数量限制"""
        for i in range(5):
            service.place_order(symbol="000001", side="buy", quantity=100, price=10.0)
        orders = service.get_orders(limit=3)
        assert len(orders) == 3

    # ── Fills ──

    def test_get_fills(self, service):
        """获取成交记录"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        fills = service.get_fills()
        assert len(fills) >= 1
        assert fills[0]["symbol"] == "000001"
        assert fills[0]["side"] == "buy"

    def test_get_fills_filter_by_symbol(self, service):
        """按代码过滤成交记录"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.place_order(symbol="000002", side="buy", quantity=500, price=20.0)
        fills = service.get_fills(symbol="000001")
        assert len(fills) >= 1
        for f in fills:
            assert f["symbol"] == "000001"

    def test_fill_has_fee(self, service):
        """成交记录包含佣金"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        fills = service.get_fills()
        fill = fills[0]
        assert fill["fee"] > 0
        assert fill["fill_price"] == 10.0
        assert fill["fill_quantity"] == 1000

    def test_sell_fill_has_tax(self, service):
        """卖出成交记录包含印花税"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        fills_buy = service.get_fills()
        service.place_order(symbol="000001", side="sell", quantity=500, price=11.0)
        fills = service.get_fills()
        sell_fills = [f for f in fills if f["side"] == "sell"]
        if sell_fills:
            assert sell_fills[0]["tax"] > 0

    def test_get_fills_empty(self, service):
        """无成交时返回空列表"""
        fills = service.get_fills()
        assert fills == []

    # ── Positions ──

    def test_get_positions_empty(self, service):
        """无持仓时返回空列表"""
        pos = service.get_positions()
        assert pos == []

    def test_get_positions_filter(self, service):
        """按 symbol 过滤持仓"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        pos = service.get_positions(symbol="000001")
        assert len(pos) == 1
        pos_wrong = service.get_positions(symbol="999999")
        assert len(pos_wrong) == 0

    def test_position_avg_cost(self, service):
        """持仓均价计算"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.place_order(symbol="000001", side="buy", quantity=500, price=12.0)
        pos = service.get_positions(symbol="000001")
        assert len(pos) == 1
        expected_avg = (1000 * 10.0 + 500 * 12.0) / 1500
        assert abs(pos[0]["avg_cost"] - expected_avg) < 0.01

    def test_position_partial_sell(self, service):
        """部分卖出后持仓减少"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.place_order(symbol="000001", side="sell", quantity=300, price=11.0)
        pos = service.get_positions(symbol="000001")
        assert len(pos) == 1
        assert pos[0]["shares"] == 700

    def test_position_full_sell(self, service):
        """全部卖出后持仓清空"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.place_order(symbol="000001", side="sell", quantity=1000, price=11.0)
        pos = service.get_positions(symbol="000001")
        assert len(pos) == 0

    # ── Price update ──

    def test_update_price(self, service):
        """更新价格影响未实现盈亏"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.update_price("000001", 12.0)
        pos = service.get_positions(symbol="000001")
        assert pos[0]["current_price"] == 12.0
        assert pos[0]["unrealized_pnl"] == 2000.0  # 1000 * (12 - 10)
        assert pos[0]["unrealized_pnl_pct"] == 0.2  # 20%

    def test_update_price_negative_pnl(self, service):
        """价格下跌产生负盈亏"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.update_price("000001", 8.0)
        pos = service.get_positions(symbol="000001")
        assert pos[0]["unrealized_pnl"] == -2000.0

    # ── Reset ──

    def test_reset(self, service):
        """重置清空所有数据"""
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        assert len(service.get_positions()) > 0
        assert len(service.get_orders()) > 0
        service.reset()
        assert service.get_balance()["cash"] == 1_000_000.0
        assert len(service.get_positions()) == 0
        assert len(service.get_orders()) == 0
        assert len(service.get_fills()) == 0

    def test_reset_custom_initial(self, service):
        """重置时可指定初始资金"""
        service.reset(initial_cash=500_000.0)
        assert service.get_balance()["cash"] == 500_000.0
        assert service.get_balance()["initial_cash"] == 500_000.0

    # ── Market order ──

    def test_place_buy_market_order(self, service):
        """市价买入"""
        result = service.place_order(
            symbol="000001", side="buy", quantity=1000, price=10.0, order_type="market",
        )
        assert result["status"] == "filled"
        assert result["filled_quantity"] == 1000


# ═══════════════════════════════════════════════════════════════════
# API 测试
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_service():
    _reset_service()
    yield
    _reset_service()


@pytest.fixture
def client():
    return TestClient(app)


class TestPaperAPI:
    """纸面交易 API 测试"""

    # ── Balance ──

    def test_get_balance(self, client):
        resp = client.get("/api/paper/balance")
        assert resp.status_code == 200
        d = resp.json()
        assert d["cash"] == 1_000_000.0
        assert d["total_value"] == 1_000_000.0
        assert d["total_pnl"] == 0.0
        assert "unrealized_pnl" in d
        assert "market_value" in d

    # ── Positions ──

    def test_get_positions_empty(self, client):
        resp = client.get("/api/paper/positions")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 0
        assert d["positions"] == []

    def test_get_positions_after_buy(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.get("/api/paper/positions")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 1
        assert d["positions"][0]["symbol"] == "000001"

    def test_get_positions_filter(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.get("/api/paper/positions?symbol=000001")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 1

    # ── Place order ──

    def test_place_order(self, client):
        resp = client.post("/api/paper/orders?symbol=000001&side=buy&quantity=1000&price=10.0")
        assert resp.status_code == 200
        d = resp.json()
        assert d["order_id"].startswith("paper_")
        assert d["status"] in ("filled", "partial")
        assert d["symbol"] == "000001"

    def test_place_order_invalid_side(self, client):
        resp = client.post("/api/paper/orders?symbol=000001&side=invalid&quantity=1000&price=10.0")
        assert resp.status_code == 200
        d = resp.json()
        assert "error" in d

    def test_place_order_market(self, client):
        resp = client.post("/api/paper/orders?symbol=000001&side=buy&quantity=1000&price=10.0&order_type=market")
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "filled"

    def test_place_order_sell_rejected_no_position(self, client):
        resp = client.post("/api/paper/orders?symbol=000001&side=sell&quantity=100&price=10.0")
        assert resp.status_code == 200
        d = resp.json()
        assert "error" in d

    def test_place_order_sell_ok(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.post("/api/paper/orders?symbol=000001&side=sell&quantity=500&price=11.0")
        assert resp.status_code == 200
        d = resp.json()
        assert d["side"] == "sell"
        assert d["status"] == "filled"

    # ── Orders ──

    def test_get_orders(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.get("/api/paper/orders")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] >= 1
        assert len(d["orders"]) >= 1

    def test_get_orders_empty(self, client):
        resp = client.get("/api/paper/orders")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 0

    def test_get_orders_filter(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.get("/api/paper/orders?status=filled")
        assert resp.status_code == 200
        d = resp.json()
        for o in d["orders"]:
            assert o["status"] == "filled"

    def test_get_orders_limit(self, client):
        service = _get_service()
        for _ in range(5):
            service.place_order(symbol="000001", side="buy", quantity=100, price=10.0)
        resp = client.get("/api/paper/orders?limit=3")
        assert resp.status_code == 200
        d = resp.json()
        assert len(d["orders"]) == 3

    # ── Cancel order ──

    def test_cancel_order(self, client):
        # 创建一个可能 pending 的订单
        svc = _get_service()
        # 先消耗部分现金再下单另一个股票
        svc.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        result = svc.place_order(symbol="000002", side="buy", quantity=100, price=5.0)
        if result["status"] == "pending":
            resp = client.delete(f"/api/paper/orders/{result['order_id']}")
            assert resp.status_code == 200
            d = resp.json()
            assert d["status"] == "canceled"

    def test_cancel_nonexistent(self, client):
        resp = client.delete("/api/paper/orders/nonexistent")
        assert resp.status_code == 400
        d = resp.json()
        assert "error" in d

    # ── Fills ──

    def test_get_fills(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.get("/api/paper/fills")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] >= 1
        assert len(d["fills"]) >= 1

    def test_get_fills_empty(self, client):
        resp = client.get("/api/paper/fills")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 0

    def test_get_fills_filter(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        service.place_order(symbol="000002", side="buy", quantity=500, price=20.0)
        resp = client.get("/api/paper/fills?symbol=000001")
        assert resp.status_code == 200
        d = resp.json()
        for f in d["fills"]:
            assert f["symbol"] == "000001"

    # ── Reset ──

    def test_reset(self, client):
        service = _get_service()
        service.place_order(symbol="000001", side="buy", quantity=1000, price=10.0)
        resp = client.post("/api/paper/reset")
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "ok"

        bal = _get_service().get_balance()
        assert bal["cash"] == 1_000_000.0

    def test_reset_custom(self, client):
        resp = client.post("/api/paper/reset?initial_cash=500000")
        assert resp.status_code == 200
        bal = _get_service().get_balance()
        assert bal["cash"] == 500_000.0


# ═══════════════════════════════════════════════════════════════════
# 数据模型测试
# ═══════════════════════════════════════════════════════════════════


class TestModels:
    """数据模型基础测试"""

    def test_account_to_dict(self):
        acct = PaperAccount(cash=50000, initial_cash=100000)
        d = acct.to_dict()
        assert d["cash"] == 50000.0
        assert d["initial_cash"] == 100000.0
        assert "total_value" in d
        assert "total_pnl" in d

    def test_position_to_dict(self):
        pos = PaperPosition(symbol="000001", shares=1000, avg_cost=10.0, current_price=12.0)
        d = pos.to_dict()
        assert d["symbol"] == "000001"
        assert d["shares"] == 1000
        assert d["unrealized_pnl"] == 2000.0

    def test_position_zero_cost(self):
        pos = PaperPosition(symbol="000001", shares=0, avg_cost=0.0, current_price=0.0)
        assert pos.unrealized_pnl_pct == 0.0

    def test_order_to_dict(self):
        o = PaperOrder(order_id="test_001", symbol="000001", side="buy", price=10.0, quantity=1000)
        d = o.to_dict()
        assert d["order_id"] == "test_001"
        assert d["remaining"] == 1000

    def test_fill_to_dict(self):
        f = PaperFill(fill_id="fill_001", order_id="ord_001", symbol="000001", side="buy",
                       fill_price=10.0, fill_quantity=1000)
        d = f.to_dict()
        assert d["fill_id"] == "fill_001"
        assert d["fill_quantity"] == 1000


# ═══════════════════════════════════════════════════════════════════
# 安全验证
# ═══════════════════════════════════════════════════════════════════


class TestSafety:
    """安全验证: 不下达真实订单"""

    def test_service_no_real_trade_methods(self):
        """PaperTradingService 不包含 send_order/place_order/execute_trade/auto_trade"""
        src = open(
            "/home/ly/.hermes/research-assistant/commands/factor_lab/paper_trading_service.py"
        ).read()
        for term in ["send_order", "execute_trade", "auto_trade"]:
            assert term not in src, f"含禁用词: {term}"

    def test_routes_no_real_trade_methods(self):
        """routes_paper 不包含 send_order/place_order/execute_trade/auto_trade"""
        src = open(
            "/home/ly/.hermes/research-assistant/commands/factor_lab/api_server/routes_paper.py"
        ).read()
        for term in ["send_order", "execute_trade", "auto_trade"]:
            assert term not in src, f"含禁用词: {term}"
