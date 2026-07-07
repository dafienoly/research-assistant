"""Auto Executor — 连续自动开发执行器 (RoadmapItem 兼容版)"""
import sys, json, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap import get_roadmap, get_version, next_version
from factor_lab.leader.roadmap_cursor import get_cursor, advance, set_blocked
from factor_lab.leader.backend_policy import select_backend, need_code_change
from factor_lab.leader.task_intake import build_task_package
from factor_lab.leader.workloop import write_completion, release_lock, is_locked, TASKS_DIR
from config import VENV_PYTHON, BASE

CST = timezone(timedelta(hours=8))
VENV = VENV_PYTHON
CLI = str(BASE / "commands" / "hermes_cli.py")


def _read_latest():
    p = TASKS_DIR / "latest.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
        return None


def _new_run_id(prefix: str = "auto") -> str:
    return f"{prefix}_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"


def _write_latest(run_id, run_dir, version, task_count):
    (TASKS_DIR / "latest.json").write_text(json.dumps({
        "run_id": run_id, "path": str(run_dir), "status": "pending",
        "current": version, "next": version, "task_count": task_count,
        "updated_at": datetime.now(CST).isoformat(),
    }, indent=2))


def _latest_has_polluted_tasks(latest: dict) -> bool:
    path = Path(latest.get("path", ""))
    tasks_dir = path / "tasks"
    if not tasks_dir.exists():
        return True
    markers = ("some_task", "V2.15", "dry-run", "dry_run", "rebalance_diff", "live_execution")
    for task_file in tasks_dir.glob("*"):
        try:
            text = task_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return True
        if any(marker in task_file.name or marker in text for marker in markers):
            return True
    return False


def _make_roadmap_task(version: str) -> str:
    """生成完整的 roadmap 任务描述"""
    from factor_lab.leader.roadmap import get_version
    v = get_version(version)
    if v:
        return (f"# T001 — {v.name}\n- Version: {v.version}\n- Priority: P1\n"
                f"- Owner: hermes_auto_developer\n- Status: pending\n\n"
                f"## 描述\nImplement {v.version}: {v.name}\nObjective: {v.objective}\n\n"
                f"## 验收标准\n- Implement roadmap item\n- Run tests\n- Produce completion signal\n\n"
                f"## 安全边界\nauto_apply=False, no_live_trade=True")
    return f"# T001 — {version}\n- Version: {version}\n- Priority: P1\n- Owner: hermes_auto_developer\n"


def _ensure_latest_clean(version):
    latest = _read_latest()
    if (not latest or latest.get("current") != version
            or not str(latest.get("run_id", "")).startswith("auto_")
            or _latest_has_polluted_tasks(latest)):
        tid = _new_run_id()
        run_dir = TASKS_DIR / tid
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tasks").mkdir(exist_ok=True)
        (run_dir / "tasks" / "T001.md").write_text(_make_roadmap_task(version))
        (run_dir / "tasks.json").write_text('["T001"]')
        _write_latest(tid, run_dir, version, 1)


