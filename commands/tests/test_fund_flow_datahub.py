from pathlib import Path

import pandas as pd

import fund_flow


def test_stock_fund_flow_reads_canonical_partition(monkeypatch) -> None:
    monkeypatch.setattr(
        fund_flow,
        "read_fund_flow_partitions",
        lambda symbols: pd.DataFrame(
            [
                {"symbol": symbols[0], "date": "20260709", "net_main_force": 1.0},
                {"symbol": symbols[0], "date": "20260710", "net_main_force": 2.0},
            ]
        ),
    )
    monkeypatch.setattr(
        fund_flow,
        "read_trade_calendar",
        lambda: pd.DataFrame([{"cal_date": "20260710", "is_open": 1}]),
    )
    result = fund_flow.extract_stock_fund_flow("688012.SH")
    assert result["data_status"] == "OK"
    assert result["observed_at"] == "20260710"
    assert result["net_main_force"] == 2.0


def test_stock_fund_flow_marks_old_partition_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        fund_flow,
        "read_fund_flow_partitions",
        lambda symbols: pd.DataFrame([{"symbol": symbols[0], "date": "20240101", "net_main_force": 1.0}]),
    )
    monkeypatch.setattr(
        fund_flow,
        "read_trade_calendar",
        lambda: pd.DataFrame([{"cal_date": "20260710", "is_open": 1}]),
    )
    result = fund_flow.extract_stock_fund_flow("688012")
    assert result["data_status"] == "STALE"
    assert result["lag_days"] > 7


def test_market_flow_fails_closed_without_owned_dataset() -> None:
    result = fund_flow.extract_market_fund_flow()
    assert result["data_status"] == "MISSING"


def test_fund_flow_has_no_browser_or_provider_bypass() -> None:
    source = Path(fund_flow.__file__).read_text(encoding="utf-8")
    assert "browser_navigator" not in source
    assert "eastmoney.com" not in source
    assert "read_fund_flow_partitions" in source
