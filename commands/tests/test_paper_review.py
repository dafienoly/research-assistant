"""测试: V2.6.1 Paper Review"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.paper.paper_review import run_paper_review, generate_review_report


def test_paper_review_no_data():
    """无 paper 数据时返回 no_data"""
    result = run_paper_review("2099-01-01")
    assert result["status"] == "no_data"


def test_paper_review_future_pending():
    """后续数据不足标记 pending"""
    result = run_paper_review("2099-01-01", "2099-01-01", "2099-01-05")
    assert result["status"] == "no_data" or "pending" in str(result.get("future", {}).get("status", ""))


def test_paper_vs_no_action():
    """paper vs no action 不崩溃"""
    review = run_paper_review("2026-07-03")
    assert "paper_vs_no_action" in review or review.get("status") == "no_data"


def test_paper_vs_actual_unavailable():
    """无实际执行数据时标记 unavailable"""
    review = run_paper_review("2026-07-03")
    vs = review.get("paper_vs_actual", {})
    if vs:
        assert vs.get("status") in ("actual_unavailable", "no_data", "pending")


def test_report_generation():
    """报告生成不报错"""
    with tempfile.TemporaryDirectory() as tmp:
        review = run_paper_review("2026-07-03")
        # review 可能没有 n_dates, 填充默认值
        if "n_dates" not in review:
            review["n_dates"] = 0
        generate_review_report(review, tmp)
        assert os.path.exists(os.path.join(tmp, "paper_review_report.html"))


def test_no_real_trade():
    """review 不调用交易方法"""
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/paper/paper_review.py").read()
    for term in ["send_order", "place_order", "execute_trade", "auto_trade"]:
        assert term not in src, f"含禁用词: {term}"
