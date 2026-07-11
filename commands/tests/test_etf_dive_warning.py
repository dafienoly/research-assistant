from unittest.mock import patch

from etf_dive_warning import _fetch_snapshot, check_dive_risk


def test_etf_warning_reads_datahub_and_marks_missing_fund_truth():
    row = {
        "159516": {
            "price": 1.2, "change_pct": 2.0, "high": 1.25, "low": 1.18,
            "open": 1.19, "amount": 2_000_000_000, "amplitude": 5.0,
            "turnover_rate": 3.0, "volume": 100, "name": "半导体设备ETF",
            "source": "datahub:akshare",
        }
    }
    with patch("etf_dive_warning.read_live_snapshot", return_value=row):
        result = check_dive_risk("159516")

    assert result["source"] == "datahub:akshare"
    assert result["price"] == 1.2
    assert result["fund_data_status"] == "MISSING"


def test_etf_warning_fails_closed_when_canonical_snapshot_is_stale():
    with patch("etf_dive_warning.read_live_snapshot", side_effect=ValueError("snapshot stale")):
        quote = _fetch_snapshot("159516")
        result = check_dive_risk("159516")

    assert quote == {"_error": "snapshot stale"}
    assert result["risk"] == "未知"
    assert "snapshot stale" in result["error"]
