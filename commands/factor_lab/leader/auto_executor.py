"""Auto Executor — 连续自动开发执行器"""
import sys, json, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap import get_roadmap, get_version, next_version
from factor_lab.leader.roadmap_cursor import get_cursor, advance, set_blocked
from factor_lab.leader.backend_policy import select_backend, need_code_change, policy_status
from factor_lab.leader.task_intake import intake, route_to_version, build_task_package
from factor_lab.leader.workloop import write_completion, release_lock, TASKS_DIR

CST = timezone(timedelta(hours=8))
VENV = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
CLI = "/home/ly/.hermes/research-assistant/commands/hermes_cli.py"


def auto_run_once():
    """自动执行器主循环"""
    release_lock("completed")

    # 1. 读取 cursor
    cursor = get_cursor()
    current = cursor["current_version"]
    cv = get_version(current)

    # 2. 检查是否 backlog
    if cv and cv.get("trading_mode") == "backlog":
        write_completion("blocked", current, current, next_question=f"{current} is backlog, not auto-executed",
                          remaining_tasks=[current])
        return {"status": "blocked", "reason": "backlog"}

    # 3. 检查 manual_required
    if cv and cv.get("manual_required", False):
        write_completion("blocked", current, current, next_question=f"{current} requires manual gate: {cv.get('objective','')}",
                          remaining_tasks=[current])
        set_blocked(current, cv.get("objective", ""))
        return {"status": "blocked", "reason": "manual_required"}

    # 4. 检查 backend
    task_type = "code_change"  # default for auto development
    backend = select_backend(task_type)
    if backend is None:
        write_completion("blocked", current, current,
                          next_question="coding_backend_not_configured",
                          remaining_tasks=[current])
        return {"status": "blocked", "reason": "coding_backend_not_configured"}

    # 5. Scan inbox
    inbox = intake()

    # 6. Check latest.json
    latest = TASKS_DIR / "latest.json"
    pending_tasks = []
    if latest.exists():
        lj = json.loads(latest.read_text())
        if lj.get("status") == "pending" and lj.get("task_count", 0) > 0:
            pending_tasks = lj

    # 7. If no pending tasks, auto-generate from roadmap
    if not pending_tasks:
        task_desc = f"Implement {cv['version']}: {cv['name']} - {cv['objective']}"
        rid = build_task_package(current, [{"title": cv["name"], "text": task_desc}])
        pending_tasks = {"run_id": rid, "status": "pending"}

    # 8. Execute agent-runner
    result = subprocess.run([VENV, CLI, "leader:agent-runner", "--once", "--backend", backend],
                             capture_output=True, text=True, timeout=60)

    # 9. Run tests
    test_ok = True
    try:
        subprocess.run([VENV, "-m", "pytest", "-q", "--tb=short"], capture_output=True, text=True, timeout=30)
    except Exception:
        test_ok = False

    # 10. Git commit
    commit = ""
    if test_ok:
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(TASKS_DIR.parent))
            commit = r.stdout.strip()
        except Exception:
            pass
        advance(current, "completed", commit=commit, run_id=latest.read_text() if latest.exists() else "")
        write_completion("completed", current, cv["name"],
                          completed_tasks=[current], remaining_tasks=[],
                          next_question=f"continue with {next_version(current)['version'] if next_version(current) else 'done'}")
    else:
        advance(current, "failed")
        write_completion("partial", current, cv["name"], remaining_tasks=[current])

    return {"status": "completed" if test_ok else "partial", "version": current, "backend": backend, "commit": commit}
