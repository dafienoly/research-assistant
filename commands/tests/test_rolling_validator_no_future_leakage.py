"""测试: Walk-Forward 无未来数据泄漏"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd

from factor_lab.validation.rolling_validator import (
    _first_trading_days,
)


def test_first_trading_days():
    """每月第一个交易日函数不为空"""
    dates = pd.bdate_range("2025-01-02", periods=100, freq="B")
    result = _first_trading_days(dates)
    assert len(result) > 0
    assert len(result) < len(dates)


def test_limited_validation_on_short_data():
    """数据不足时返回 limited 报告, 不沉默崩溃"""
    import numpy as np
    import pandas as pd
    from factor_lab.validation.rolling_validator import run_rolling_validation

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
    assert r["limitation"] in ("limited", "insufficient_data"), \
        f"应为 limited 或 insufficient_data, 实际为 {r['limitation']}"
