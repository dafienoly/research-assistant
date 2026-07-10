import pandas as pd
import pytest

from factor_lab.vnext.snapshot import HubSnapshotBuilder


def test_snapshot_helpers_use_only_available_history():
    frame = pd.DataFrame({"close": [10.0, 11.0], "vol": [100.0, 200.0]})
    assert HubSnapshotBuilder._period_return(frame, 1) == pytest.approx(0.1)
    assert HubSnapshotBuilder._relative_score(None, 0.1) is None


def test_style_baskets_use_equal_weight_real_member_returns():
    dates = pd.date_range("2026-01-01", periods=3)
    baskets = {
        "pcb": {
            "A": pd.DataFrame({"trade_date": dates, "close": [10.0, 11.0, 12.1]}),
            "B": pd.DataFrame({"trade_date": dates, "close": [20.0, 18.0, 19.8]}),
        }
    }
    rows = HubSnapshotBuilder._basket_returns(baskets)["pcb"]
    assert rows[0]["return"] == pytest.approx(0.0)
    assert rows[1]["return"] == pytest.approx(0.1)
