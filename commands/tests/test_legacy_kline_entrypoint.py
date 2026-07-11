from __future__ import annotations

from pathlib import Path

import update_kline_daily


def test_legacy_kline_entrypoint_delegates_to_datahub(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(update_kline_daily, "cmd_update_daily", lambda: calls.append("datahub"))

    update_kline_daily.run()

    assert calls == ["datahub"]


def test_legacy_kline_entrypoint_has_no_provider_or_csv_writer() -> None:
    source = Path(update_kline_daily.__file__).read_text(encoding="utf-8")
    forbidden = ("baostock", "rsscast_mcp", "fetch_kline", "csv.writer", "open(")
    assert all(token not in source.lower() for token in forbidden)
