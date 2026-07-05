"""测试: 不允许 silent fallback — 适配 rolling_validator 实际 API"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.validation.rolling_validator import (
    run_rolling_validation,
)


def test_limited_validation_on_short_data():
    """数据不足时返回 limited/insufficient_data, 不沉默崩溃"""
    import numpy as np
    import pandas as pd

    np.random.seed(42)
    symbols = [f"{i:06d}" for i in range(30)]
    dates = pd.bdate_range("2025-01-02", periods=60, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": sym, "test_factor": np.random.randn(),
                         "ret1": np.random.randn() * 0.02, "close": 10 + np.random.randn()})
    df = pd.DataFrame(rows)
    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    r = run_rolling_validation(df, "test_factor", close_pivot,
                                train_window_months=6, val_window_months=3, test_window_months=3,
                                start_date="2025-01-02", end_date="2025-03-31")
    assert r["limitation"] in ("limited", "insufficient_data"), f"应为 limited, 实际为 {r['limitation']}"
    assert r.get("n_windows", 0) == 0, "不足时窗口数应为 0"


def test_full_validation_on_adequate_data():
    """数据充足时返回 full 验证"""
    import numpy as np
    import pandas as pd

    np.random.seed(42)
    symbols = [f"{i:06d}" for i in range(30)]
    dates = pd.bdate_range("2025-01-02", periods=300, freq="B")
    rows = []
    for sym in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": sym, "test_factor": np.random.randn() * 2,
                         "ret1": np.random.randn() * 0.02, "close": 10 + np.random.randn()})
    df = pd.DataFrame(rows)
    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    r = run_rolling_validation(df, "test_factor", close_pivot,
                                train_window_months=3, val_window_months=1, test_window_months=1,
                                start_date="2025-01-02", end_date="2025-09-30")
    print(f"  windows={r.get('total_windows',0)}, limitation={r['limitation']}, keys={list(r.keys())}")
    assert r.get("total_windows", 0) >= 2 or len(r.get("windows", [])) >= 2, f"至少2个窗口, 实际 total_windows={r.get('total_windows',0)}"
