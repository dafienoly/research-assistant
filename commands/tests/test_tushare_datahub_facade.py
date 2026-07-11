from pathlib import Path

import tushare_datahub


def test_tushare_datahub_compatibility_entries_delegate(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(tushare_datahub, "cmd_update_daily", lambda: calls.append("daily"))
    tushare_datahub.run_incremental(3)
    tushare_datahub.run_full()
    assert calls == ["daily", "daily"]


def test_tushare_datahub_has_no_parallel_provider_or_writer() -> None:
    source = Path(tushare_datahub.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "get_ts_client",
        "pull_daily_by_date",
        "pull_daily_basic",
        "pull_moneyflow",
        "pull_fina_indicator_batch",
        "to_csv(",
        "open(",
        "KLINE_DIR",
        "FUND_FLOW_DIR",
    ):
        assert forbidden not in source
    assert "cmd_update_daily" in source
