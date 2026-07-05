"""API Agent Console routes — SSE 流式 session"""
import json, asyncio
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


@router.get("/agent-console/sessions/{sid}")
async def get_session_api(sid: str):
    return get_session(sid)


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
