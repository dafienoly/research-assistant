import numpy as np
import pandas as pd

from factor_lab.vnext.datasets import MLRankingDatasetBuilder, PolicyBacktestDatasetBuilder


def test_ml_dataset_builder_removes_forward_label_from_scoring(tmp_path):
    root = tmp_path / "data" / "normalized" / "market"
    root.mkdir(parents=True)
    dates = pd.date_range("2025-01-01", periods=80, freq="B")
    pd.DataFrame({"ts_code": "600001.SH", "trade_date": dates.strftime("%Y%m%d"), "close": np.arange(80) + 10, "vol": np.arange(80) + 100, "amount": np.arange(80) + 1000}).to_csv(root / "600001.SH.csv", index=False)
    result = MLRankingDatasetBuilder(tmp_path).build("2025-01-01", "2025-05-01", tmp_path / "train.csv", tmp_path / "score.csv")
    assert result["training_rows"] > 0
    assert "forward_return" not in pd.read_csv(tmp_path / "score.csv").columns


def test_policy_dataset_returns_missing_when_primary_index_absent(tmp_path, monkeypatch):
    builder = PolicyBacktestDatasetBuilder(tmp_path)
    monkeypatch.setattr(builder, "_query", lambda *args: pd.DataFrame())
    result = builder.build("2025-01-01", "2025-05-01", tmp_path / "policy.csv")
    assert result["status"] == "MISSING"
    assert "datahub:index_daily:000001.SH" in result["missing_evidence"]


def test_policy_dataset_reads_market_series_from_datahub_without_provider(tmp_path):
    root = tmp_path / "data/normalized/market_series/index"
    root.mkdir(parents=True)
    pd.DataFrame({"trade_date": ["20250102"], "close": [3200]}).to_csv(root / "000001.SH.csv", index=False)
    builder = PolicyBacktestDatasetBuilder(tmp_path)
    frame = builder._query("index_daily", "000001.SH", "20250101", "20250131")
    assert len(frame) == 1
    assert builder.sources[0]["source"] == "datahub:index_daily:000001.SH"


def test_policy_dataset_marks_partial_sources_without_zero_filling_returns(tmp_path, monkeypatch):
    builder = PolicyBacktestDatasetBuilder(tmp_path)
    dates = pd.date_range("2025-01-01", periods=130, freq="B")
    sse = pd.DataFrame(
        {
            "trade_date": dates,
            "open": np.linspace(3900, 4000, len(dates)),
            "high": np.linspace(3910, 4010, len(dates)),
            "low": np.linspace(3890, 3990, len(dates)),
            "close": np.linspace(3900, 4000, len(dates)),
            "pct_chg": np.linspace(-1, 1, len(dates)),
            "amount": 1_000_000,
        }
    )
    def query(api, code, start, end):
        frame = sse.copy() if code == "000001.SH" else pd.DataFrame()
        builder.sources.append({"source": f"fixture:{api}:{code}", "status": "OK" if not frame.empty else "MISSING", "records": len(frame)})
        return frame

    monkeypatch.setattr(builder, "_query", query)
    monkeypatch.setattr(builder, "_breadth", lambda start, end: pd.DataFrame())
    monkeypatch.setattr(builder, "_anchor_equal_return", lambda start, end: pd.Series(dtype=float))
    output = tmp_path / "policy.csv"
    result = builder.build("2025-01-01", "2025-07-01", output)
    frame = pd.read_csv(output)
    assert result["status"] == "PARTIAL"
    assert frame["strategy_return"].isna().all()
    assert frame["semiconductor"].isna().all()


def test_policy_breadth_vectorized_batches_count_each_stock_day(tmp_path):
    root = tmp_path / "data" / "normalized" / "market"
    root.mkdir(parents=True)
    pd.DataFrame({"trade_date": ["20250102", "20250103"], "pct_chg": [1.0, -1.0]}).to_csv(root / "A.csv", index=False)
    pd.DataFrame({"trade_date": ["20250102", "20250103"], "pct_chg": [-2.0, -3.0]}).to_csv(root / "B.csv", index=False)
    result = PolicyBacktestDatasetBuilder(tmp_path)._breadth("2025-01-01", "2025-01-31")
    assert result.loc[pd.Timestamp("2025-01-02")].to_dict() == {"advancing": 1, "declining": 1}
    assert result.loc[pd.Timestamp("2025-01-03")].to_dict() == {"advancing": 0, "declining": 2}


def test_anchor_returns_parse_integer_dates_and_deduplicate(tmp_path):
    root = tmp_path / "data/normalized/market"
    root.mkdir(parents=True)
    pd.DataFrame(
        {
            "trade_date": [20250102, 20250102, 20250103],
            "close": [10, 11, 12],
        }
    ).to_csv(root / "002371.SZ.csv", index=False)
    builder = PolicyBacktestDatasetBuilder(tmp_path)
    result = builder._anchor_equal_return("2025-01-01", "2025-01-31")
    assert list(result.index) == [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]
    assert any(row.get("duplicate_rows") == 1 for row in builder.sources)
