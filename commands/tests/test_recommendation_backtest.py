"""测试: V2.9 Recommendation Backtest"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.adaptive.recommendation_backtest import run_recommendation_backtest, generate_backtest_report


def test_backtest_no_data():
    result = run_recommendation_backtest("2099-01-01", "2099-01-05")
    assert result["status"] == "no_data"


def test_backtest_loads():
    result = run_recommendation_backtest("2026-07-01", "2026-07-31")
    assert "status" in result


def test_candidate_verdicts():
    result = run_recommendation_backtest("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        for c in result.get("candidates", []):
            assert c["verdict"] in ("accept_candidate", "reject_candidate", "watch_candidate", "insufficient_data")


def test_evidence_required():
    result = run_recommendation_backtest("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        for c in result.get("candidates", []):
            assert "evidence" in c and c["evidence"]


def test_no_auto_apply():
    result = run_recommendation_backtest("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        assert result.get("auto_apply") == False


def test_report_generation():
    with tempfile.TemporaryDirectory() as tmp:
        result = run_recommendation_backtest("2026-07-01", "2026-07-31")
        if result.get("status") == "no_data":
            return
        for key in ["candidates", "summary", "requires_human_approval"]:
            if key not in result:
                result[key] = [] if key in ("candidates",) else {} if key == "summary" else True
        generate_backtest_report(result, tmp)
        assert os.path.exists(os.path.join(tmp, "recommendation_backtest_report.html"))
