"""Leader 命令处理器 — 从 hermes_cli.py 拆分而来"""
import sys
from pathlib import Path

_BASE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_BASE))


def handle(command: str, args: list[str]) -> bool:
    if command == "leader:inspect":
        from factor_lab.leader.inspect import run_inspect
        print(run_inspect())
        return True

    elif command == "leader:dispatch":
        from factor_lab.leader.workloop import dispatch_from_completion
        dispatch_from_completion()
        return True

    elif command == "leader:consume-latest-task":
        from factor_lab.leader.workloop import consume_latest_task
        consume_latest_task()
        return True

    elif command == "leader:lock-status":
        from factor_lab.leader.workloop import is_locked, TASKS_DIR
        path = TASKS_DIR / "current_run.lock"
        if path.exists():
            import json
            data = json.loads(path.read_text())
            print(f"  🔒 运行中: {data.get('run_id')}")
        else:
            print(f"  🔓 无运行中任务")
        return True

    elif command == "leader:agent-runner":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--once", action="store_true")
        p.add_argument("--watch", action="store_true")
        p.add_argument("--backend", default="claude")
        p.add_argument("--interval", type=int, default=180)
        a = p.parse_args(args)
        from factor_lab.leader.agent_runner import AgentRunner
        runner = AgentRunner(backend=a.backend, interval=a.interval)
        if a.watch:
            runner.watch()
        else:
            result = runner.run_once()
            print(f"  Status: {result.get('status', '?')}")
            if result.get("completed"):
                print(f"  ✅ Completed: {', '.join(result['completed'])}")
            if result.get("remaining"):
                print(f"  ⏳ Remaining: {', '.join(result['remaining'])}")
        return True

    elif command == "leader:loop-once":
        from factor_lab.leader.agent_runner import loop_once
        loop_once()
        return True

    elif command == "leader:automation-status":
        from factor_lab.leader.auto_health import health
        print(health())
        return True

    elif command == "leader:roadmap-status":
        from factor_lab.leader.roadmap import roadmap_as_dicts
        from factor_lab.leader.roadmap_cursor import get_cursor, status_text
        print(status_text())
        return True

    elif command == "leader:task-list":
        from factor_lab.leader.workloop import TASKS_DIR
        import json
        latest = TASKS_DIR / "latest.json"
        if latest.exists():
            data = json.loads(latest.read_text())
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("  ⚠️ latest.json 不存在")
        return True

    elif command == "leader:version-report":
        from factor_lab.leader.version_detail import build_report
        result = build_report()
        print(result.get("summary", result.get("report", "No report")))
        return True

    elif command == "leader:backup-list":
        from factor_lab.leader.roadmap_backup import list_backups
        for b in list_backups():
            print(f"  {b}")
        return True

    elif command == "leader:recover":
        from factor_lab.leader.roadmap_backup import restore_backup
        backup_id = args[0] if args else ""
        result = restore_backup(backup_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return True

    elif command == "leader:task-submit":
        from factor_lab.leader.task_intake import build_task_package
        title = " ".join(args) if args else "quick task"
        build_task_package(title)
        return True

    elif command == "leader:auto-run-once":
        from factor_lab.leader.auto_executor import auto_run_once
        result = auto_run_once()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return True

    elif command == "leader:auto-status":
        from factor_lab.leader.cursor import get_cursor
        print(get_cursor())
        return True

    elif command == "leader:dashboard":
        from factor_lab.leader.dashboard import serve
        import os
        port = int(os.environ.get("HERMES_DASHBOARD_PORT", "8765"))
        serve(port=port)
        return True

    elif command == "leader:dashboard-json":
        from factor_lab.leader.version_detail import dashboard_json
        print(dashboard_json())
        return True

    elif command == "leader:accept":
        from factor_lab.leader.acceptance import run_acceptance
        print(run_acceptance())
        return True

    elif command == "leader:github-sync":
        from factor_lab.leader.github_sync import sync
        sync()
        return True

    elif command == "leader:loop-watch":
        from factor_lab.leader.auto_executor import auto_loop
        auto_loop()
        return True

    elif command == "architecture:audit":
        from factor_lab.leader.architecture_audit import run_audit
        result = run_audit()
        for item in result:
            print(f"  [{item.get('severity','INFO')}] {item.get('message','')}")
        return True

    return False  # 未处理
