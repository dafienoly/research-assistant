"""Agent Console Sessions — 会话管理"""
import json, os, uuid
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
    # Write request
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
    return {"session_id": sid, "events": events[-200:], "answer": answer}


def append_event(sid: str, event: AgentEvent):
    sdir = SESSIONS_DIR / sid
    if not sdir.exists():
        return
    # events.jsonl
    with open(sdir / "events.jsonl", "a") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    # answer.md
    if event.type == "answer_delta" and event.data:
        with open(sdir / "answer.md", "a") as f:
            f.write(event.data)


def update_status(sid: str, status: str):
    sdir = SESSIONS_DIR / sid
    if sdir.exists():
        (sdir / "summary.json").write_text(json.dumps(
            {"session_id": sid, "status": status, "updated_at": datetime.now(CST).isoformat()}, indent=2))


def stream_events(sid: str, start_line: int = 0):
    """生成 SSE events"""
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
