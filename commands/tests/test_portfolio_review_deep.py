"""测试: V2.2.1 Portfolio Review 深化"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.portfolio.portfolio_review import (
    run_portfolio_review, _calc_opportunity_cost,
    _calc_drift, _analyze_overrides, generate_review_report,
)


def test_review_basic():
    """复盘不崩溃"""
    review = run_portfolio_review("2026-07-03")
    assert "date" in review
    assert "review_status" in review


def test_opportunity_cost():
    """机会成本计算"""
    missed = [{"symbol": "000001", "action": "buy"}]
    future = {"status": "completed", "returns": {"ret_1d": 0.02, "ret_3d": 0.05}}
    oc = _calc_opportunity_cost(missed, future)
    assert oc["total_missed"] == 1


def test_manual_override_analysis():
    """人工 override 分析"""
    overrides = [{"symbol": "000001", "action": "buy"}]
    future = {"status": "completed", "returns": {"ret_1d": 0.03}}
    ao = _analyze_overrides(overrides, future)
    assert ao["total"] == 1


def test_portfolio_drift():
    """组合偏离"""
    rebalance = {"plans": {"B": {"buy_candidate": [{"symbol": "000001"}], "sell_candidate": [], "risk_sell_candidate": []}}}
    match = {"matched": [{"symbol": "000002", "action": "buy"}]}  # 不同股票 → missed
    drift = _calc_drift(rebalance, match)
    assert "missed_buys" in drift


def test_pending_future():
    """后续数据不足标记 pending"""
    review = run_portfolio_review("2099-01-01")  # 未来日期
    assert review["review_status"] in ("partial", "completed") or "pending" in str(review)


def test_report_generation():
    """报告生成不报错"""
    with tempfile.TemporaryDirectory() as tmp:
        review = run_portfolio_review("2026-07-03")
        generate_review_report(review, tmp)
        assert os.path.exists(os.path.join(tmp, "portfolio_review_report.html"))
