"""API Agent Console routes — SSE 流式 session"""
import json, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from factor_lab.agent_console.sessions import create_session, get_session, stream_events, SESSIONS_DIR
from factor_lab.agent_console.adapters import start_session
from factor_lab.agent_console.adapters import get_adapters

router = APIRouter()


@router.get("/agent-console/adapters")
async def list_adapters():
    return {"adapters": get_adapters()}


class CreateSessionBody(BaseModel):
    agent: str = "hermes_research"
    prompt: str = ""


@router.post("/agent-console/sessions")
async def create_session_api(body: CreateSessionBody):
    if not body.prompt.strip():
        return JSONResponse({"error": "prompt required"}, status_code=400)
    import threading as _t
    sid = create_session(body.agent, body.prompt)
    _t.Thread(target=start_session, args=(sid, body.agent, body.prompt), daemon=True).start()
    return {"session_id": sid, "status": "running"}


@router.get("/agent-console/sessions")
async def list_sessions(limit: int = 50):
    """列出所有 session，按时间倒序"""
    from factor_lab.agent_console.sessions import SESSIONS_DIR
    sessions = []
    if SESSIONS_DIR.exists():
        for d in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("ac_"):
                summary = {}
                sf = d / "summary.json"
                if sf.exists():
                    summary = json.loads(sf.read_text())
                answer_md = ""
                af = d / "answer.md"
                if af.exists():
                    answer_md = af.read_text()[:500]
                req = {}
                rf = d / "request.json"
                if rf.exists():
                    req = json.loads(rf.read_text())
                # 计算耗时
                duration = ""
                start = req.get("created_at", "")
                end = summary.get("updated_at", "")
                if start and end:
                    try:
                        sd = datetime.fromisoformat(start)
                        ed = datetime.fromisoformat(end)
                        delta = ed - sd
                        duration = f"{delta.total_seconds():.0f}s"
                        if delta.total_seconds() > 3600:
                            duration = f"{delta.total_seconds()/3600:.1f}h"
                        elif delta.total_seconds() > 60:
                            duration = f"{delta.total_seconds()/60:.0f}m"
                    except:
                        pass
                sessions.append({
                    "id": d.name, "status": summary.get("status", "unknown"),
                    "agent": req.get("agent", "?"), "prompt": req.get("prompt", "")[:100],
                    "updated_at": summary.get("updated_at", d.name[3:19]),
                    "answer_preview": answer_md[:200], "duration": duration,
                })
                if len(sessions) >= limit:
                    break
    return {"sessions": sessions}


@router.get("/agent-console/sessions/{sid}")
async def get_session_api(sid: str):
    from factor_lab.agent_console.sessions import get_session
    return get_session(sid)


@router.post("/agent-console/sessions/{sid}/backup")
async def backup_session(sid: str):
    """备份指定 session 到 HermesReports"""
    import shutil
    from pathlib import Path
    src = SESSIONS_DIR / sid
    if not src.exists():
        return {"error": "not found"}
    dst = Path("/mnt/d/HermesReports/session_backups") / sid
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return {"status": "backed_up", "path": str(dst)}


@router.get("/versions/report/detail")
async def version_report_detail():
    """详细版本报告，含 Agent 输出摘要和 git 变更记录"""
    from factor_lab.leader.version_report import generate_report
    report = generate_report()
    # 附上版本完成详情
    from factor_lab.leader.version_detail import get_completion_detail
    detail = get_completion_detail()
    if "error" not in detail:
        report["completion_detail"] = detail
    # 附上最近的 agent_logs 输出
    log_dir = Path("/home/ly/.hermes/research-assistant/agent_tasks/agent_logs")
    logs = []
    if log_dir.exists():
        for f in sorted(log_dir.iterdir(), reverse=True)[:5]:
            if f.is_file():
                logs.append({
                    "file": f.name,
                    "size": f.stat().st_size,
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime, tz=CST).isoformat(),
                    "preview": f.read_text()[:500] if f.stat().st_size < 50000 else "(large)",
                })
    report["agent_outputs"] = logs
    return report


@router.post("/agent-console/cleanup")
async def cleanup_sessions(days: int = 30):
    from factor_lab.agent_console.sessions import cleanup_sessions as _clean
    count = _clean(days)
    return {"cleaned": count, "retention_days": days}


@router.get("/agent-console/backups")
async def list_backups():
    from factor_lab.agent_console.sessions import list_backups as _lb
    return {"backups": _lb()}


@router.post("/agent-console/backups/{backup_id}/restore")
async def restore_backup(backup_id: str):
    from factor_lab.agent_console.sessions import restore_backup as _rb
    result = _rb(backup_id)
    if "error" in result:
        from fastapi.responses import JSONResponse
        return JSONResponse(result, status_code=404)
    return result


@router.get("/agent-console/sessions/{sid}/stream")
async def stream_session(sid: str):
    async def event_gen():
        last_count = 0
        while True:
            el = SESSIONS_DIR / sid / "events.jsonl"
            if el.exists():
                lines = el.read_text().splitlines()
                for line in lines[last_count:]:
                    yield f"data: {line}\n\n"
                    last_count += 1
                if lines and '"done"' in lines[-1]:
                    break
            await asyncio.sleep(0.3)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/agent-console/sessions/{sid}/cancel")
async def cancel_session_api(sid: str):
    from factor_lab.agent_console.adapters import cancel_session
    cancel_session(sid)
    return {"status": "cancelled"}
