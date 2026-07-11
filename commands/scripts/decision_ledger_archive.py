#!/usr/bin/env python3
"""Archive old Decision Loop JSONL ledgers without deleting audit history."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from factor_lab.decision_loop.storage import DecisionLoopStore


INDEPENDENT_LEDGERS = (
    "execution/audit.jsonl",
    "cycles/history.jsonl",
    "reviews/records.jsonl",
    "authorization/audit.jsonl",
    "positions/history.jsonl",
    "positions/rollback_audit.jsonl",
    "reconciliation/history.jsonl",
    "reconciliation/failure_history.jsonl",
    "parameters/candidates.jsonl",
    "parameters/weekly_candidates.jsonl",
    "parameters/audit.jsonl",
    "parameters/production_history.jsonl",
    "certification/history.jsonl",
    "scheduler/alerts.jsonl",
)


def _before(row: dict, field: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(row.get(field))) < cutoff
    except (TypeError, ValueError):
        return False


def compact_notification_history(store: DecisionLoopStore, cutoff: datetime) -> dict[str, str]:
    """Archive correlated terminal notification state without making delivery replayable."""
    with store.exclusive("notifications/outbox-worker", timeout=10):
        outbox = store.read_jsonl("notifications/outbox.jsonl")
        receipts = store.read_jsonl("notifications/delivery_receipts.jsonl")
        dead_letters = store.read_jsonl("notifications/dead_letter.jsonl")
        acknowledgements = store.read_jsonl("notifications/acknowledgements.jsonl")
        receipt_terminal = {
            f"{row.get('event_id')}:{row.get('channel')}"
            for row in receipts
            if row.get("delivered")
        }
        dead_terminal = {
            f"{row.get('event_id')}:{row.get('channel')}" for row in dead_letters
        }
        terminal_keys = receipt_terminal | dead_terminal
        selected_outbox = {
            f"{row.get('event_id')}:{row.get('channel')}"
            for row in outbox
            if _before(row, "queued_at", cutoff)
            and f"{row.get('event_id')}:{row.get('channel')}" in terminal_keys
        }
        terminal_event_ids = {
            str(row.get("event_id"))
            for row in outbox
            if f"{row.get('event_id')}:{row.get('channel')}" in selected_outbox
        }
        archived: dict[str, str] = {}

        # Outbox must be removed first. A crash afterwards can leave an orphan receipt,
        # but cannot make an already delivered message eligible for replay.
        path = store.archive_selected_jsonl(
            "notifications/outbox.jsonl",
            cutoff,
            lambda row: f"{row.get('event_id')}:{row.get('channel')}" in selected_outbox,
        )
        if path:
            archived["notifications/outbox.jsonl"] = str(path)
        active_keys = {
            f"{row.get('event_id')}:{row.get('channel')}"
            for row in store.read_jsonl("notifications/outbox.jsonl")
        }
        for ledger, field in (
            ("notifications/delivery_receipts.jsonl", "attempted_at"),
            ("notifications/dead_letter.jsonl", "dead_lettered_at"),
        ):
            path = store.archive_selected_jsonl(
                ledger,
                cutoff,
                lambda row, timestamp=field: _before(row, timestamp, cutoff)
                and f"{row.get('event_id')}:{row.get('channel')}" not in active_keys,
            )
            if path:
                archived[ledger] = str(path)

        acknowledged_ids = {
            str(row.get("event_id"))
            for row in acknowledgements
            if _before(row, "acknowledged_at", cutoff)
        }
        completed_events = terminal_event_ids & acknowledged_ids
        for ledger, timestamp in (
            ("events/events.jsonl", "created_at"),
            ("notifications/events.jsonl", "generated_at"),
            ("notifications/acknowledgements.jsonl", "acknowledged_at"),
        ):
            path = store.archive_selected_jsonl(
                ledger,
                cutoff,
                lambda row, field=timestamp: str(row.get("event_id")) in completed_events
                and _before(row, field, cutoff),
            )
            if path:
                archived[ledger] = str(path)
        return archived


def archive_ledgers(store: DecisionLoopStore, retention_days: int = 90) -> dict[str, object]:
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
    archived = compact_notification_history(store, cutoff)
    for ledger in INDEPENDENT_LEDGERS:
        path = store.archive_jsonl(ledger, cutoff)
        if path is not None:
            archived[ledger] = str(path)
    return {
        "status": "OK",
        "cutoff": cutoff.isoformat(),
        "checked": len(INDEPENDENT_LEDGERS) + 6,
        "archived": archived,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-days", type=int, default=90)
    args = parser.parse_args()
    result = archive_ledgers(DecisionLoopStore(), args.retention_days)
    print(
        f"Decision Loop ledger archive: checked={result['checked']} "
        f"archived={len(result['archived'])} cutoff={result['cutoff']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
