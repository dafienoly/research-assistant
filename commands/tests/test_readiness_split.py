"""测试: readiness 拆分为四个字段"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"

REQUIRED = [
    "strategy_signal_readiness",
    "self_account_readiness",
    "restricted_signal_readiness",
    "etf_substitution_readiness",
]


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_readiness_has_four_fields():
    """readiness 包含四个拆分字段"""
    d = _load()
    r = d.get("readiness", {})
    for field in REQUIRED:
        assert field in r, f"readiness 缺少 {field}"


def test_no_old_live_readiness():
    """不存在旧的单一 live_readiness 字段"""
    d = _load()
    assert "live_readiness" not in d, "应移除旧字段 live_readiness"


def test_readiness_valid_values():
    """readiness 字段值合法"""
    d = _load()
    r = d.get("readiness", {})
    valid = {"ready", "partial", "not_ready", "no_signal", "framework_ready", "no_trigger"}
    for field in REQUIRED:
        val = r.get(field, "")
        assert val in valid or val == "?", f"{field}={val} 非法"
