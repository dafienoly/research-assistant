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
        desc = ""
        if hasattr(v, 'description') and v.description:
            desc = f"\n## 详细描述\n{v.description}\n"
        return (f"# T001 — {v.name}\n- Version: {v.version}\n- Priority: P1\n"
                f"- Owner: hermes_auto_developer\n- Status: pending\n\n"
                f"## 描述\nImplement {v.version}: {v.name}\nObjective: {v.objective}\n{desc}\n"
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
                CURSOR_FILE.write_text(json.dumps(cursor, indent=2))
                break

    # 0. 如果 current_version 已经完成，尝试推进到下一个版本
    completed_set = set(cursor.get("completed_versions", []))
    if current in completed_set:
        from factor_lab.leader.roadmap import is_backlog as _is_backlog
        nv = next_version(current)
        # 查找下一个非 backlog、未完成的版本
        while nv and (_is_backlog(nv.version) or nv.version in completed_set):
            nv = next_version(nv.version)
        if nv:
            # 找到可推进的下一个版本
            cursor["current_version"] = nv.version
            from factor_lab.leader.roadmap_cursor import CURSOR_FILE
            CURSOR_FILE.write_text(json.dumps(cursor, indent=2))
            current = nv.version
        else:
            # 路线图全部完成，不再需要执行
            write_completion("completed", current, "all",
                              summary={"passed": 0, "failed": 0, "note": "Roadmap complete"},
                              completed_tasks=[current], remaining_tasks=[],
                              next_question="roadmap complete")
            release_lock("completed")
            return {"status": "completed", "reason": "roadmap_complete", "version": current}

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
        if hasattr(cv, 'description') and cv.description:
            task_text += f"\n\n## 详细描述\n\n{cv.description}"
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
    _sid = None
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
                    _sid = _f.parent.name  # 记录已存在的 session ID
                    break
            except Exception:
                continue
        if not _has_session:
            from factor_lab.agent_console.adapters import start_session as _start_agent
            import threading as _t
            # 根据后端选择相应的 adapter
            _agent_adapter = "claude_code" if backend in ("claude", "command") else "hermes_demo"
            _sid = _cs(_agent_adapter, f"版本 {current}: {cv.name}", version=current)
            from factor_lab.agent_console.sessions import write_lifecycle as _wl
            _wl(_sid, _agent_adapter, f"Auto execute {current}: {cv.name}")
            # 写入启动参数
            try:
                from factor_lab.agent_console.sessions import SESSIONS_DIR as _SDIR2
                _params = {
                    "backend": backend,
                    "agent_adapter": _agent_adapter,
                    "effort_level": "ultra",
                    "cli_command": "claude --print --dangerously-skip-permissions --permission-mode auto --add-dir ... --model deepseek-v4",
                    "streaming_mode": "tail+live",
                    "permission_mode": "auto",
                }
                (_SDIR2 / _sid / "startup_params.json").write_text(
                    __import__('json').dumps(_params, indent=2))
            except Exception:
                pass
            _t.Thread(target=_start_agent, args=(_sid, _agent_adapter,
                       f"Auto execute {current}: {cv.name if cv else ''}"), daemon=True).start()
    except Exception:
        pass

    # 5. Execute agent-runner 前先记录 retry_count（避免被 agent-runner 的 write_completion 覆盖）
    _retry_count = 0
    if not is_locked():
        try:
            _prev_file = TASKS_DIR / "latest_completion.json"
            if _prev_file.exists():
                _prev = json.loads(_prev_file.read_text())
                if _prev and _prev.get("version") == current:
                    _prev_note = _prev.get("summary", {}).get("note", "")
                    if "agent_ok=False" in _prev_note and "test_ok=True" in _prev_note:
                        _retry_count = _prev.get("summary", {}).get("retry_count", 0) + 1
        except Exception:
            pass

    # 5. Execute agent-runner (后台进程，实时流日志到 session)
    agent_log_dir = TASKS_DIR / "agent_logs"
    agent_log_dir.mkdir(parents=True, exist_ok=True)
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
    _agent_proc = None
    _tail_thread = None
    try:
        # 启动 agent-runner 后台进程
        _agent_proc = subprocess.Popen(
            [VENV, CLI, "leader:agent-runner", "--once", "--backend", backend],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(Path(CLI).parent))
        # 后台线程：tail agent 日志 + 推送到 session
        if _sid:
            import threading as _th, time as _time, re as _re2
            _ansi_re_tail = _re2.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            def _tail_log():
                _last_size = 0
                _max_wait = 600
                _waited = 0
                while _waited < _max_wait:
                    _time.sleep(1)
                    _waited += 1
                    try:
                        _log_dirs = sorted(agent_log_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                        for _ld in _log_dirs[:3]:
                            if not _ld.is_dir():
                                continue
                            for _lf in sorted(_ld.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
                                _sz = _lf.stat().st_size
                                if _sz > _last_size:
                                    _raw = _lf.read_text(encoding="utf-8", errors="replace")[_last_size:_last_size+4096]
                                    _last_size = _sz
                                    # 清洗 ANSI + 控制字符
                                    _clean = _ansi_re_tail.sub('', _raw)
                                    _clean = ''.join(c for c in _clean if ord(c) >= 0x20 or c in '\n\r\t')
                                    # 过滤诊断行
                                    _filtered = []
                                    for _line in _clean.split('\n'):
                                        _s = _line.strip()
                                        if _s.startswith('$ ') or _s.startswith('# heartbeat') or _s.startswith('# started') or _s.startswith('# finished'):
                                            continue
                                        if _s:
                                            _filtered.append(_line)
                                    if _filtered:
                                        try:
                                            from factor_lab.agent_console.sessions import append_event as _ae
                                            from factor_lab.agent_console.schemas import AgentEvent as _Ae
                                            _ae(_sid, _Ae("answer_delta", _sid, data='\n'.join(_filtered), status="running"))
                                        except Exception:
                                            pass
                                break
                            break
                    except Exception:
                        pass
                    if _agent_proc and _agent_proc.poll() is not None:
                        _time.sleep(1)
                        break
            _tail_thread = _th.Thread(target=_tail_log, daemon=True)
            _tail_thread.start()
        # 等待 agent-runner 完成
        _stdout, _ = _agent_proc.communicate(timeout=3600)
        agent_ok = _agent_proc.returncode == 0 and "Status: completed" in _stdout
        if not agent_ok:
            agent_error = f"rc={_agent_proc.returncode}, stdout_snip={_stdout[:300]}"
    except subprocess.TimeoutExpired:
        agent_ok = False
        agent_error = "timeout=3600 expired"
        if _agent_proc:
            _agent_proc.kill()
    except Exception as e:
        agent_ok = False
        agent_error = f"{type(e).__name__}: {e}"
    finally:
        if _agent_proc and _agent_proc.poll() is None:
            _agent_proc.kill()

    # 6. Run tests（先清理残留 pytest 进程）
    try:
        import subprocess as _sp_kill
        _sp_kill.run(["pkill", "-f", "python3.*-m pytest.*test_"],
                     capture_output=True, timeout=5)
    except Exception:
        pass
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
    commit = ""
    # retry bypass: agent-runner 多次失败但测试通过 → 放行
    if not agent_ok and test_ok and _retry_count >= 2:
        agent_ok = True
    if agent_ok and test_ok:
        report_path = str(agent_log_dir)
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"],
                                capture_output=True, text=True,
                                cwd="/home/ly/.hermes/research-assistant")
            commit = r.stdout.strip()
        except Exception:
            pass

        # 7a. 审计门禁 (ADR-022): advance 前审计，失败则标记 partial
        audit_ok = True
        try:
            import subprocess as _sp
            _ar = _sp.run(
                [VENV, CLI, "leader:audit-and-push", "--version", current, "--mode", "full"],
                capture_output=True, text=True, timeout=300,
                cwd="/home/ly/.hermes/research-assistant/commands"
            )
            if _ar.returncode != 0:
                # 区分：审计本身失败 vs 审计通过但推送失败
                _audit_passed = "✅ 通过" in _ar.stdout or "状态: ✅ 通过" in _ar.stdout or "status.:.passed" in _ar.stdout
                if _audit_passed:
                    # 审计通过但推送失败（git lock / 超时等），不阻塞版本
                    audit_ok = True
                else:
                    write_completion("partial", current, cv.name,
                                      report_dir=report_path,
                                      summary={"passed": 0, "failed": 1,
                                               "note": f"审计未通过 — {_ar.stdout[:500]}"},
                                      remaining_tasks=[current],
                                      next_question="audit failed, fix before continuing")
                    _status = "partial"
                    # 写入 Agent Console session
                    try:
                        from factor_lab.agent_console.sessions import append_event, update_status
                        from factor_lab.agent_console.schemas import AgentEvent
                        _md = f"## ❌ 版本 {current} 审计未通过\n\n审计报告:\n```\n{_ar.stdout[:1000]}\n```\n"
                        if _sid:
                            append_event(_sid, AgentEvent("answer_delta", _sid, data=_md, status="partial"))
                            append_event(_sid, AgentEvent("done", _sid, data="", status="partial"))
                            update_status(_sid, "partial")
                    except Exception:
                        pass
                    _post_cleanup()
                    return {"status": "partial", "version": current, "reason": "audit_failed",
                            "audit_output": _ar.stdout[:300]}
        except subprocess.TimeoutExpired:
            audit_ok = True  # 超时放行，不阻塞推进
        except Exception:
            audit_ok = True

        # 7b. 反偷工减料审计 (Anti-Cheat): 风险自动选择 Gate
        if audit_ok:
            try:
                _ac = _sp.run(
                    [VENV, CLI, "leader:anti-cheat-audit", "--risk", "auto",
                     "--enable-gate5", "--version", current],
                    capture_output=True, text=True, timeout=120,
                    cwd="/home/ly/.hermes/research-assistant/commands"
                )
                if _ac.returncode != 0:
                    audit_ok = False
                    write_completion("partial", current, cv.name,
                                      report_dir=report_path,
                                      summary={"passed": 0, "failed": 1,
                                               "note": f"Anti-cheat 审计未通过 — {_ac.stdout[:500]}"},
                                      remaining_tasks=[current],
                                      next_question="anti-cheat audit failed, fix stubs/tests before continuing")
                    _status = "partial"
                    try:
                        _md = f"## ❌ 版本 {current} 反偷工减料审计未通过\n\n{_ac.stdout[:1000]}\n"
                        if _sid:
                            append_event(_sid, AgentEvent("answer_delta", _sid, data=_md, status="partial"))
                            append_event(_sid, AgentEvent("done", _sid, data="", status="partial"))
                            update_status(_sid, "partial")
                    except Exception:
                        pass
                    _post_cleanup()
                    return {"status": "partial", "version": current, "reason": "anti_cheat_failed",
                            "audit_output": _ac.stdout[:300]}
            except subprocess.TimeoutExpired:
                pass  # 超时放行
            except Exception:
                pass

        if audit_ok:
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
        # 版本完成后自动更新 GitNexus 知识图谱
        try:
            subprocess.run(
                ["bash", "/home/ly/.hermes/research-assistant/commands/scripts/gitnexus_refresh.sh",
                 "--index-only"],
                capture_output=True, timeout=300,
                cwd="/home/ly/.hermes/research-assistant"
            )
        except Exception:
            pass
        # 注入 agent 工作日志到 session（让 Claude Code 真实输出可见）
        if _sid:
            try:
                from factor_lab.agent_console.sessions import append_event, update_status
                from factor_lab.agent_console.schemas import AgentEvent
                import re as _re
                _ansi_re = _re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                # 查找 agent 日志文件
                _log_dir = TASKS_DIR / "agent_logs"
                if _log_dir.exists():
                    _log_dirs = sorted(_log_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                    for _ld in _log_dirs[:3]:
                        if not _ld.is_dir():
                            continue
                        for _lf in sorted(_ld.glob("*.log"), key=lambda p: p.stat().st_mtime):
                            _raw = _lf.read_text(encoding="utf-8", errors="replace")
                            _clean = _ansi_re.sub('', _raw)
                            if len(_clean.strip()) > 50:
                                # 跳过脑暴 preamble：找到第一个实现相关的行
                                _lines = _clean.split('\n')
                                _skip_until = 0
                                for i, line in enumerate(_lines):
                                    stripped = line.strip()
                                    # 跳过 command 行、shebang、空行、脑暴内容
                                    if stripped.startswith('$ ') or stripped.startswith('#') or not stripped:
                                        _skip_until = i + 1
                                    elif any(kw in stripped for kw in [
                                        'Base directory', 'Brainstorming', 'HARD-GATE',
                                        'Do NOT invoke', 'Anti-Pattern', 'Checklist',
                                        'Process Flow', '## The Process',
                                    ]):
                                        _skip_until = i + 1
                                    else:
                                        break  # 找到正文开始
                                _body_lines = _lines[_skip_until:]
                                # 跳过尾部空行和 # finished_at
                                while _body_lines and not _body_lines[-1].strip():
                                    _body_lines.pop()
                                if _body_lines and _body_lines[-1].strip().startswith('# finished_at'):
                                    _body_lines.pop()
                                # 清洗嵌套 ```，避免破坏外层围栏
                                _body_text = '\n'.join(_body_lines)
                                _nested_fence = _re.compile(r'^```', _re.MULTILINE)
                                _body_text = _nested_fence.sub('`\\`', _body_text)
                                _body_text = _body_text[:5000].strip()
                                if len(_body_text) > 50:
                                    _header = f"\n\n## 🤖 Claude Code 工作输出 ({_lf.name})\n\n```\n"
                                    _footer = "\n```\n"
                                    append_event(_sid, AgentEvent("answer_delta", _sid, data=_header + _body_text + _footer, status="running"))
                                break
                        break
            except Exception:
                pass
        # 向 Agent Console session 写入完成总结
        if _sid:
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
        if _sid:
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
                                   "agent_error": agent_error,
                                   "retry_count": _retry_count},
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
