import numpy as np
import pandas as pd

from factor_lab.vnext.ml import CrossSectionalRanker


def test_ranker_scores_without_trading_instructions():
    frame = pd.DataFrame({"x": np.arange(80), "y": np.arange(80)[::-1]})
    target = frame["x"] * 0.01
    ranker = CrossSectionalRanker("ridge")
    ranker.fit(frame, target, pd.Series(pd.date_range("2025-01-01", periods=80)))
    scores = ranker.score(frame.tail(2), symbols=["A", "B"])
    assert all("candidate_score" in row and "buy" not in row and "sell" not in row for row in scores)


def test_weak_oos_rank_ic_is_watch_only_not_false_confidence():
    frame = pd.DataFrame({"x": np.arange(80), "y": np.arange(80)[::-1]})
    ranker = CrossSectionalRanker("ridge")
    ranker.fit(frame, frame["x"] * 0.01, pd.Series(pd.date_range("2025-01-01", periods=80)))
    assert ranker.trained is not None
    ranker.trained.oos_score["rank_ic"] = 0.001
    card = ranker.model_card()
    score = ranker.score(frame.tail(1), symbols=["A"])[0]
    assert card["status"] == "PARTIAL"
    assert card["promotion_eligible"] is False
    assert card["lifecycle_status"] == "WATCH"
    assert score["confidence"] == 0.02
    assert score["risk_warning"] == "weak_oos_rank_ic_do_not_promote"
