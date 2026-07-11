from __future__ import annotations

from pathlib import Path

import pandas as pd

from factor_lab import factor_engine
from factor_lab.datahub_access import factor_input_locations, read_fund_flow_partitions, read_stock_industry_map


def test_factor_input_locations_support_isolated_datahub_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HERMES_FACTOR_DATA_ROOT", str(tmp_path / "derived"))
    monkeypatch.setenv("HERMES_FACTOR_KLINE_ROOT", str(tmp_path / "daily"))

    locations = factor_input_locations()

    assert locations.daily_kline == tmp_path / "daily"
    assert locations.fundamentals == tmp_path / "derived/fundamentals/fundamentals_timeseries.csv"
    assert locations.fund_flow == tmp_path / "derived/fundamentals/fund_flow_timeseries.csv"
    assert locations.events == tmp_path / "derived/event_timeseries.csv"


def test_load_stock_kline_preserves_schema_filtering_and_datahub_isolation(monkeypatch, tmp_path: Path) -> None:
    kline_root = tmp_path / "daily"
    kline_root.mkdir()
    pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
            "open": [10, 11, 12],
            "high": [11, 12, 13],
            "low": [9, 10, 11],
            "close": [10.5, 11.5, 12.5],
            "volume": [100, 200, 300],
            "amount": [1000, 2000, 3000],
        }
    ).to_csv(kline_root / "000001.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "date": ["2026-07-01"],
            "open": [20],
            "high": [21],
            "low": [19],
            "close": [20.5],
            "volume": [100],
            "amount": [2000],
        }
    ).to_csv(kline_root / "000002.csv", index=False, encoding="utf-8-sig")
    monkeypatch.setattr(factor_engine, "KLINE", kline_root)
    for name in ("FUND_CSV", "FLOW_CSV", "NORTH_CSV", "MARGIN_CSV", "EVENT_CSV", "SENTIMENT_CSV"):
        monkeypatch.setattr(factor_engine, name, tmp_path / f"missing-{name}.csv")

    frame = factor_engine.load_stock_kline(
        ["000001", "000002", "999999"],
        start_date="2026-07-02",
        end_date="2026-07-03",
        min_days=2,
    )

    assert list(frame["symbol"].unique()) == ["000001"]
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-02", "2026-07-03"]
    assert pd.api.types.is_numeric_dtype(frame["close"])
    assert set(["symbol", "date", "open", "high", "low", "close", "volume", "amount"]).issubset(frame.columns)


def test_load_stock_kline_accepts_canonical_datahub_schema(monkeypatch, tmp_path: Path) -> None:
    kline_root = tmp_path / "market"
    kline_root.mkdir()
    pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": [20260709, 20260710],
            "open": [10, 10.5],
            "high": [11, 11.5],
            "low": [9.5, 10],
            "close": [10.5, 11],
            "vol": [100, 200],
            "amount": [1000, 2200],
        }
    ).to_csv(kline_root / "000001.SZ.csv", index=False, encoding="utf-8-sig")
    monkeypatch.setattr(factor_engine, "KLINE", kline_root)
    for name in ("FUND_CSV", "FLOW_CSV", "NORTH_CSV", "MARGIN_CSV", "EVENT_CSV", "SENTIMENT_CSV"):
        monkeypatch.setattr(factor_engine, name, tmp_path / f"missing-{name}.csv")

    frame = factor_engine.load_stock_kline(
        ["000001"],
        start_date="2026-07-09",
        end_date="2026-07-10",
        min_days=2,
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-09", "2026-07-10"]
    assert frame["volume"].tolist() == [100, 200]


def test_industry_map_is_read_from_canonical_stock_reference(tmp_path: Path) -> None:
    source = tmp_path / "stock_basic.csv"
    pd.DataFrame(
        {
            "symbol": ["1", "000002", "000003"],
            "industry": ["银行", "房地产", None],
        }
    ).to_csv(source, index=False, encoding="utf-8-sig")

    mapping = read_stock_industry_map(source)

    assert mapping == {"000001": "银行", "000002": "房地产"}


def test_fund_flow_reads_only_requested_canonical_partitions(tmp_path: Path) -> None:
    pd.DataFrame({
        "ts_code": ["688012.SH"], "trade_date": [20260710], "net_mf_amount": [10.0],
        "buy_elg_amount": [7.0], "sell_elg_amount": [2.0],
    }).to_csv(tmp_path / "688012.SH.csv", index=False)
    pd.DataFrame({
        "ts_code": ["000001.SZ"], "trade_date": [20260710], "net_mf_amount": [99.0],
    }).to_csv(tmp_path / "000001.SZ.csv", index=False)

    frame = read_fund_flow_partitions(["688012"], root=tmp_path)

    assert frame["symbol"].unique().tolist() == ["688012"]
    assert frame.iloc[0]["net_main_force"] == 10.0
    assert frame.iloc[0]["net_super_large"] == 5.0


def test_stock_loader_requests_only_active_fund_flow_partitions(monkeypatch, tmp_path: Path) -> None:
    kline_root = tmp_path / "daily"
    kline_root.mkdir()
    pd.DataFrame({
        "date": ["2026-07-09", "2026-07-10"], "open": [10, 11], "high": [11, 12],
        "low": [9, 10], "close": [10.5, 11.5], "volume": [100, 200], "amount": [1000, 2300],
    }).to_csv(kline_root / "688012.csv", index=False)
    monkeypatch.setattr(factor_engine, "KLINE", kline_root)
    for name in ("FUND_CSV", "NORTH_CSV", "MARGIN_CSV", "EVENT_CSV", "SENTIMENT_CSV"):
        monkeypatch.setattr(factor_engine, name, tmp_path / f"missing-{name}.csv")
    requested: list[list[str]] = []

    def read_partitions(symbols: list[str]) -> pd.DataFrame:
        requested.append(symbols)
        return pd.DataFrame({
            "symbol": ["688012"], "date": [20260710], "net_main_force": [12.0],
        })

    monkeypatch.setattr(factor_engine, "read_fund_flow_partitions", read_partitions)

    frame = factor_engine.load_stock_kline(
        ["688012", "000001"], start_date="2026-07-09", end_date="2026-07-10", min_days=2,
    )

    assert requested == [["688012"]]
    assert frame.loc[frame["date"] == pd.Timestamp("2026-07-10"), "net_main_force"].iloc[0] == 12.0


def test_incompatible_auxiliary_schema_is_visible_and_not_broadcast(tmp_path: Path, capsys) -> None:
    source = tmp_path / "north_flow_timeseries.csv"
    pd.DataFrame({"trade_date": [20260710], "north_money": [100.0]}).to_csv(
        source, index=False, encoding="utf-8-sig"
    )

    frame = factor_engine._load_csv(source, factor_engine.NORTH_FIELDS)

    assert frame.empty
    output = capsys.readouterr().out
    assert "schema 不兼容" in output
    assert "symbol" in output


def test_factor_engine_has_no_machine_specific_data_paths() -> None:
    source = Path(factor_engine.__file__).read_text(encoding="utf-8")
    assert "/mnt/c/Users/" not in source
    assert "/home/ly/" not in source
    assert "factor_input_locations" in source
    assert "IndustryMapper" not in source