def auto_run_once():
    """自动执行器主循环 (RoadmapItem 安全版)"""
    from factor_lab.leader.version_timing import record_start, record_end
    from factor_lab.leader.roadmap_backup import auto_backup
    from factor_lab.leader.version_notify import version_completed, version_blocked, version_failed

    if is_locked():
        return {"status": "running", "reason": "another_agent_run_in_progress"}

    release_lock("completed")

    cursor = get_cursor()
    current = cursor["current_version"]
    if not current:
        # 修复空的 current_version
        from factor_lab.leader.roadmap import get_roadmap
        completed = set(cursor.get("completed_versions", []))
        for item in get_roadmap():
            if item.version not in completed:
                current = item.version
                cursor["current_version"] = current
                from factor_lab.leader.roadmap_cursor import CURSOR_FILE
                import json
                CURSOR_FILE.write_text(json.dumps(cursor, indent=2))
                break

    cv = get_version(current)

    record_start(current)
    auto_backup()

    # 1. Check backlog / manual_required BEFORE creating session
    if cv is None:
        write_completion("blocked", current, "unknown", remaining_tasks=[current],
                          next_question=f"{current} not in roadmap")
        _ensure_latest_clean(current)
        version_blocked(current, "unknown", "不在路线图中")
        return {"status": "blocked", "reason": "not_in_roadmap", "version": current}

    if cv.trading_mode == "backlog":
        write_completion("blocked", current, current, next_question=f"{current} is backlog",
                          remaining_tasks=[current])
        _ensure_latest_clean(current)
        version_blocked(current, cv.name or current, "backlog 版本不自动执行")
        return {"status": "blocked", "reason": "backlog", "version": current}

    if cv.manual_required:
        write_completion("blocked", current, current,
                          next_question=f"{current} requires manual gate: {cv.objective}",
                          remaining_tasks=[current])
        set_blocked(current, cv.objective)
        _ensure_latest_clean(current)
        version_blocked(current, cv.name, cv.objective)
        return {"status": "blocked", "reason": "manual_required", "version": current}

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
        tid = _new_run_id()
        run_dir = TASKS_DIR / tid
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tasks").mkdir(exist_ok=True)
        task_text = f"Implement {cv.version}: {cv.name} - {cv.objective}"
        (run_dir / "tasks" / "T001.md").write_text(task_text)
        (run_dir / "tasks.json").write_text('["T001"]')
        _write_latest(tid, run_dir, current, 1)
        pending_tasks = {"run_id": tid, "status": "pending"}

    # 3. Check backend
    backend = select_backend("code_change")
    if backend is None:
        write_completion("blocked", current, cv.name,
                          next_question="coding_backend_not_configured",
                          remaining_tasks=[current])
        _ensure_latest_clean(current)
        return {"status": "blocked", "reason": "coding_backend_not_configured", "version": current}

    # 4. 创建 Agent Console session — 只有当真正要执行时才创建
    #    检查此版本是否已有 session（防重复创建）
    _created_session = False
    try:
        from factor_lab.agent_console.sessions import create_session as _cs
        from factor_lab.agent_console.sessions import SESSIONS_DIR as _SDIR
        # 检查是否已为此版本创建过 session
        _existing = list(_SDIR.glob("*/request.json"))
        _has_session = False
        for _f in _existing:
            try:
                _r = json.loads(_f.read_text())
                if _r.get("version") == current:
                    _has_session = True
                    break
            except Exception:
                continue
        if not _has_session:
            from factor_lab.agent_console.adapters import start_session as _start_agent
            import threading as _t
            # 根据后端选择相应的 adapter
            _agent_adapter = "claude_code" if backend in ("claude", "command") else "hermes_demo"
            _sid = _cs(_agent_adapter, f"版本 {current}: {cv.name}", version=current)
            _t.Thread(target=_start_agent, args=(_sid, _agent_adapter,
                       f"Auto execute {current}: {cv.name if cv else ''}"), daemon=True).start()
            _created_session = True
    except Exception:
        pass

    # 5. Execute agent-runner
    agent_log_dir = TASKS_DIR / "agent_logs"
    agent_log_dir.mkdir(parents=True, exist_ok=True)
    # 写 status.json 供 dashboard 读取进度
    _run_status_path = agent_log_dir / "status.json"
    try:
        _run_status_path.write_text(json.dumps({
            "stage": "agent", "backend": backend, "version": current, "name": cv.name,
            "status": "running", "started_at": datetime.now(CST).isoformat(),
        }))
    except Exception:
        pass
    agent_ok = False
    agent_error = ""
    try:
        result = subprocess.run(
            [VENV, CLI, "leader:agent-runner", "--once", "--backend", backend],
            capture_output=True, text=True, timeout=3600)
        agent_ok = result.returncode == 0 and "Status: completed" in result.stdout
        if not agent_ok:
            agent_error = f"rc={result.returncode}, stdout_snip={result.stdout[:300]}, stderr_snip={result.stderr[:300]}"
    except subprocess.TimeoutExpired:
        agent_ok = False
        agent_error = "timeout=3600 expired"
    except Exception as e:
        agent_ok = False
        agent_error = f"{type(e).__name__}: {e}"

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

    # 7. Build human-readable summary
    if agent_ok and test_ok:
        commit = ""
        report_path = str(agent_log_dir)
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
                          report_dir=report_path,
                          summary={"passed": 1, "failed": 0,
                                   "note": f"Version {current} completed"},
                          completed_tasks=[current], remaining_tasks=[],
                          next_question=next_q)
        _status = "completed"
        version_completed(current, cv.name, f"{cv.objective} — 测试通过")
        record_end(current, "completed")
        try:
            from factor_lab.leader.version_detail import capture_completion
            capture_completion(current, cv.name)
        except Exception:
            pass
        # 向 Agent Console session 写入 markdown 格式结果
        if _created_session:
            try:
                from factor_lab.agent_console.sessions import append_event, update_status
                from factor_lab.agent_console.schemas import AgentEvent
                _md = f"## ✅ 版本 {current} 完成\n\n- **版本**: {current}\n- **名称**: {cv.name}\n- **状态**: 完成\n- **提交**: {commit}\n- **下一个**: {next_q}\n"
                append_event(_sid, AgentEvent("answer_delta", _sid, data=_md, status="completed"))
                append_event(_sid, AgentEvent("done", _sid, data="", status="completed"))
                update_status(_sid, "completed")
            except Exception:
                pass
    else:
        if _created_session:
            try:
                from factor_lab.agent_console.sessions import append_event, update_status
                from factor_lab.agent_console.schemas import AgentEvent
                _md = f"## ⏳ 版本 {current} 执行中…\n\n- **版本**: {current}\n- **名称**: {cv.name}\n- **状态**: partial (agent_ok={agent_ok}, test_ok={test_ok})\n- **后端**: {backend}\n- **说明**: Agent 执行完成但测试未通过，将在下一 tick 重试\n"
                append_event(_sid, AgentEvent("answer_delta", _sid, data=_md, status="running"))
                append_event(_sid, AgentEvent("done", _sid, data="", status="partial"))
                update_status(_sid, "partial")
            except Exception:
                pass
        write_completion("partial", current, cv.name,
                          report_dir=str(agent_log_dir),
                          summary={"passed": 0, "failed": 1,
                                   "note": f"agent_ok={agent_ok} test_ok={test_ok}",
                                   "agent_error": agent_error},
                          remaining_tasks=[current],
                          next_question="fix before continuing")
        _status = "partial"

    _post_cleanup()
    return {
        "status": _status,
        "version": current,
        "name": cv.name,
        "backend": backend,
        "commit": commit,
        "outcome": "✅ 执行完成，测试通过" if _status == "completed" else "⏳ 测试未通过，下个周期重试",
    }


def _post_cleanup():
    """确保 auto_run_once 后 latest.json 不受污染"""
    import json as _json
    from factor_lab.leader.roadmap_cursor import get_cursor as _gc
    _c = _gc()
    _cv = _c["current_version"]
    _l = _read_latest()
    if _l and _l.get("current") != _cv:
        _archive = TASKS_DIR / "archive"
        _archive.mkdir(exist_ok=True)
        (_archive / f"post_stale_{_l['run_id']}.json").write_text(_json.dumps(_l, indent=2))
        _ensure_latest_clean(_cv)
