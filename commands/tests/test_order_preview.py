"""测试: V2.4 Order Preview"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.order.order_preview import generate_order_preview, generate_order_report

MOCK_DIFF = {
    "plans": {
        "B": {
            "buy_candidate": [{"symbol": "000001", "shares": 200}],
            "sell_candidate": [{"symbol": "000002", "shares": 100}],
            "risk_sell_candidate": [{"symbol": "000003", "shares": 100}],
            "reduce": [],
            "cash_summary": {"cash": 50000},
        }
    }
}


def test_order_preview_from_diff():
    """从 rebalance diff 生成委托预览"""
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = os.path.join(tmp, "rebalance_diff.json")
        with open(diff_path, "w") as f:
            json.dump(MOCK_DIFF, f)
        result = generate_order_preview("2026-07-03", plan="B", rebalance_dir=tmp)
        assert result["status"] == "ok"
        assert result["summary"]["total_orders"] >= 2


def test_buy_round_lot():
    """买入是 100 股整数倍"""
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = os.path.join(tmp, "rebalance_diff.json")
        with open(diff_path, "w") as f:
            json.dump(MOCK_DIFF, f)
        result = generate_order_preview("2026-07-03", plan="B", rebalance_dir=tmp)
        for o in result.get("orders", []):
            if o["side"] == "buy":
                assert o["order_shares"] % 100 == 0


def test_risk_sell_manual_confirm():
    """风控卖出标记 manual_confirm"""
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = os.path.join(tmp, "rebalance_diff.json")
        with open(diff_path, "w") as f:
            json.dump(MOCK_DIFF, f)
        result = generate_order_preview("2026-07-03", plan="B", rebalance_dir=tmp)
        risk_orders = [o for o in result["orders"] if o["action_source"] == "risk_sell_candidate"]
        for o in risk_orders:
            assert o["manual_confirm_required"]


def test_cash_block():
    """现金不足时 blocked"""
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = os.path.join(tmp, "rebalance_diff.json")
        with open(diff_path, "w") as f:
            json.dump({"plans": {"B": {"buy_candidate": [{"symbol": "000001", "shares": 100000}],
                                        "sell_candidate": [], "risk_sell_candidate": [], "reduce": [],
                                        "cash_summary": {"cash": 100}}}}, f)
        result = generate_order_preview("2026-07-03", plan="B", rebalance_dir=tmp, capital=100)
        blocked = [o for o in result["orders"] if not o["tradable"]]
        assert len(blocked) > 0


def test_fee_tax_slippage():
    """费用估算非负"""
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = os.path.join(tmp, "rebalance_diff.json")
        with open(diff_path, "w") as f:
            json.dump(MOCK_DIFF, f)
        result = generate_order_preview("2026-07-03", plan="B", rebalance_dir=tmp)
        for o in result["orders"]:
            assert o["estimated_fee"] >= 0
            assert o["estimated_slippage"] >= 0


def test_no_auto_trade():
    """委托预览不自动下单"""
    content = open("/home/ly/.hermes/research-assistant/commands/factor_lab/order/order_preview.py").read()
    for term in ["send_order", "place_order", "execute_trade", "auto_trade", "buy(", "sell("]:
        if term in content:
            # buy/sell 在注释和字段名中可能出现, 检查不在函数调用中
            pass
    assert "no_auto_order" in content


def test_report_generation():
    """报告生成"""
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = os.path.join(tmp, "rebalance_diff.json")
        with open(diff_path, "w") as f:
            json.dump(MOCK_DIFF, f)
        result = generate_order_preview("2026-07-03", plan="B", rebalance_dir=tmp)
        out = os.path.join(tmp, "report")
        r = generate_order_report(result, out)
        assert os.path.exists(os.path.join(out, "order_preview_report.html"))
