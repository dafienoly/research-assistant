#!/usr/bin/env python3
"""Refresh canonical live snapshot under the global DataHub writer lock."""

from __future__ import annotations

import json
from datetime import date

from factor_lab.datahub_access import calendar_row
from factor_lab.datahub_ingestion.live_snapshot import LiveSnapshotIngestion


def trading_day_gate(day: date | None = None) -> dict:
    target = day or date.today()
    try:
        row = calendar_row(target)
    except (FileNotFoundError, OSError, ValueError) as exc:
        return {"status": "FAILED", "reason": f"trade_calendar_unavailable:{type(exc).__name__}"}
    return {
        "status": "OPEN" if int(row["is_open"]) == 1 else "CLOSED",
        "source": "canonical_datahub",
        "trading_date": target.isoformat(),
    }


def main() -> int:
    gate = trading_day_gate()
    if gate["status"] == "CLOSED":
        print(json.dumps({"status": "SKIPPED", "reason": "non_trading_day", "calendar_gate": gate}))
        return 0
    if gate["status"] == "FAILED":
        print(json.dumps({"status": "FAILED", "reason": gate["reason"], "calendar_gate": gate}))
        return 2
    try:
        manifest = LiveSnapshotIngestion().fetch_locked()
    except RuntimeError as error:
        if "writer active" not in str(error):
            raise
        print(json.dumps({"status": "DEFERRED", "reason": "datahub_writer_active"}))
        return 75
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
