from unittest.mock import patch

from dive_prediction import live_predictor


def test_realtime_price_reads_datahub_without_synthetic_high_low():
    row = {live_predictor.ETF_CODE: {
        "price": 1.2, "change_pct": -2.0, "high": 1.3, "low": 1.1,
        "open": 1.25, "amount": 2_000_000_000, "source": "datahub:akshare",
    }}
    with patch.object(live_predictor, "read_live_snapshot", return_value=row):
        result = live_predictor.fetch_realtime_price()

    assert result["high"] == 1.3
    assert result["low"] == 1.1
    assert result["amount"] == 20
    assert result["source"] == "datahub:akshare"


def test_event_market_breadth_reads_same_canonical_snapshot():
    snapshot = {
        str(index): {"change_pct": -6 if index < 20 else 1}
        for index in range(200)
    }
    with patch.object(live_predictor, "read_live_snapshot", return_value=snapshot):
        result = live_predictor.check_event_driven()

    assert result["risk_boost"] == 1
    assert "市场普跌" in result["detail"]
