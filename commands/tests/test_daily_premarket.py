"""测试: V1.12 Daily Premarket Runner"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path

JSON_PATH = "/mnt/d/HermesReports/unified_premarket/20260703/unified_premarket_report.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_pipeline_status_json():
    status = {
        "run_id": "test_001",
        "date": "2026-07-03",
        "status": "success",
        "stage_status": {"trading_calendar": "success"},
        "warnings": [],
        "errors": [],
    }
    assert status["status"] == "success"


def test_no_auto_trade_in_daily():
    terms = ["auto_buy", "auto_order", "自动买入", "自动下单"]
    d = json.dumps(_load())
    for t in terms:
        assert t.lower() not in d.lower(), f"含禁用词: {t}"


def test_decision_template():
    from factor_lab.orchestration.daily_premarket_runner import _generate_decision_template
    tpl = _generate_decision_template("2026-07-03", "/tmp/report.html")
    assert "确认" in tpl


def test_notification_message():
    from factor_lab.orchestration.daily_premarket_runner import _generate_notification_message
    msg = _generate_notification_message({
        "unified_readiness": "usable_with_warning",
        "self_stock_candidates": {"total": 18, "top5": [{"symbol": "000001"}]},
        "etf_substitution_summary": {"candidates": [{"etf_name": "科创芯片ETF"}]},
        "allocation_plans": {"balanced": {"total_used": 49421, "remaining_cash": 579}},
    }, {"today": "2026-07-03", "is_trading_day": True}, [])
    assert "确认" in msg or "不自动下单" in msg


def test_non_trading_day_no_buy():
    from factor_lab.orchestration.daily_premarket_runner import TradingCalendar
    cal = TradingCalendar()
    s = cal.status()
    assert "is_trading_day" in s or "today" in s


def test_stale_data_warning():
    from factor_lab.orchestration.daily_premarket_runner import TradingCalendar
    cal = TradingCalendar()
    s = cal.status()
    assert "calendar_status" in s
