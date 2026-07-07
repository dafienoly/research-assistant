"""API Roadmap routes — 路线图查看与编辑，含系列分组与进度统计"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from factor_lab.leader.roadmap import get_roadmap, get_version, ALPHA_FACTORY_ROADMAP, is_backlog
from factor_lab.leader.roadmap_cursor import get_cursor, advance, set_blocked

router = APIRouter()


def _get_series(version: str) -> str:
    if version.startswith("V3"):
        return "V3 Alpha Factory"
    if version.startswith("V4"):
        return "V4 Controlled Execution"
    if version.startswith("V5"):
        return "V5 Data Platform"
    if version.startswith("V6"):
        return "V6 Research Automation"
    if version.startswith("V7"):
        return "V7 Product UI/Ops"
    if version.startswith("V8"):
        return "V8 Multi-Agent Engineering"
    if version.startswith("V9"):
        return "V9 Future Backlog"
    return "Other"


def _compute_status(version: str, cursor: dict) -> str:
    if version in cursor.get("completed_versions", []):
        return "completed"
    if version in cursor.get("failed_versions", []):
        return "failed"
    if version == cursor.get("current_version", ""):
        return "current"
    return "pending"


def _compute_progress(items: list[dict]) -> dict:
    series_map: dict[str, dict] = {}
    total, completed, failed, current, pending, backlog = 0, 0, 0, 0, 0, 0
    for item in items:
        s = item["series"]
        if s not in series_map:
            series_map[s] = {"key": s, "name": s, "total": 0, "completed": 0, "failed": 0, "current": 0, "pending": 0}
        series_map[s]["total"] += 1
        total += 1
        if item["status"] == "completed":
            series_map[s]["completed"] += 1
            completed += 1
        elif item["status"] == "failed":
            series_map[s]["failed"] += 1
            failed += 1
        elif item["status"] == "current":
            series_map[s]["current"] += 1
            current += 1
        else:
            series_map[s]["pending"] += 1
            pending += 1
        if item.get("backlog"):
            backlog += 1

    for s in series_map.values():
        s["percent"] = round((s["completed"] / s["total"]) * 100, 1) if s["total"] else 0

    active_total = total - backlog
    completed_active = completed
    percent = round((completed_active / active_total) * 100, 1) if active_total else 0

    return {
        "total_versions": total,
        "completed": completed,
        "failed": failed,
        "current": current,
        "pending": pending,
        "backlog": backlog,
        "percent": percent,
        "series": sorted(series_map.values(), key=lambda x: x["key"]),
    }


@router.get("/roadmap")
async def get_roadmap_api():
    items = []
    for item in ALPHA_FACTORY_ROADMAP:
        d = {
            "version": item.version, "name": item.name, "objective": item.objective,
            "auto_allowed": item.auto_allowed, "manual_required": item.manual_required,
            "trading_mode": item.trading_mode, "backlog": is_backlog(item.version),
            "series": _get_series(item.version),
        }
        items.append(d)
    return {"items": items, "progress": _compute_progress(items)}


@router.get("/roadmap/versions")
async def get_versions():
    cursor = get_cursor()
    items = []
    for item in ALPHA_FACTORY_ROADMAP:
        v = item.version
        status = _compute_status(v, cursor)
        items.append({
            "version": v, "name": item.name, "objective": item.objective,
            "status": status, "auto_allowed": item.auto_allowed,
            "manual_required": item.manual_required, "trading_mode": item.trading_mode,
            "series": _get_series(v),
            "backlog": is_backlog(v),
        })
    progress = _compute_progress(items)
    return {"versions": items, "cursor": cursor, "progress": progress}


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
