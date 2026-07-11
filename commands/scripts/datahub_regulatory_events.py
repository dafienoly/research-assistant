#!/usr/bin/env python3
"""Refresh regulatory truth for current planned/held symbols."""

from __future__ import annotations

import json
import fcntl
from pathlib import Path

from factor_lab.datahub_ingestion.regulatory_events import RegulatoryEventIngestion
from factor_lab.decision_loop.service import DecisionLoopService


ROOT = Path(__file__).resolve().parents[2]
LOCK = Path.home() / ".hermes/locks/datahub-global.lock"


def _current_symbols() -> list[str]:
    service = DecisionLoopService()
    symbols = set()
    snapshot = service.status().get("current_position_snapshot") or {}
    for position in snapshot.get("positions", []):
        if position.get("symbol"):
            symbols.add(str(position["symbol"]))
    watchlist = service.store.read_json("watchlist/current.json", default={}) or {}
    for key in ("primary", "backup", "anchor_etfs", "symbols"):
        for item in watchlist.get(key, []) or []:
            symbol = item.get("symbol") if isinstance(item, dict) else item
            if symbol:
                symbols.add(str(symbol))
    return sorted(symbols)


def main() -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "DEFERRED", "reason": "datahub_writer_active"}))
            return 75
        result = RegulatoryEventIngestion(ROOT).fetch(_current_symbols())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"OK", "EMPTY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
