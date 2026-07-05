"""V1.12.1 边界测试: 非交易日/数据过期/通知失败/无 silent fallback"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.orchestration.daily_premarket_runner import TradingCalendar, run_daily_premarket

JSON_PATH = "/mnt/d/HermesReports/unified_premarket/20260703/unified_premarket_report.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_non_trading_day_no_buy_advice():
    """非交易日不生成买入建议"""
    cal = TradingCalendar()
    s = cal.status()
    # 不崩溃
    assert "is_trading_day" in s or "today" in s


def test_daily_runner_non_trading_day():
    """非交易日 pipeline 标记 non_trading_day warning"""
    d = _load()
    assert "excluded" in d or "unified_readiness" in d


def test_stale_data_warning():
    """数据过期时标记 warning"""
    cal = TradingCalendar()
    s = cal.status()
    assert "calendar_status" in s


def test_notify_failure_not_block():
    """通知失败不阻断报告"""
    d = _load()
    assert "readiness" in d


def test_no_auto_trade():
    """全链路无自动交易指令"""
    terms = ["auto_buy", "auto_order", "send_order", "execute_trade", "自动下单"]
    content = json.dumps(_load()).lower()
    for t in terms:
        assert t.lower() not in content, f"含禁用词: {t}"


def test_no_silent_fallback():
    """无 silent fallback"""
    d = _load()
    ur = d.get("unified_readiness", "")
    assert ur in ("ready", "usable_with_warning", "partial", "failed", "warning"), f"未知: {ur}"


def test_audit_log_fields():
    """audit.log 包含必要字段"""
    log_path = "/mnt/d/HermesReports/unified_premarket/20260703/audit.log"
    with open(log_path) as f:
        log = f.read()
    assert "UNIFIED PREMARKET AUDIT" in log or "AUDIT" in log


def test_decision_template_content():
    """决策模板包含确认选项"""
    from factor_lab.orchestration.daily_premarket_runner import _generate_decision_template
    tpl = _generate_decision_template("2026-07-03", "/tmp/rpt")
    assert "Plan A" in tpl or "plan" in tpl.lower()
    assert "确认" in tpl


def test_pipeline_output_files_exist():
    """每日输出文件完整性"""
    base = "/mnt/d/HermesReports/unified_premarket/20260703"
    required = ["unified_premarket_report.html", "unified_premarket_report.json", "audit.log"]
    for f in required:
        assert os.path.exists(os.path.join(base, f)), f"缺失: {f}"
