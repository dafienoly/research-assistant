"""测试: restricted_board_candidates 输出完整性"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.live.account_profile import get_board, is_self_tradable

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"

VALID_PATHS = {"etf_substitution_candidate", "manual_compliance_review", "watch_only"}


def _load():
    with open(JSON_PATH) as f:
        return json.load(f)


def test_restricted_contains_all_boards():
    """restricted 包含所有权限受限的板块"""
    d = _load()
    restricted = d.get("restricted_board_candidates", [])
    assert len(restricted) > 0, "应有权限受限股票"
    boards = {r["board"] for r in restricted}
    # 至少应有创业板或科创板
    assert "创业板" in boards or "科创板" in boards, f"预期含创业板/科创板, 实际 {boards}"


def test_restricted_required_fields():
    """restricted 条目包含所有必需字段"""
    d = _load()
    restricted = d.get("restricted_board_candidates", [])
    for r in restricted:
        assert "symbol" in r
        assert "board" in r
        assert "original_rank" in r
        assert "ret5" in r
        assert "reason" in r, f"{r.get('symbol','?')} 缺少 reason"
        assert "suggested_path" in r, f"{r.get('symbol','?')} 缺少 suggested_path"


def test_restricted_suggested_path_valid():
    """suggested_path 只能是允许的路径"""
    d = _load()
    restricted = d.get("restricted_board_candidates", [])
    for r in restricted:
        assert r["suggested_path"] in VALID_PATHS, \
            f"{r['symbol']}: 非法路径 {r['suggested_path']}"


def test_restricted_not_in_self():
    """restricted 中的股票不应出现在 self_tradable"""
    d = _load()
    restricted = {c["symbol"] for c in d.get("restricted_board_candidates", [])}
    self_t = {c["symbol"] for c in d.get("self_tradable_target_candidates", [])}
    overlap = restricted & self_t
    assert len(overlap) == 0, f"restricted 出现在 self: {overlap}"
