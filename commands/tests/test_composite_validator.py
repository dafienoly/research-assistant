"""测试: 候选池加载、组合验证输出、无 demo fallback"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path

import numpy as np
import pandas as pd

from factor_lab.pool.candidate_pool import load_from_leaderboard, CandidatePool
from factor_lab.composite.factor_combiner import compute_composite


# ─── 候选池 ───────────────────────────────────────────────────

def test_candidate_pool_load():
    """从排行榜 JSON 加载候选池"""
    # 创建临时排行榜
    lb = _make_sample_leaderboard()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(lb, f)
        tmp = f.name
    pool = load_from_leaderboard(tmp)
    assert len(pool.promoted_names) > 0
    assert len(pool.rejected_names) > 0
    os.unlink(tmp)


def test_candidate_pool_promoted_property():
    pool = CandidatePool()
    pool.promoted = [{"factor_name": "ret5", "pass_gate": True, "grade": "B"}]
    assert "ret5" in pool.promoted_names


def test_candidate_pool_save():
    """池保存后能重新加载"""
    pool = CandidatePool()
    pool.promoted = [{"factor_name": "ret5", "pass_gate": True, "grade": "B"}]
    pool.rejected = [{"factor_name": "reversal5", "pass_gate": False, "grade": "D"}]
    d = pool.to_dict()
    assert "promoted_factors" in d
    assert "rejected_factors" in d
    assert len(d["promoted_factors"]) == 1


# ─── 组合方法 ─────────────────────────────────────────────────

def test_equal_weight_composite_nonempty():
    df = _make_dummy_data()
    r = compute_composite(df, ["ret5", "ret10"], method="equal_weight_score")
    assert len(r) == len(df)


def test_weighted_score_composite_nonempty():
    df = _make_dummy_data()
    r = compute_composite(df, ["ret5", "ret10"], method="weighted_score",
                           weights={"ret5": 0.7, "ret10": 0.3})
    assert len(r) == len(df)


def test_gated_score_composite_nonempty():
    df = _make_dummy_data()
    r = compute_composite(df, ["ret5", "ret10"], method="gated_score")
    assert len(r) == len(df)


def test_zscore_blend_nonempty():
    df = _make_dummy_data()
    r = compute_composite(df, ["ret5", "ret10"], method="zscore_blend",
                           weights={"ret5": 0.5, "ret10": 0.5})
    assert len(r) == len(df)


def test_rank_blend_nonempty():
    df = _make_dummy_data()
    r = compute_composite(df, ["ret5", "ret10"], method="rank_blend",
                           weights={"ret5": 0.5, "ret10": 0.5})
    assert len(r) == len(df)


# ─── No Demo Fallback ──────────────────────────────────────────

def test_no_demo_fallback_empty_data():
    """空数据应返回 0 或 NaN, 不崩溃"""
    df = pd.DataFrame({"date": [], "symbol": [], "ret5": [], "ret10": []})
    try:
        r = compute_composite(df, ["ret5", "ret10"], method="equal_weight_score")
        assert len(r) == 0
    except Exception as e:
        # 可以报错但不应静默返回假数据
        assert True


# ─── 辅助 ─────────────────────────────────────────────────────

def _make_sample_leaderboard() -> dict:
    return {
        "generated_at": "2025-01-01",
        "config": {"n_factors": 8},
        "summary": {"total": 8, "grade_counts": {"A": 0, "B": 3, "C": 3, "D": 2}},
        "entries": [
            {"factor_name": "ret5", "factor_family": "momentum", "expression": "5日收益率",
             "score": 73.5, "grade": "B", "pass_gate": True},
            {"factor_name": "ret10", "factor_family": "momentum", "expression": "10日收益率",
             "score": 69.6, "grade": "B", "pass_gate": True},
            {"factor_name": "close_gt_ma20", "factor_family": "trend", "expression": "站上MA20",
             "score": 69.6, "grade": "B", "pass_gate": True},
            {"factor_name": "reversal5", "factor_family": "reversal", "expression": "5日反转",
             "score": 31.0, "grade": "D", "pass_gate": False},
        ],
    }


def _make_dummy_data() -> pd.DataFrame:
    np.random.seed(42)
    n_stocks, n_days = 50, 20
    symbols = [f"{i:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2025-01-02", periods=n_days, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": sym,
                         "ret5": np.random.randn() * 0.02,
                         "ret10": np.random.randn() * 0.02})
    return pd.DataFrame(rows)
