#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))

from factor_lab.scheduling import ScheduleRegistry, ScheduledDagRunner  # noqa: E402
from factor_lab.decision_loop.storage import DecisionLoopStore  # noqa: E402
from factor_lab.datahub_access import calendar_row  # noqa: E402


def trading_day_gate(dag_id: str, trading_date: str) -> dict:
    if dag_id == "weekly_datahub":
        return {"status": "NOT_REQUIRED"}
    try:
        day = datetime.fromisoformat(trading_date).date()
        row = calendar_row(day)
    except (FileNotFoundError, ValueError) as exc:
        return {"status": "FAILED", "reason": f"trade_calendar_unavailable:{type(exc).__name__}"}
    return {"status": "OPEN" if int(row["is_open"]) == 1 else "CLOSED", "source": "canonical_datahub"}


def enqueue_failure_alert(result: dict, store: DecisionLoopStore | None = None) -> dict:
    """Persist a failed DAG alert for the existing dual-channel outbox worker."""
    if result.get("status") == "SUCCESS":
        return {"status": "not_required"}
    store = store or DecisionLoopStore()
    dag_id = str(result.get("dag_id") or "unknown")
    trading_date = str(result.get("trading_date") or "unknown")
    event_id = f"ops_dag_{dag_id}_{trading_date}"
    failures = [
        f"{job_id}={record.get('status')}"
        for job_id, record in result.get("jobs", {}).items()
        if record.get("status") not in {"SUCCESS", "SKIPPED"}
    ]
    alert_text = f"[Hermes 运维告警] DAG {dag_id} {trading_date} FAILED\n" + "\n".join(failures)
    queued_at = datetime.now().astimezone().isoformat()
    store.append_unique_jsonl(
        "scheduler/alerts.jsonl",
        {"event_id": event_id, "dag_id": dag_id, "trading_date": trading_date, "failures": failures, "queued_at": queued_at},
        f"alert:{event_id}",
    )
    channels = {}
    for channel in ("telegram", "enterprise_wechat"):
        _, created = store.append_unique_jsonl(
            "notifications/outbox.jsonl",
            {
                "event_id": event_id,
                "channel": channel,
                "payload": {"event_id": event_id, "text": alert_text},
                "queued_at": queued_at,
                "max_attempts": 5,
            },
            f"{event_id}:{channel}",
        )
        channels[channel] = {"queued": True, "created": created}
    return {"status": "queued", "event_id": event_id, "channels": channels}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a resumable Hermes scheduled DAG")
    parser.add_argument("dag_id", nargs="?", help="DAG id from commands/config/scheduled_jobs.json")
    parser.add_argument("--date", default=datetime.now().astimezone().date().isoformat())
    parser.add_argument("--registry", type=Path, default=ROOT / "commands/config/scheduled_jobs.json")
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry = ScheduleRegistry.load(args.registry)
    if args.validate:
        print(json.dumps({"status": "OK", "dags": sorted(registry.dags), "jobs": sorted(registry.jobs)}, indent=2))
        return 0
    if not args.dag_id:
        parser.error("dag_id is required unless --validate is used")
    calendar_gate = trading_day_gate(args.dag_id, args.date)
    if calendar_gate["status"] == "CLOSED":
        print(json.dumps({
            "status": "SKIPPED", "dag_id": args.dag_id, "trading_date": args.date,
            "skip_reason": "non_trading_day", "calendar_gate": calendar_gate,
        }, ensure_ascii=False, indent=2))
        return 0
    if calendar_gate["status"] == "FAILED":
        result = {
            "status": "FAILED", "dag_id": args.dag_id, "trading_date": args.date,
            "jobs": {"trade_calendar_gate": {"status": "FAILED", "reason": calendar_gate["reason"]}},
            "calendar_gate": calendar_gate,
        }
        result["operational_alert"] = enqueue_failure_alert(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    runner = ScheduledDagRunner(ROOT, registry, state_root=args.state_root)
    if args.dry_run:
        print(json.dumps(runner.describe(args.dag_id, args.date), ensure_ascii=False, indent=2))
        return 0
    result = runner.run(args.dag_id, args.date)
    if result["status"] != "SUCCESS":
        try:
            result["operational_alert"] = enqueue_failure_alert(result)
        except (OSError, ValueError, TimeoutError) as exc:
            result["operational_alert"] = {"status": "failed", "error": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
