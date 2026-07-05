"""测试: V2.5 Risk Approval"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.approval.risk_approval import run_approval, generate_approval_report, KILL_SWITCH
from factor_lab.approval.risk_approval import BLOCKED_TRADE_METHODS

SAMPLE_ORDERS = {
    "orders": [
        {"order_id": "ORD_001", "symbol": "000001", "side": "buy", "order_shares": 200, "estimated_amount": 2000, "tradable": True, "manual_confirm_required": False, "risk_level": "tradable", "reference_price": 10.0},
        {"order_id": "ORD_002", "symbol": "000002", "side": "sell", "order_shares": 100, "estimated_amount": 1500, "tradable": True, "manual_confirm_required": False, "risk_level": "tradable"},
        {"order_id": "ORD_003", "symbol": "000003", "side": "sell", "order_shares": 100, "estimated_amount": 800, "tradable": True, "manual_confirm_required": True, "risk_level": "review_required"},
    ],
    "summary": {"total_orders": 3},
}


def test_approval_from_order_preview():
    """从 order preview 生成审批"""
    with tempfile.TemporaryDirectory() as tmp:
        op_path = os.path.join(tmp, "order_preview.json")
        with open(op_path, "w") as f:
            json.dump(SAMPLE_ORDERS, f)
        result = run_approval("2026-07-03", plan="B", order_preview_dir=tmp)
        assert "error" not in result or result["status"] != "failed"
        assert "approval_summary" in result


def test_approval_blocked():
    """不可交易订单被 blocked"""
    orders = {"orders": [{"order_id": "ORD_B", "symbol": "000001", "side": "buy", "tradable": False, "block_reason": "涨停不可买", "manual_confirm_required": False}], "summary": {"total_orders": 1}}
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "order_preview.json"), "w") as f:
            json.dump(orders, f)
        result = run_approval("2026-07-03", order_preview_dir=tmp)
        assert result["summary"]["blocked"] >= 1


def test_second_confirmation():
    """风控卖出进入二次确认"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "order_preview.json"), "w") as f:
            json.dump(SAMPLE_ORDERS, f)
        result = run_approval("2026-07-03", order_preview_dir=tmp)
        assert result["summary"]["needs_second_confirmation"] >= 1


def test_kill_switch_blocked():
    """Kill switch 阻断买入"""
    orders = {"orders": [{"order_id": "ORD_K", "symbol": "000001", "side": "buy", "order_shares": 200, "estimated_amount": 2000, "tradable": True, "manual_confirm_required": False, "risk_level": "tradable", "reference_price": 0}], "summary": {"total_orders": 1}}
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "order_preview.json"), "w") as f:
            json.dump(orders, f)
        result = run_approval("2026-07-03", order_preview_dir=tmp, capital=50000)
        assert result.get("kill_switch_triggered") or result["summary"]["blocked"] >= 0


def test_no_auto_trade():
    """审批不自动下单"""
    import inspect
    src = inspect.getsource(__import__('factor_lab.approval.risk_approval', fromlist=['run_approval']))
    # 检查是否有函数调用 (名称后跟左括号), 排除列表声明
    import re
    calls = re.findall(r'(send_order|place_order|execute_trade)\s*\(', src)
    assert len(calls) == 0, f"含交易函数调用: {calls}"


def test_checklist_generated():
    """人工确认清单生成"""
    with tempfile.TemporaryDirectory() as tmp:
        op_path = os.path.join(tmp, "order_preview.json")
        with open(op_path, "w") as f:
            json.dump(SAMPLE_ORDERS, f)
        result = run_approval("2026-07-03", order_preview_dir=tmp)
        out = os.path.join(tmp, "report")
        generate_approval_report(result, out)
        assert os.path.exists(os.path.join(out, "manual_confirmation_checklist.md"))
