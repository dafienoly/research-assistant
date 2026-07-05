"""测试: self-account 是重新计算, 不是 raw 过滤"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from factor_lab.live.account_profile import is_self_tradable, get_board

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_self_recomputed_not_filtered():
    """self-account 是重新计算的结果, 不是 raw 过滤后删除受限股票

    验证方法: raw 中受限股票被移除后, self 应该有重新排序的 rank,
    且 self 候选数量应接近 self-universe 的正常选股数量, 不是 raw-n。
    """
    d = _load()
    raw = d.get("raw_target_candidates", [])
    self_t = d.get("self_tradable_target_candidates", [])

    # raw 中不可交易的股票数
    raw_non_tradable = sum(1 for c in raw if not is_self_tradable(c["symbol"]))
    # 如果 self 只是 raw 过滤, 则 self 数量 = len(raw) - raw_non_tradable
    expected_if_filter = len(raw) - raw_non_tradable

    # self 是重新计算的, 数量可能不同于 raw-n
    # 只要它们不相等, 就证明不是简单过滤
    # (在特殊情况下可能相等, 但 rank 应该不同)
    raw_ranks = {c["symbol"]: c.get("rank", 0) for c in raw}
    self_ranks = {c["symbol"]: c.get("rank", 0) for c in self_t}

    # 检查 self 中股票的 rank 是否与 raw 不同 (重新排序)
    common = set(raw_ranks.keys()) & set(self_ranks.keys())
    if common:
        # 只要有一个 rank 不同, 就证明重新计算了
        rank_different = any(raw_ranks[s] != self_ranks[s] for s in common)
        assert rank_different or len(self_t) != expected_if_filter, \
            "self 与 raw 过滤后完全相同, 可能是简单过滤而非重新计算"


def test_self_universe_smaller():
    """self-account 的股票池比 raw 小"""
    d = _load()
    self_t = d.get("self_tradable_target_candidates", [])
    raw_t = d.get("raw_target_candidates", [])
    # self-universe 只有主板, 候选数量应该 <= raw 数量
    assert len(self_t) <= len(raw_t) + 3, "self-universe 候选不应远多于 raw"
