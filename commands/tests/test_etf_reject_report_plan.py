"""测试: ETF 淘汰 + 数据缺失 + 报告 + 资金计划"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.etf.etf_selector import run_etf_selector
from factor_lab.etf.etf_universe import load_etf_registry

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _get_restricted():
    with open(JSON_PATH) as f:
        return json.load(f).get("restricted_board_candidates", [])


def test_reject_low_liquidity():
    """低流动性应被过滤"""
    r = _get_restricted()
    result = run_etf_selector(r, min_amount_20d=999999)  # 极高阈值
    assert len(result["candidates"]) == 0, "高流动性阈值下应无候选"


def test_reject_missing_data_no_fallback():
    """空数据不静默返回假候选"""
    result = run_etf_selector([], capital=50000)
    assert len(result["candidates"]) == 0
    # 即使资金为 0 也不崩溃
    result2 = run_etf_selector([{"symbol": "000001", "board": "主板", "ret5": 0.1, "original_rank": 1}], capital=0)
    assert result2 is not None


def test_report_generation():
    """报告生成不报错"""
    from factor_lab.etf.etf_selector_cli import _write_reports, parse_args
    r = _get_restricted()
    result = run_etf_selector(r)
    registry = load_etf_registry()
    with tempfile.TemporaryDirectory() as tmp:
        _write_reports(tmp, result, registry, JSON_PATH)
        files = os.listdir(tmp)
        assert "etf_selector.json" in files
        assert "etf_selector_report.html" in files
        assert "etf_candidates.csv" in files


def test_substitution_plan_capital():
    """资金计划不超可用资金"""
    r = _get_restricted()
    result = run_etf_selector(r, capital=10000)
    plan = result.get("capital_plan", {})
    total = plan.get("total_allocated", 0)
    assert total <= 10000, f"分配{total}超资金10000"


def test_no_auto_order():
    """ETF 替代不生成自动下单指令"""
    forbidden = ["自动买入", "自动下单", "auto_buy", "auto_order"]
    r = _get_restricted()
    result = run_etf_selector(r)
    result_str = json.dumps(result)
    for term in forbidden:
        assert term.lower() not in result_str.lower(), f"含禁用词: {term}"


def test_etf_policy_config():
    """评分阈值配置化"""
    r = _get_restricted()
    # 不同阈值应产生不同结果
    strict = run_etf_selector(r, min_amount_20d=999999, min_aum=999)
    loose = run_etf_selector(r, min_amount_20d=0, min_aum=0)
    assert len(loose["candidates"]) >= len(strict["candidates"]), "宽松阈值应产更多候选"
