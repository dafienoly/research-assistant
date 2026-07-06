"""Agent Console Sessions — 会话管理 (增强版)"""
import json, os, uuid, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.agent_console.schemas import AgentEvent, SessionState

CST = timezone(timedelta(hours=8))
SESSIONS_DIR = Path("/home/ly/.hermes/research-assistant/agent_tasks/agent_console_sessions")


def _sid() -> str:
    return f"ac_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def create_session(agent: str, prompt: str) -> str:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sid = _sid()
    sdir = SESSIONS_DIR / sid
    sdir.mkdir()
    state = SessionState(session_id=sid, agent=agent, prompt=prompt,
                         status="pending", created_at=datetime.now(CST).isoformat())
    (sdir / "request.json").write_text(json.dumps({"agent": agent, "prompt": prompt,
                                                    "created_at": state.created_at}, indent=2))
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
    # 耗时
    start = req.get("created_at", "")
    end = summary.get("updated_at", "")
    duration = ""
    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            delta = end_dt - start_dt
            duration = f"{delta.total_seconds():.0f}s"
            if delta.total_seconds() > 3600:
                duration = f"{delta.total_seconds()/3600:.1f}h"
            elif delta.total_seconds() > 60:
                duration = f"{delta.total_seconds()/60:.0f}m"
        except:
            pass
    return {
        "session_id": sid, "events": events[-200:], "answer": answer,
        "diagnostics": diagnostics[-50:], "duration": duration,
        "status": summary.get("status", "unknown"),
        "agent": req.get("agent", "?"), "prompt": req.get("prompt", "")[:200],
        "git_commit": _last_git_commit(), "created_at": req.get("created_at", ""),
    }


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
        if agent:
            data["agent"] = agent
        if prompt:
            data["prompt"] = prompt
        (sdir / "summary.json").write_text(json.dumps(data, indent=2))


def cleanup_sessions(days: int = 30):
    """清理超过指定天数的 session"""
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
                        import shutil
                        shutil.rmtree(d)
                        count += 1
                except:
                    continue
    return count


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
