"""测试: restricted 不进入 rebalance plan"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_restricted_not_in_self_plan():
    """self_tradable_target 不含 restricted 股票"""
    d = _load()
    restricted = {c["symbol"] for c in d.get("restricted_board_candidates", [])}
    self_t = {c["symbol"] for c in d.get("self_tradable_target_candidates", [])}
    assert restricted.isdisjoint(self_t), "restricted 出现在 self 候选"


def test_self_plan_only_main():
    """self 资金计划不含受限板块"""
    d = _load()
    cp = d.get("capital_plan", {})
    for lot in cp.get("lots", []):
        sym = lot.get("symbol", "")
        assert not sym.startswith(("300", "301", "688", "689")), f"资金计划含受限: {sym}"
