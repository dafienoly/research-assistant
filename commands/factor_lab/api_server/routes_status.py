"""API Status routes — 版本状态 + Agent Console 核心"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from factor_lab.api_server.response import api_success
from factor_lab.leader.auto_health import health
from factor_lab.leader.roadmap_cursor import get_cursor
from factor_lab.leader.workloop import read_completion, TASKS_DIR
from factor_lab.leader.version_report import generate_report
from factor_lab.leader.backend_policy import policy_status
from factor_lab.leader.dashboard import _roadmap_details, _agent_output_snapshot

import json

router = APIRouter()


@router.get("/status")
async def get_status():
    h = health()
    cursor = get_cursor()
    completion = read_completion()
    latest = {}
    lp = TASKS_DIR / "latest.json"
    if lp.exists():
        latest = json.loads(lp.read_text())
    report = generate_report()
    be = policy_status()
    return api_success(data={
        "state": {"level": "green" if h.get("lock_status") == "free" else "red"},
        "health": h,
        "cursor": cursor,
        "latest": latest,
        "latest_completion": completion,
        "roadmap_details": _roadmap_details(),
        "roadmap_progress": {
            "current": cursor.get("current_version", ""),
            "completed": len(cursor.get("completed_versions", [])),
        },
        "backend": be,
        "report": report,
    })


@router.get("/agent-output")
async def get_agent_output(lines: int = 100):
    latest = {}
    completion = read_completion()
    lp = TASKS_DIR / "latest.json"
    if lp.exists():
        latest = json.loads(lp.read_text())
    return _agent_output_snapshot(latest, completion, lines=lines)
