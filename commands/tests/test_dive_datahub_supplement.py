from __future__ import annotations

from pathlib import Path

from dive_prediction import datahub_supplement


def test_dive_supplement_routes_stock_and_fund_to_one_daily_owner(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        datahub_supplement,
        "_run_daily_datahub",
        lambda: calls.append("daily") or {"status": "OK"},
    )

    assert datahub_supplement.main(["--stocks", "--fund"]) == 0
    assert calls == ["daily"]


def test_dive_supplement_routes_index_to_market_series_owner(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        datahub_supplement,
        "pull_index",
        lambda: calls.append("index") or {"status": "OK"},
    )

    assert datahub_supplement.main(["--index"]) == 0
    assert calls == ["index"]


def test_dive_supplement_contains_no_provider_credentials_or_parallel_writer() -> None:
    source = Path(datahub_supplement.__file__).read_text(encoding="utf-8").lower()
    forbidden = ("jqdatasdk", "jq_account", "jq_pwd", "os.environ.pop", ".unlink(", "csv.dictwriter", "open(")
    assert all(token not in source for token in forbidden)
    assert "datahub_cron.sh" in source
    assert "marketseriesingestion" in source
    assert "datahub_write_lock" in source
