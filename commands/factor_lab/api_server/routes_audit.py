"""审计日志 API — 事件查询和操作审计追踪。"""

from fastapi import APIRouter, Request, Path, Query
from factor_lab.api_server.response import api_success, api_error
from factor_lab.api_server.services.audit_service import audit_service

router = APIRouter()


@router.get("/audit/events")
async def list_audit_events(
    request: Request,
    event_type: str = Query("", description="按事件类型过滤: api_call/job_run/backtest/portfolio/config_change/error"),
    outcome: str = Query("", description="按结果过滤: success/failure/pending"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """查询审计日志事件列表。"""
    events, total = audit_service.list(
        event_type=event_type or None,
        outcome=outcome or None,
        limit=limit,
        offset=offset,
    )
    return api_success(
        data={
            "events": [e.model_dump() for e in events],
            "total": total,
            "limit": limit,
            "offset": offset,
            "stats": audit_service.get_stats(),
        },
        request=request,
    )


@router.get("/audit/run/{run_id}")
async def get_audit_by_run(request: Request, run_id: str = Path(..., description="任务 run_id")):
    """查询指定 run_id 的审计事件。"""
    events = audit_service.get_by_run_id(run_id)
    if not events:
        return api_success(data={"events": [], "total": 0}, request=request)
    return api_success(
        data={"events": [e.model_dump() for e in events], "total": len(events)},
        request=request,
    )


@router.get("/audit/export")
async def export_audit_events(request: Request, limit: int = Query(1000, ge=1, le=10000)):
    """Export the operational ledger; code audit reports use /code-audits."""
    events, total = audit_service.list(limit=limit)
    return api_success(
        data={"events": [event.model_dump() for event in events], "total": total},
        request=request,
    )
