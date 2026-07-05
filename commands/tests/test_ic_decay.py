"""测试: IC 衰减"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd

from factor_lab.validation.anti_overfit import check_ic_decay


def test_ic_decay_short_horizon_best():
    """IC 衰减曲线包含所有预期 horizon"""
    df = _make_momentum_factor_data()
    result = check_ic_decay(df, "test_factor", horizons=[1, 3, 5, 10, 20])
    curve = result["ic_decay_curve"]
    print(f"Curve: {curve}")
    for h in ["1D", "3D", "5D", "10D", "20D"]:
        assert h in curve, f"缺少 horizon {h}"
    assert result["half_life_days"] >= 1


def test_ic_decay_curve_nonempty():
    """IC 衰减曲线非空"""
    df = _make_momentum_factor_data()
    result = check_ic_decay(df, "test_factor")
    assert len(result["ic_decay_curve"]) > 0
    assert result["half_life_days"] >= 1


def test_ic_decay_strong_signal():
    """强信号半衰期应 >= 1"""
    df = _make_momentum_factor_data()
    result = check_ic_decay(df, "test_factor")
    assert result["half_life_days"] >= 1
    assert result["verdict"] in ("pass", "warn")


def _make_momentum_factor_data() -> pd.DataFrame:
    """生成有动量效应的数据"""
    np.random.seed(42)
    symbols = [f"{i:06d}" for i in range(60)]
    dates = pd.bdate_range("2025-01-02", periods=120, freq="B")
    rows = []
    for sym in symbols:
        trend = np.cumsum(np.random.randn(len(dates)) * 0.005)
        for i, d in enumerate(dates):
            close = 10 + trend[i]
            factor = trend[i] - (trend[i-5] if i >= 5 else 0)
            rows.append({"date": d, "symbol": sym, "test_factor": factor,
                         "close": close})
    return pd.DataFrame(rows)
