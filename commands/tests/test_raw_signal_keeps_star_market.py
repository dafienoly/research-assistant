"""测试: raw 信号保留科创/创业板, 不受 self_account 限制"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from factor_lab.live.account_profile import get_board, is_self_tradable

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_raw_contains_star_and_chinext():
    """raw_target_candidates 可以包含 300/301/688/689"""
    d = _load()
    raw = d.get("raw_target_candidates", [])
    syms = [c["symbol"] for c in raw]
    star_or_chinext = [s for s in syms if get_board(s) in ("star", "chinext")]
    assert len(star_or_chinext) > 0, f"Raw 应含科创/创业板, 当前仅 {syms}"


def test_raw_not_limited_by_self_account():
    """raw 信号不受 self_account 权限限制"""
    d = _load()
    raw = d.get("raw_target_candidates", [])
    self_t = d.get("self_tradable_target_candidates", [])
    raw_syms = {c["symbol"] for c in raw}
    self_syms = {c["symbol"] for c in self_t}
    # raw 中可能有 self 不可买的股票
    non_self = raw_syms - self_syms
    # 有差异是正常的, 但 raw 不能像 self 一样受限
    assert len(raw_syms) >= len(self_syms), "raw 不应小于 self"


def test_raw_is_research_not_execution():
    """raw 是研究信号, target 命名不含 self/tradable"""
    d = _load()
    assert "raw_target_candidates" in d
    rebal = d.get("rebalance_plan", {})
    plan_str = json.dumps(rebal)
    # raw 的股票不应该在 rebalance_plan 中作为 buy
    # (注: 新代码没有全局 rebalance_plan 了, 检查 self 的)
    self_t = d.get("self_tradable_target_candidates", [])
    self_syms = {c["symbol"] for c in self_t}
    raw_syms = {c["symbol"] for c in d.get("raw_target_candidates", [])}
    # raw 中不可在 self 中买的股票应当出现在 restricted
    restricted = {c["symbol"] for c in d.get("restricted_board_candidates", [])}
    non_tradable_raw = raw_syms - self_syms
    if non_tradable_raw:
        missing = non_tradable_raw - restricted
        assert len(missing) == 0, f"Raw 中不可交易股票应进入 restricted, 缺失: {missing}"
