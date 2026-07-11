from __future__ import annotations

import numpy as np
import pandas as pd

from factor_lab.vnext.ml_governance import _relevance_labels, purged_embargo_split


def test_purged_embargo_split_has_disjoint_ordered_windows():
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    frame = pd.DataFrame(
        [
            {"date": day, "symbol": f"S{symbol}", "forward_return": symbol / 100}
            for day in dates
            for symbol in range(5)
        ]
    )
    train, validation, test, manifest = purged_embargo_split(frame, purge_days=5, embargo_days=5)
    assert train["date"].max() < validation["date"].min() < test["date"].min()
    assert (validation["date"].min() - train["date"].max()).days >= 5
    assert (test["date"].min() - validation["date"].max()).days >= 5
    assert manifest["purge_trading_days"] == 5
    assert manifest["embargo_trading_days"] == 5


def test_relevance_labels_are_cross_sectional_and_bounded():
    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-01-01")] * 10 + [pd.Timestamp("2026-01-02")] * 10,
            "forward_return": np.tile(np.arange(10), 2),
        }
    )
    labels = _relevance_labels(frame)
    assert labels.min() >= 0
    assert labels.max() <= 4
    assert labels[:10].tolist() == labels[10:].tolist()
