"""测试: 因子相关性矩阵 + TopN 重合度 + 组合方法"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd

from factor_lab.composite.factor_correlation import compute_correlation, compute_topn_overlap
from factor_lab.composite.factor_combiner import compute_composite


# ─── 相关性矩阵 ───────────────────────────────────────────────

def test_correlation_returns_dict():
    df = _make_dummy_data()
    r = compute_correlation(df, ["ret5", "ret10"])
    assert "pearson" in r
    assert "spearman" in r
    assert "avg_corr" in r


def test_correlation_positive():
    """完全正相关的因子 avg_corr ≈ 1"""
    np.random.seed(42)
    n = 100
    df = pd.DataFrame({
        "date": ["2025-01-02"] * n,
        "symbol": [f"{i:06d}" for i in range(n)],
        "ret5": np.random.randn(n),
    })
    df["ret10"] = df["ret5"] + np.random.randn(n) * 0.01  # 几乎相同
    r = compute_correlation(df, ["ret5", "ret10"])
    assert r["avg_corr"] > 0.8, f"预期高相关, 实际 {r['avg_corr']}"


def test_correlation_random():
    """随机因子 avg_corr ≈ 0"""
    np.random.seed(42)
    n = 200
    df = pd.DataFrame({
        "date": ["2025-01-02"] * n,
        "symbol": [f"{i:06d}" for i in range(n)],
        "f1": np.random.randn(n),
        "f2": np.random.randn(n),
    })
    r = compute_correlation(df, ["f1", "f2"])
    assert abs(r["avg_corr"]) < 0.3, f"预期低相关, 实际 {r['avg_corr']}"


# ─── TopN 重合度 ──────────────────────────────────────────────

def test_topn_overlap_identical():
    """相同因子 overlap ≈ 1"""
    np.random.seed(42)
    df = _make_dummy_data()
    r = compute_topn_overlap(df, ["ret5", "ret5"])
    assert r["overlap_matrix"]["ret5"]["ret5"] == 1.0


def test_topn_overlap_random():
    """随机因子 overlap ≈ 0"""
    np.random.seed(42)
    n_stocks, n_days = 100, 30
    symbols = [f"{i:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2025-01-02", periods=n_days, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": sym, "f1": np.random.randn(), "f2": np.random.randn()})
    df = pd.DataFrame(rows)
    r = compute_topn_overlap(df, ["f1", "f2"], top_quantile=0.2)
    assert r["overlap_matrix"]["f1"]["f2"] < 0.3, f"预期低overlap, 实际 {r}"


# ─── 组合方法 ─────────────────────────────────────────────────

def test_equal_weight_composite():
    """等权组合输出非空"""
    df = _make_dummy_data(extra_cols=True)
    result = compute_composite(df, ["ret5", "ret10", "vol_ratio60"], method="equal_weight_score")
    assert len(result) == len(df)
    assert not result.isna().all()


def test_weighted_score_composite():
    """加权组合输出非空"""
    df = _make_dummy_data(extra_cols=True)
    weights = {"ret5": 0.5, "ret10": 0.3, "vol_ratio60": 0.2}
    result = compute_composite(df, ["ret5", "ret10", "vol_ratio60"],
                                method="weighted_score", weights=weights)
    assert len(result) == len(df)


def test_gated_score_composite():
    """门控组合: gate=False 时结果为 0"""
    df = _make_dummy_data(extra_cols=True)
    # 所有 ret5 rank 改为 < 0.5 来测试
    result = compute_composite(df, ["ret5", "close_gt_ma20"], method="gated_score")
    assert len(result) == len(df)


def test_zscore_blend_composite():
    df = _make_dummy_data(extra_cols=True)
    weights = {"ret5": 0.5, "ret10": 0.5}
    result = compute_composite(df, ["ret5", "ret10"], method="zscore_blend", weights=weights)
    assert len(result) == len(df)


def test_rank_blend_composite():
    df = _make_dummy_data(extra_cols=True)
    weights = {"ret5": 0.6, "ret10": 0.4}
    result = compute_composite(df, ["ret5", "ret10"], method="rank_blend", weights=weights)
    assert len(result) == len(df)


# ─── 辅助 ─────────────────────────────────────────────────────

def _make_dummy_data(extra_cols=False) -> pd.DataFrame:
    np.random.seed(42)
    n_stocks, n_days = 50, 30
    symbols = [f"{i:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2025-01-02", periods=n_days, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            r = {
                "date": d, "symbol": sym,
                "ret5": np.random.randn() * 0.02,
                "ret10": np.random.randn() * 0.02,
            }
            if extra_cols:
                r["vol_ratio60"] = np.random.randn() * 0.5 + 1.0
                r["close_gt_ma20"] = np.random.randn() * 0.01
            rows.append(r)
    return pd.DataFrame(rows)
