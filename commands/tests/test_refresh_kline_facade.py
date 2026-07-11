from pathlib import Path

import scripts.refresh_kline_data as refresh


def test_refresh_kline_facade_delegates_once(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(refresh, "cmd_update_daily", lambda: calls.append("daily"))
    refresh.run()
    assert calls == ["daily"]


def test_refresh_kline_facade_cannot_write_or_delete_market_data() -> None:
    source = Path(refresh.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "get_ts_client",
        "pull_daily_data",
        "pull_fund_daily",
        "merge_new_data",
        "fix_etf_schema",
        "clean_hist_duplicates",
        "shutil",
        "unlink(",
        "open(old_csv_path, \"w\"",
    ):
        assert forbidden not in source
    assert "cmd_update_daily" in source
