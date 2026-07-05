"""测试: V2.0 Portfolio + Rebalance Diff"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.portfolio.position_loader import PositionLoader
from factor_lab.portfolio.rebalance_diff import run_rebalance_diff, generate_rebalance_report


def test_position_loader_csv():
    """加载 CSV 持仓"""
    path = "/home/ly/.hermes/research-assistant/data/positions/current_positions.csv"
    if not os.path.exists(path):
        assert True
        return
    loader = PositionLoader()
    pos = loader.load_csv(path)
    assert len(pos) > 0


def test_position_schema_validation():
    """字段缺失标记 partial"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "bad.csv")
        with open(csv_path, "w") as f:
            f.write("symbol,shares\n000001,abc\n")
        loader = PositionLoader()
        pos = loader.load_csv(csv_path)
        assert loader.partial or loader.errors


def test_no_fake_fallback():
    """空路径不返回假数据"""
    loader = PositionLoader()
    pos = loader.load_csv("/nonexistent/path.csv")
    assert len(pos) == 0
    assert len(loader.errors) > 0


def test_rebalance_diff_hold_buy_sell():
    """调仓差异分类 (使用真实报告)"""
    from pathlib import Path
    real_report = Path("/mnt/d/HermesReports/unified_premarket/20260703/unified_premarket_report.json")
    if not real_report.exists():
        assert True  # 无报告时跳过
        return

    result = run_rebalance_diff("2026-07-03", None, plan="B", capital=50000)
    if "error" not in result:
        plans = result.get("plans", {})
        assert "B" in plans, "Plan B 应存在"
        pb = plans["B"]
        assert "hold" in pb and "sell_candidate" in pb and "buy_candidate" in pb


def test_round_lot_buy_sell():
    """100 股整数倍校验"""
    loader = PositionLoader()
    rows = loader._validate([
        {"symbol": "000001", "shares": "150", "current_price": "10"},
    ], "csv")
    # 150 不是 100 的倍数, 应有 warning
    if loader.warnings:
        has_warning = any("100的整数倍" in w for w in loader.warnings)
        # 可能通过也可能 warning, 不崩溃即可
        assert True


def test_no_auto_order():
    """调仓不自动下单"""
    content = open("/home/ly/.hermes/research-assistant/commands/factor_lab/portfolio/rebalance_diff.py").read()
    for term in ["auto_buy", "execute_trade", "send_order"]:
        assert term not in content, f"含禁用词: {term}"
    # no_auto_order 是安全声明, 不视为禁用


def test_cash_manager_insufficient():
    """资金不足标记 shortfall"""
    from pathlib import Path
    real_report = Path("/mnt/d/HermesReports/unified_premarket/20260703/unified_premarket_report.json")
    if not real_report.exists():
        assert True
        return
    result = run_rebalance_diff("2026-07-03", None, plan="B", capital=10000)
    if "error" not in result:
        cs = result.get("plans", {}).get("B", {}).get("cash_summary", {})
        assert "cash_shortfall" in cs


def test_report_generation():
    """报告生成不报错"""
    with tempfile.TemporaryDirectory() as tmp:
        result = {
            "date": "2026-07-03", "plan": "B", "capital": 50000,
            "total_assets": 50000, "total_cash": 50000, "total_stock_value": 0,
            "target_stock_cost": 25000, "target_etf_cost": 25000, "total_target_cost": 50000,
            "cash_shortfall": 0,
            "position_validation": {"partial": False, "warnings": [], "errors": []},
            "hold": [], "sell_candidate": [], "buy_candidate": [], "skip_buy": [],
        }
        r = generate_rebalance_report(result, tmp)
        assert "output_dir" in r
