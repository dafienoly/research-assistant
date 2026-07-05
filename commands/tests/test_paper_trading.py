"""测试: V2.6 Paper Trading"""
import sys, os, json, tempfile, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.paper.paper_trading import run_paper_trade, generate_paper_report

APPROVED_CSV = """order_id,symbol,side,order_shares,limit_price,reference_price
ORD_001,000001,buy,200,10.05,10.00
ORD_002,000002,sell,100,14.95,15.00
ORD_003,000003,buy,500,20.10,20.00
"""


def test_paper_execution():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "approved_orders.csv"), "w") as f:
            f.write(APPROVED_CSV)
        result = run_paper_trade("2026-07-03", plan="B", approval_dir=tmp)
        assert "fills" in result and len(result["fills"]) > 0


def test_fill_status():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "approved_orders.csv"), "w") as f:
            f.write(APPROVED_CSV)
        result = run_paper_trade("2026-07-03", approval_dir=tmp)
        statuses = [f["paper_status"] for f in result["fills"]]
        assert all(s in ("filled", "partial_filled", "blocked", "pending") for s in statuses)


def test_cash_update():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "approved_orders.csv"), "w") as f:
            f.write(APPROVED_CSV)
        result = run_paper_trade("2026-07-03", approval_dir=tmp)
        assert result["account_after"]["cash"] >= 0


def test_blocked_insufficient_cash():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "approved_orders.csv"), "w") as f:
            f.write("order_id,symbol,side,order_shares,limit_price,reference_price\nORD_B,000001,buy,100000,100.00,100.00\n")
        result = run_paper_trade("2026-07-03", approval_dir=tmp)
        statuses = {f["paper_status"] for f in result["fills"]}
        assert "blocked" in statuses or "partial_filled" in statuses


def test_no_real_trade():
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/paper/paper_trading.py").read()
    for term in ["send_order", "place_order", "execute_trade", "auto_trade"]:
        assert term not in src, f"含禁用词: {term}"


def test_report_generation():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "approved_orders.csv"), "w") as f:
            f.write(APPROVED_CSV)
        result = run_paper_trade("2026-07-03", approval_dir=tmp)
        out = os.path.join(tmp, "report")
        generate_paper_report(result, out)
        assert os.path.exists(os.path.join(out, "paper_trading_report.html"))
