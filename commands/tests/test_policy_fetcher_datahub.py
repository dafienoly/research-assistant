from __future__ import annotations

import json
import pandas as pd

from policy_fetcher import PolicyEventFetcher


def test_policy_fetcher_reads_canonical_announcement_snapshot(tmp_path):
    snapshot = tmp_path / "regulatory_watchlist.json"
    snapshot.write_text(json.dumps({
        "generated_at": "2026-07-10T16:00:00+08:00",
        "covered_symbols": ["688012"],
        "announcements": [{
            "symbol": "688012", "title": "股东减持计划公告", "date": "2026-07-10", "source": "sse",
        }],
    }), encoding="utf-8")

    events = PolicyEventFetcher(snapshot).get_announcement_events(["688012.SH"])

    assert events == [{
        "source": "sse", "event_type": "减持", "title": "股东减持计划公告",
        "symbol": "688012", "date": "2026-07-10", "parsed_at": "2026-07-10T16:00:00+08:00",
    }]


def test_policy_fetcher_fails_closed_for_uncovered_symbol(tmp_path):
    snapshot = tmp_path / "regulatory_watchlist.json"
    snapshot.write_text(json.dumps({"covered_symbols": [], "announcements": []}), encoding="utf-8")

    try:
        PolicyEventFetcher(snapshot).get_announcement_events(["688012"])
    except ValueError as exc:
        assert "coverage missing" in str(exc)
    else:
        raise AssertionError("uncovered policy symbol must fail closed")


def test_policy_empty_refresh_replaces_stale_derived_events_with_manifest(tmp_path, monkeypatch):
    snapshot = tmp_path / "regulatory_watchlist.json"
    snapshot.write_text(json.dumps({
        "generated_at": "2026-07-10T16:00:00+08:00", "covered_symbols": ["688012"],
        "announcements": [],
    }), encoding="utf-8")
    events_root = tmp_path / "events"
    events_root.mkdir()
    stale = events_root / "preopen_events.csv"
    stale.write_text("event_id,title\nstale,old event\n", encoding="utf-8")
    import policy_fetcher as module
    monkeypatch.setitem(module.PATHS, "events", events_root)
    monkeypatch.setitem(module.PATHS, "audit", tmp_path / "audit")
    fetcher = PolicyEventFetcher(snapshot)
    assert fetcher.get_announcement_events(["688012"]) == []

    fetcher.save_preopen_events([])

    assert pd.read_csv(stale).empty
    manifest = json.loads((events_root / "preopen_events.manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "EMPTY"
    assert manifest["covered_symbols"] == ["688012"]
