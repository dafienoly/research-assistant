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
    runner = ScheduledDagRunner(ROOT, registry, state_root=args.state_root)
    if args.dry_run:
        print(json.dumps(runner.describe(args.dag_id, args.date), ensure_ascii=False, indent=2))
        return 0
    result = runner.run(args.dag_id, args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

