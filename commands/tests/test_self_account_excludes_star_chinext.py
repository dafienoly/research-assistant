"""测试: self-account 排除科创/创业板"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.live.account_profile import get_board, is_self_tradable

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_self_no_chinext():
    """self_tradable_target_candidates 不包含 300/301"""
    d = _load()
    self_t = d.get("self_tradable_target_candidates", [])
    for c in self_t:
        sym = c["symbol"]
        assert not sym.startswith(("300", "301")), f"创业板 {sym} 不应在 self 候选"


def test_self_no_star():
    """self_tradable_target_candidates 不包含 688/689"""
    d = _load()
    self_t = d.get("self_tradable_target_candidates", [])
    for c in self_t:
        sym = c["symbol"]
        assert not sym.startswith(("688", "689")), f"科创板 {sym} 不应在 self 候选"


def test_self_only_main_board():
    """self-account 只允许主板代码"""
    d = _load()
    self_t = d.get("self_tradable_target_candidates", [])
    for c in self_t:
        sym = c["symbol"]
        board = get_board(sym)
        assert board == "main", f"{sym} 板块={board}, 仅预期 main"


def test_self_symbols_all_tradable():
    """self 候选所有 symbol 均可交易"""
    d = _load()
    self_t = d.get("self_tradable_target_candidates", [])
    for c in self_t:
        assert is_self_tradable(c["symbol"]), f"{c['symbol']} 不可交易"
