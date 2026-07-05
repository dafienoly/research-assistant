"""测试: ETF 选择器 + 评分 + 流动性 + 主题匹配"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.etf.etf_selector import run_etf_selector

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _get_restricted():
    with open(JSON_PATH) as f:
        return json.load(f).get("restricted_board_candidates", [])


def test_selector_from_restricted():
    r = _get_restricted()
    result = run_etf_selector(r)
    assert len(result["candidates"]) >= 1, "至少 1 个 ETF 候选"
    assert len(result["themes"]) >= 1, "至少 1 个主题"
    assert result["data_status"] in ("ok", "partial"), "data_status 有效"


def test_selector_fields():
    r = _get_restricted()
    result = run_etf_selector(r)
    for c in result["candidates"]:
        assert "score" in c
        assert "etf_code" in c
        assert "etf_name" in c


def test_selector_no_auto_order():
    r = _get_restricted()
    result = run_etf_selector(r)
    plan = result.get("capital_plan", {})
    assert "不自动执行" in plan.get("note", "") or "参考" in plan.get("note", ""), "无自动下单"


def test_score_liquidity_penalty():
    """低流动性 ETF 分数较低"""
    from factor_lab.etf.etf_selector import _score_etf
    score_high = _score_etf({"avg_amount_20d": "50000", "aum": "100", "expense_ratio": "0.15", "theme": "科创芯片", "holdings_available": "false"}, [], 50000, 100, 0.15)
    score_low = _score_etf({"avg_amount_20d": "1000", "aum": "2", "expense_ratio": "0.50", "theme": "未知", "holdings_available": "false"}, [], 1000, 2, 0.50)
    assert score_high["total"] > score_low["total"], "高流动性应得分更高"


def test_score_theme_match():
    """主题匹配 ETF 得分更高"""
    from factor_lab.etf.etf_selector import _score_etf
    matched = _score_etf({"theme": "科创芯片", "avg_amount_20d": "20000", "aum": "50", "expense_ratio": "0.50", "holdings_available": "false"}, [], 20000, 50, 0.50)
    unknown = _score_etf({"theme": "未知", "avg_amount_20d": "20000", "aum": "50", "expense_ratio": "0.50", "holdings_available": "false"}, [], 20000, 50, 0.50)
    assert matched["total"] > unknown["total"], "主题匹配应得分更高"
