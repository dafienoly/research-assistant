from datetime import datetime, timedelta

from factor_lab.decision_loop.storage import DecisionLoopStore
from scripts.decision_ledger_archive import (
    INDEPENDENT_LEDGERS,
    archive_ledgers,
    compact_notification_history,
)


def test_archive_job_covers_all_declared_ledgers_and_preserves_recent_rows(tmp_path) -> None:
    store = DecisionLoopStore(tmp_path)
    old = datetime.now().astimezone() - timedelta(days=120)
    recent = datetime.now().astimezone() - timedelta(days=1)
    ledger = INDEPENDENT_LEDGERS[0]
    store.append_jsonl(ledger, {"id": "old", "created_at": old.isoformat()})
    store.append_jsonl(ledger, {"id": "recent", "created_at": recent.isoformat()})

    result = archive_ledgers(store, retention_days=90)

    assert result["status"] == "OK"
    assert result["checked"] == len(INDEPENDENT_LEDGERS) + 6
    assert ledger in result["archived"]
    assert store.read_jsonl(ledger) == [{"id": "recent", "created_at": recent.isoformat()}]


def test_notification_compaction_never_leaves_replayable_outbox(tmp_path) -> None:
    store = DecisionLoopStore(tmp_path)
    old = datetime.now().astimezone() - timedelta(days=120)
    cutoff = datetime.now().astimezone() - timedelta(days=90)
    key = "event-old:telegram"
    store.append_unique_jsonl(
        "notifications/outbox.jsonl",
        {
            "event_id": "event-old",
            "channel": "telegram",
            "queued_at": old.isoformat(),
        },
        key,
    )
    store.append_unique_jsonl(
        "notifications/delivery_receipts.jsonl",
        {
            "event_id": "event-old",
            "channel": "telegram",
            "delivered": True,
            "attempted_at": old.isoformat(),
        },
        f"delivery:{key}:1",
    )

    archived = compact_notification_history(store, cutoff)

    assert "notifications/outbox.jsonl" in archived
    assert store.read_jsonl("notifications/outbox.jsonl") == []
    assert store.read_jsonl("notifications/delivery_receipts.jsonl") == []


def test_notification_compaction_keeps_pending_and_unacknowledged_state(tmp_path) -> None:
    store = DecisionLoopStore(tmp_path)
    old = datetime.now().astimezone() - timedelta(days=120)
    cutoff = datetime.now().astimezone() - timedelta(days=90)
    store.append_unique_jsonl(
        "notifications/outbox.jsonl",
        {
            "event_id": "event-pending",
            "channel": "telegram",
            "queued_at": old.isoformat(),
        },
        "event-pending:telegram",
    )
    store.append_unique_jsonl(
        "notifications/events.jsonl",
        {"event_id": "event-pending", "generated_at": old.isoformat()},
        "event:event-pending",
    )

    compact_notification_history(store, cutoff)

    assert len(store.read_jsonl("notifications/outbox.jsonl")) == 1
    assert len(store.read_jsonl("notifications/events.jsonl")) == 1
