"""Auto Executor — 连续自动开发执行器 (RoadmapItem 兼容版)"""
import sys, json, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap import get_roadmap, get_version, next_version
from factor_lab.leader.roadmap_cursor import get_cursor, advance, set_blocked
from factor_lab.leader.backend_policy import select_backend, need_code_change
from factor_lab.leader.task_intake import build_task_package
from factor_lab.leader.workloop import write_completion, release_lock, TASKS_DIR

CST = timezone(timedelta(hours=8))
VENV = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
CLI = "/home/ly/.hermes/research-assistant/commands/hermes_cli.py"


def _read_latest():
    p = TASKS_DIR / "latest.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _write_latest(run_id, run_dir, version, task_count):
    (TASKS_DIR / "latest.json").write_text(json.dumps({
        "run_id": run_id, "path": str(run_dir), "status": "pending",
        "current": version, "next": version, "task_count": task_count,
        "updated_at": datetime.now(CST).isoformat(),
    }, indent=2))


def _ensure_latest_clean(version):
    """确保 latest.json 与 cursor 一致，不清除则重建"""
    latest = _read_latest()
    if not latest or latest.get("current") != version:
        tid = f"align_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"
        run_dir = TASKS_DIR / tid
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tasks").mkdir(exist_ok=True)
        (run_dir / "tasks" / "T001.md").write_text(f"Align {version}")
        (run_dir / "tasks.json").write_text('["T001"]')
        _write_latest(tid, run_dir, version, 1)


def auto_run_once():
    """自动执行器主循环 (RoadmapItem 安全版)"""
    release_lock("completed")

    cursor = get_cursor()
    current = cursor["current_version"]
    cv = get_version(current)

    # 1. Check backlog (before backend, before stale handling)
    if cv is None:
        write_completion("blocked", current, "unknown", remaining_tasks=[current],
                          next_question=f"{current} not in roadmap")
        _ensure_latest_clean(current)
        return {"status": "blocked", "reason": "not_in_roadmap"}

    if cv.trading_mode == "backlog":
        write_completion("blocked", current, current, next_question=f"{current} is backlog",
                          remaining_tasks=[current])
        _ensure_latest_clean(current)
        return {"status": "blocked", "reason": "backlog"}

    if cv.manual_required:
        write_completion("blocked", current, current,
                          next_question=f"{current} requires manual gate: {cv.objective}",
                          remaining_tasks=[current])
        set_blocked(current, cv.objective)
        _ensure_latest_clean(current)
        return {"status": "blocked", "reason": "manual_required"}

    # 2. Check/align latest.json with cursor.current_version (BEFORE backend check)
    latest = _read_latest()
    pending_tasks = None
    if latest:
        if latest.get("current") != current:
            archive_dir = TASKS_DIR / "archive"
            archive_dir.mkdir(exist_ok=True)
            (archive_dir / f"stale_{latest['run_id']}.json").write_text(json.dumps(latest, indent=2))
            pending_tasks = None
        elif latest.get("status") == "pending" and latest.get("task_count", 0) > 0:
            pending_tasks = latest

    if not pending_tasks:
        tid = f"auto_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"
        run_dir = TASKS_DIR / tid
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tasks").mkdir(exist_ok=True)
        task_text = f"Implement {cv.version}: {cv.name} - {cv.objective}"
        (run_dir / "tasks" / "T001.md").write_text(task_text)
        (run_dir / "tasks.json").write_text('["T001"]')
        _write_latest(tid, run_dir, current, 1)
        pending_tasks = {"run_id": tid, "status": "pending"}

    # 3. Check backend (after latest is aligned)
    backend = select_backend("code_change")
    if backend is None:
        # latest is already aligned, safe to block
        write_completion("blocked", current, cv.name,
                          next_question="coding_backend_not_configured",
                          remaining_tasks=[current])
        _ensure_latest_clean(current)
        return {"status": "blocked", "reason": "coding_backend_not_configured"}

    # 5. Execute agent-runner
    try:
        result = subprocess.run(
            [VENV, CLI, "leader:agent-runner", "--once", "--backend", backend],
            capture_output=True, text=True, timeout=60)
        agent_ok = result.returncode == 0
    except subprocess.TimeoutExpired:
        agent_ok = False
    except Exception:
        agent_ok = False

    # 6. Run tests
    test_ok = False
    try:
        r = subprocess.run(
            [VENV, "-m", "pytest", "tests/test_fixed_roadmap.py",
             "tests/test_workloop.py", "tests/test_agent_runner.py",
             "-q", "--tb=short"],
            capture_output=True, text=True, timeout=30,
            cwd="/home/ly/.hermes/research-assistant/commands")
        test_ok = r.returncode == 0
    except Exception:
        test_ok = False

    # 7. Git commit
    commit = ""
    if test_ok:
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"],
                                capture_output=True, text=True,
                                cwd="/home/ly/.hermes/research-assistant")
            commit = r.stdout.strip()
        except Exception:
            pass
        advance(current, "completed", commit=commit)
        nv = next_version(current)
        next_q = f"continue with {nv.version}" if nv else "roadmap complete"
        write_completion("completed", current, cv.name,
                          completed_tasks=[current], remaining_tasks=[],
                          next_question=next_q)
    else:
        advance(current, "failed")
        write_completion("partial", current, cv.name,
                          remaining_tasks=[current],
                          next_question="fix before continuing")

    return {"status": "completed" if test_ok and agent_ok else "partial",
            "version": current, "backend": backend, "commit": commit}
