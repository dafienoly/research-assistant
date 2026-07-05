"""测试: V2.7 Paper Dashboard"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.paper.paper_dashboard import build_dashboard, generate_dashboard_report


def test_dashboard_no_data():
    """无 paper 数据返回 no_data"""
    result = build_dashboard("2099-01-01", "2099-01-05")
    assert result["status"] == "no_data"


def test_dashboard_loads():
    """从真实 paper_trading 加载 (可能没有数据)"""
    result = build_dashboard("2026-07-01", "2026-07-31")
    assert "status" in result


def test_rolling_metrics():
    """滚动指标不崩溃"""
    result = build_dashboard("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        assert "paper_sharpe" in result


def test_execution_quality():
    """执行质量指标"""
    result = build_dashboard("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        assert "execution_quality" in result


def test_report_generation():
    """报告生成不报错"""
    with tempfile.TemporaryDirectory() as tmp:
        result = build_dashboard("2026-07-01", "2026-07-31")
        if "n_trading_days" not in result:
            result["n_trading_days"] = 0
        generate_dashboard_report(result, tmp)
        assert os.path.exists(os.path.join(tmp, "paper_dashboard_report.html"))


def test_no_real_trade():
    """dashboard 不调用交易方法"""
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/paper/paper_dashboard.py").read()
    for term in ["send_order", "place_order", "execute_trade", "auto_trade"]:
        assert term not in src, f"含禁用词: {term}"
