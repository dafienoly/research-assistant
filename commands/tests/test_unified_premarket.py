"""测试: V1.11 Unified Premarket Report"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.live.unified_premarket_report import (
    _unified_readiness, _build_plans, _generate_summary, _build_excluded, main
)

JSON_PATH = "/mnt/d/HermesReports/unified_premarket/20260703/unified_premarket_report.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_unified_readiness():
    r = _unified_readiness({"strategy_signal_readiness": "ready",
                            "self_account_readiness": "ready"}, {})
    assert r == "usable_with_warning", f"预期 usable_with_warning, 实际 {r}"


def test_readiness_aggregator():
    r = _unified_readiness({"strategy_signal_readiness": "ready",
                            "self_account_readiness": "ready"},
                           {"data_status": "ok"})
    assert r == "ready", f"预期 ready, 实际 {r}"


def test_plan_a_b_c_generated():
    d = _load()
    for name in ("conservative", "balanced", "aggressive"):
        assert name in d.get("allocation_plans", {}), f"缺少方案 {name}"


def test_plan_round_lot():
    """资金计划使用 100 股整数倍"""
    d = _load()
    for pname in ("conservative", "balanced", "aggressive"):
        plan = d.get("allocation_plans", {}).get(pname, {})
        for lot in plan.get("self_stock_lots", []):
            assert lot["shares"] % 100 == 0, f"{pname} {lot['symbol']} 不是100的倍数"


def test_restricted_not_direct_buy():
    """受限股票不在 self 候选里"""
    d = _load()
    self_top5 = {c["symbol"] for c in d.get("self_stock_candidates", {}).get("top5", [])}
    excluded = {e["symbol"] for e in d.get("excluded", [])}
    assert len(self_top5 & excluded) == 0, "受限股票出现在 self 候选"


def test_no_borrowed_account():
    d = json.dumps(_load())
    for term in ["借账户", "代买", "borrow_account", "buy_by_other_account"]:
        assert term not in d, f"含禁用词: {term}"


def test_no_auto_order():
    d = json.dumps(_load())
    for term in ["自动下单", "auto_buy", "auto_order"]:
        assert term not in d, f"含自动下单: {term}"


def test_etf_partial_data_warning():
    """ETF partial 数据有 warning"""
    d = _load()
    ur = d.get("unified_readiness", "")
    assert "warning" in ur or "partial" in ur, f"无数据警告, readiness={ur}"


def test_report_generation():
    """报告生成不报错"""
    from factor_lab.live.unified_premarket_report import _write_all
    d = _load()
    self_t = d.get("self_stock_candidates", {}).get("top8", [])
    etf_c = d.get("etf_substitution_summary", {}).get("candidates", [])
    with tempfile.TemporaryDirectory() as tmp:
        _write_all(tmp, d, self_t, etf_c)
        files = os.listdir(tmp)
        assert "unified_premarket_report.html" in files
        assert "unified_premarket_report.json" in files
        assert "self_stock_plan.csv" in files
        assert "readiness_summary.json" in files
        assert "audit.log" in files


def test_audit_log():
    d = _load()
    log_path = "/mnt/d/HermesReports/unified_premarket/20260703/audit.log"
    with open(log_path) as f:
        log = f.read()
    assert "UNIFIED PREMARKET AUDIT" in log
    assert "usable_with_warning" in log or "ready" in log
