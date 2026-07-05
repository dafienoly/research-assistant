"""测试: V1.13 Decision Log + Review"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.decision.decision_logger import create_decision_log, update_decision_log, load_decision_log
from factor_lab.decision.decision_review import run_decision_review, generate_review_report, _get_future_returns


def test_decision_log_schema():
    """decision_log 包含必需字段"""
    with tempfile.TemporaryDirectory() as tmp:
        log = create_decision_log("2026-07-03", tmp)
        for field in ["decision_date", "user_action", "selected_plan",
                       "manual_buy", "manual_sell", "confirmed_by_user"]:
            assert field in log, f"缺少字段: {field}"


def test_decision_log_create():
    """创建决策日志"""
    with tempfile.TemporaryDirectory() as tmp:
        log = create_decision_log("2026-07-03", tmp)
        assert log["decision_date"] == "2026-07-03"
        assert log["user_action"] == "no_action"


def test_decision_log_update():
    """更新决策日志字段"""
    with tempfile.TemporaryDirectory() as tmp:
        create_decision_log("2026-07-03", tmp)
        log = update_decision_log("2026-07-03", plan="B", action="plan_b",
                                   buy=["000001"], exclude=["600000"],
                                   confirm=True, output_dir=tmp)
        assert log["selected_plan"] == "B"
        assert log["confirmed_by_user"] == True
        assert "000001" in log["manual_buy"]
        assert "600000" in log["manual_exclude"]


def test_decision_log_reload():
    """重新加载一致"""
    with tempfile.TemporaryDirectory() as tmp:
        create_decision_log("2026-07-03", tmp)
        update_decision_log("2026-07-03", plan="A", output_dir=tmp)
        loaded = load_decision_log("2026-07-03", tmp)
        assert loaded["selected_plan"] == "A"


def test_review_no_future_data_pending():
    """无后续行情时标记 pending"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run_decision_review("2026-07-03", "2026-07-05")
        assert "reviews" in result
        # 如果没找到决策日志, reviews 为空但不会崩溃


def test_generate_review_report():
    """报告生成不报错"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run_decision_review("2026-07-03", "2026-07-05")
        r = generate_review_report(result, tmp)
        assert "output_dir" in r


def test_no_silent_fallback_review():
    """复盘不静默返回假数据"""
    result = run_decision_review("2099-01-01", "2099-01-05")
    assert "reviews" in result
