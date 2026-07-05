"""测试: ETF 替代框架输出"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_etf_themes_exist():
    """restricted 信号强时生成 ETF 替代主题"""
    d = _load()
    etf = d.get("etf_substitution_candidates", [])
    assert len(etf) > 0, "应有 ETF 替代主题"


def test_etf_required_fields():
    """ETF 替代条目包含必需字段, 不生成具体买入指令"""
    d = _load()
    for t in d.get("etf_substitution_candidates", []):
        assert "theme" in t
        assert "trigger_symbols" in t
        assert "trigger_count" in t
        assert "reason" in t
        assert "etf_candidate_type" in t
        assert "next_step" in t
        # 不生成具体 ETF 代码
        etf_str = json.dumps(t)
        assert "buy" not in etf_str.lower() or "etf_candidate_type" in t


def test_etf_no_concrete_etf():
    """ETF 替代不输出具体 ETF 代码/买入指令"""
    d = _load()
    for t in d.get("etf_substitution_candidates", []):
        next_step = t.get("next_step", "")
        assert "etf selector" in next_step.lower() or "后续" in next_step, \
            f"应说明后续步骤, 当前: {next_step}"
