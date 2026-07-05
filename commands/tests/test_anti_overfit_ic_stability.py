"""测试: 反过拟合 IC 稳定性"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd

from factor_lab.validation.anti_overfit import check_ic_stability


def test_ic_stability_returns_dict():
    """IC 稳定性检查返回预期的 dict keys"""
    df = _make_dummy_factor_data(n_stocks=50, n_days=60)
    result = check_ic_stability(df, "test_factor")
    assert isinstance(result, dict)
    for key in ["ic_mean", "ic_std", "ic_ir", "positive_ic_ratio", "monthly_ic_series", "verdict"]:
        assert key in result, f"缺少 key: {key}"


def test_ic_stability_strong_factor():
    """强因子返回 pass"""
    np.random.seed(42)
    df = _make_dummy_factor_data(n_stocks=100, n_days=120, noise_level=0.3)
    result = check_ic_stability(df, "test_factor")
    print(f"IC_IR={result['ic_ir']:.4f},  verdict={result['verdict']}")
    assert result["verdict"] in ("pass", "warn")


def test_ic_stability_random_factor():
    """随机因子应为 fail 或 warn"""
    np.random.seed(42)
    # 构造真正的随机因子: 收益和因子完全独立
    n_stocks, n_days = 100, 120
    symbols = [f"{i:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2025-01-02", periods=n_days, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            factor = np.random.randn() * 0.02
            ret1 = np.random.randn() * 0.02  # 完全独立
            rows.append({"date": d, "symbol": sym, "test_factor": factor, "ret1": ret1})
    df = pd.DataFrame(rows)
    result = check_ic_stability(df, "test_factor")
    print(f"IC_IR={result['ic_ir']:.4f}, POS={result['positive_ic_ratio']:.2%}, verdict={result['verdict']}")
    assert result["verdict"] != "pass", f"随机因子不应 pass, 实际为 {result['verdict']}"


def test_monthly_ic_nonempty():
    """月度 IC 序列非空"""
    df = _make_dummy_factor_data(n_stocks=30, n_days=120)
    result = check_ic_stability(df, "test_factor")
    assert len(result["monthly_ic_series"]) > 0
    assert len(result["quarterly_ic_series"]) > 0


# ─── 辅助 ─────────────────────────────────────────────────────

def _make_dummy_factor_data(
    n_stocks: int = 50,
    n_days: int = 60,
    noise_level: float = 0.5,
) -> pd.DataFrame:
    """生成测试用因子数据"""
    symbols = [f"{i:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2025-01-02", periods=n_days, freq="B")

    rows = []
    for sym in symbols:
        base = np.random.randn() * 0.02
        for d in dates:
            factor = base + np.random.randn() * noise_level * 0.01
            ret1 = base * 0.5 + np.random.randn() * 0.02
            rows.append({"date": d, "symbol": sym, "test_factor": factor, "ret1": ret1})
    return pd.DataFrame(rows)
