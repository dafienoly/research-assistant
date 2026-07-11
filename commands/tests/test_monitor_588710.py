from unittest.mock import patch

import monitor_588710


def test_quotes_only_read_canonical_datahub_snapshot():
    monitor_588710.ALL_CODES[:] = ["588710", "688012"]
    expected = {"588710": {"price": 1.0, "source": "datahub:akshare"}}
    with patch("monitor_588710.read_live_snapshot", return_value=expected) as reader:
        result = monitor_588710.get_quotes()

    reader.assert_called_once_with(["588710", "688012"])
    assert result == expected


def test_quotes_fail_closed_when_snapshot_is_stale():
    monitor_588710.ALL_CODES[:] = ["588710"]
    with patch("monitor_588710.read_live_snapshot", side_effect=ValueError("stale")):
        assert monitor_588710.get_quotes() == {}


def test_holdings_only_read_canonical_datahub():
    frame = __import__("pandas").DataFrame([
        {"symbol": "688012.SH", "stk_mkv_ratio": 8.5},
        {"symbol": "688072.SH", "stk_mkv_ratio": 7.0},
    ])
    monitor_588710.HOLDINGS.clear()
    monitor_588710.ALL_CODES.clear()
    with patch("monitor_588710.read_etf_holdings", return_value=frame), \
         patch("monitor_588710.read_stock_name_map", return_value={"688012": "中微公司", "688072": "拓荆科技"}):
        monitor_588710._load_holdings()

    assert monitor_588710.HOLDINGS["688012"] == ("中微公司", 8.5)
    assert monitor_588710.ALL_CODES == ["588710", "688012", "688072"]


def test_auxiliary_market_context_does_not_fallback_to_network():
    with patch("monitor_588710.read_latest_north_flow", return_value={"trade_date": "20260710", "north_money": 1234}):
        assert "12.34亿" in monitor_588710.get_north_flow()[0]
    assert "DataHub KOSPI 数据缺失" in monitor_588710.get_kospi()[0]
