"""Agent Console Sessions — 会话管理 (V3: 版本关联 + 备份恢复 + 生命周期)"""
import json, os, uuid, subprocess, shutil, atexit
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.agent_console.schemas import AgentEvent, SessionState

CST = timezone(timedelta(hours=8))
SESSIONS_DIR = Path("/home/ly/.hermes/research-assistant/agent_tasks/agent_console_sessions")
BACKUP_DIR = Path("/mnt/d/HermesReports/session_backups")


def _sid() -> str:
    return f"ac_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def create_session(agent: str, prompt: str, version: str = "") -> str:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sid = _sid()
    sdir = SESSIONS_DIR / sid
    sdir.mkdir()
    state = SessionState(session_id=sid, agent=agent, prompt=prompt,
                         status="pending", created_at=datetime.now(CST).isoformat())
    req = {"agent": agent, "prompt": prompt, "version": version, "created_at": state.created_at}
    (sdir / "request.json").write_text(json.dumps(req, indent=2))
    return sid


def get_session(sid: str) -> dict:
    sdir = SESSIONS_DIR / sid
    if not sdir.exists():
        return {"error": "not found"}
    events = []
    el = sdir / "events.jsonl"
    if el.exists():
        events = [json.loads(l) for l in el.read_text().splitlines()]
    answer = ""
    am = sdir / "answer.md"
    if am.exists():
        answer = am.read_text()
    diagnostics = [e["data"] for e in events if e.get("type") == "diagnostic"]
    summary = {}
    sf = sdir / "summary.json"
    if sf.exists():
        summary = json.loads(sf.read_text())
    req = {}
    rf = sdir / "request.json"
    if rf.exists():
        req = json.loads(rf.read_text())
    start = req.get("created_at", "")
    end = summary.get("updated_at", "")
    duration = _calc_duration(start, end)
    return {
        "session_id": sid, "events": events[-200:], "answer": answer,
        "diagnostics": diagnostics[-50:], "duration": duration or "—",
        "status": summary.get("status", "unknown"),
        "agent": req.get("agent", "?"), "prompt": req.get("prompt", "")[:200],
        "version": req.get("version", "") or "—",
        "git_commit": _last_git_commit() or "—", "created_at": req.get("created_at", ""),
    }


def _calc_duration(start: str, end: str) -> str:
    if not start or not end:
        return ""
    try:
        sd = datetime.fromisoformat(start)
        ed = datetime.fromisoformat(end)
        delta = ed - sd
        s = delta.total_seconds()
        if s > 3600: return f"{s/3600:.1f}h"
        if s > 60: return f"{s/60:.0f}m"
        return f"{s:.0f}s"
    except:
        return ""


def _last_git_commit() -> str:
    try:
        r = subprocess.run(["git", "log", "-1", "--oneline"],
                           capture_output=True, text=True, timeout=5,
                           cwd="/home/ly/.hermes/research-assistant")
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def append_event(sid: str, event: AgentEvent):
    sdir = SESSIONS_DIR / sid
    if not sdir.exists():
        return
    with open(sdir / "events.jsonl", "a") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    if event.type == "answer_delta" and event.data:
        with open(sdir / "answer.md", "a") as f:
            f.write(event.data)


def update_status(sid: str, status: str, agent: str = "", prompt: str = ""):
    sdir = SESSIONS_DIR / sid
    if sdir.exists():
        data = {"session_id": sid, "status": status, "updated_at": datetime.now(CST).isoformat()}
        if agent: data["agent"] = agent
        if prompt: data["prompt"] = prompt
        (sdir / "summary.json").write_text(json.dumps(data, indent=2))


def cleanup_sessions(days: int = 30):
    now = datetime.now(CST)
    count = 0
    for d in sorted(SESSIONS_DIR.iterdir()):
        if d.is_dir() and d.name.startswith("ac_"):
            sf = d / "summary.json"
            if sf.exists():
                try:
                    data = json.loads(sf.read_text())
                    updated = datetime.fromisoformat(data.get("updated_at", ""))
                    if (now - updated).days > days:
                        shutil.rmtree(d)
                        count += 1
                except:
                    continue
    return count


def list_backups() -> list:
    """列出所有已备份的 session"""
    backups = []
    if BACKUP_DIR.exists():
        for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("ac_"):
                req = {}
                rf = d / "request.json"
                if rf.exists():
                    req = json.loads(rf.read_text())
                summary = {}
                sf = d / "summary.json"
                if sf.exists():
                    summary = json.loads(sf.read_text())
                backups.append({
                    "id": d.name, "version": req.get("version", "") or "—",
                    "agent": req.get("agent", "?"), "prompt": req.get("prompt", "")[:100],
                    "status": summary.get("status", "unknown"),
                    "backed_up_at": datetime.fromtimestamp(d.stat().st_mtime, tz=CST).isoformat(),
                })
    return backups


def restore_backup(backup_id: str) -> dict:
    """从备份恢复 session"""
    src = BACKUP_DIR / backup_id
    if not src.exists():
        return {"error": f"备份 {backup_id} 不存在"}
    dst = SESSIONS_DIR / backup_id
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return {"status": "restored", "session_id": backup_id}


def stream_events(sid: str, start_line: int = 0):
    el = SESSIONS_DIR / sid / "events.jsonl"
    if not el.exists():
        return
    lines = el.read_text().splitlines()
    for line in lines[start_line:]:
        try:
            evt = json.loads(line)
            event = AgentEvent(**evt)
            yield event.to_sse()
        except Exception:
            continue


# ─── Daemon thread lifecycle ───────────────────────────────────

def write_lifecycle(sid: str, agent: str, prompt: str, status: str = "running"):
    """标记 daemon session 的生命周期状态，进程退出后可检测 orphaned。"""
    import os as _os
    sdir = SESSIONS_DIR / sid
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "lifecycle.json").write_text(json.dumps({
        "pid": _os.getpid(),
        "status": status,
        "agent": agent,
        "prompt": prompt[:200],
        "created_at": datetime.now(CST).isoformat(),
    }, indent=2))


@atexit.register
def _mark_orphaned_sessions():
    """进程退出前将所有 running daemon session 标记为 orphaned。"""
    if not SESSIONS_DIR.exists():
        return
    orphaned = 0
    for d in sorted(SESSIONS_DIR.iterdir()):
        if not d.is_dir():
            continue
        lf = d / "lifecycle.json"
        if not lf.exists():
            continue
        try:
            state = json.loads(lf.read_text())
            if state.get("status") == "running":
                state["status"] = "orphaned"
                state["orphaned_at"] = datetime.now(CST).isoformat()
                lf.write_text(json.dumps(state, indent=2))
                orphaned += 1
        except Exception:
            continue
    if orphaned:
        print(f"[sessions] marked {orphaned} session(s) as orphaned on shutdown")
