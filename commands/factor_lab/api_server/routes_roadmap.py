"""API Roadmap routes — 路线图查看与编辑"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from factor_lab.leader.roadmap import get_roadmap, get_version, ALPHA_FACTORY_ROADMAP
from factor_lab.leader.roadmap_cursor import get_cursor, advance, set_blocked
from factor_lab.leader.dashboard import _roadmap_details

router = APIRouter()


@router.get("/roadmap")
async def get_roadmap_api():
    return {"items": _roadmap_details()}


@router.get("/roadmap/versions")
async def get_versions():
    cursor = get_cursor()
    items = []
    for item in ALPHA_FACTORY_ROADMAP:
        v = item.version
        status = "completed" if v in cursor.get("completed_versions", []) else \
                 "failed" if v in cursor.get("failed_versions", []) else \
                 "current" if v == cursor.get("current_version", "") else \
                 "pending"
        items.append({
            "version": v, "name": item.name, "objective": item.objective,
            "status": status, "auto_allowed": item.auto_allowed,
            "manual_required": item.manual_required, "trading_mode": item.trading_mode,
        })
    return {"versions": items, "cursor": cursor}


class MarkVersion(BaseModel):
    version: str
    status: str  # completed / failed / skip / reset


@router.post("/roadmap/versions/mark")
async def mark_version(body: MarkVersion):
    if body.status == "completed":
        advance(body.version, "completed")
    elif body.status == "failed":
        advance(body.version, "failed")
    elif body.status == "reset":
        # 重置到指定版本
        c = get_cursor()
        c["current_version"] = body.version
        c["status"] = "running"
        from factor_lab.leader.roadmap_cursor import CURSOR_FILE
        import json
        CURSOR_FILE.write_text(json.dumps(c, indent=2))
    return {"status": "ok"}
