"""Legacy Backtest Lab API with fail-visible execution retirement.

VNext verified backtest artifacts remain available from ``/api/vnext/backtests``.
This legacy endpoint must not fabricate metrics while a canonical universe/date/
cost-aware runner is not wired to its request contract.
"""

from fastapi import APIRouter, Path, Query, Request

from factor_lab.api_server.response import api_error, api_success
from factor_lab.api_server.services.audit_service import audit_service
from factor_lab.api_server.services.job_service import job_service


router = APIRouter()


@router.post("/backtests/run")
async def run_backtest(request: Request, body: dict):
    """Reject legacy submissions until a governed canonical runner is integrated."""
    strategy = str(body.get("strategy") or "").strip()
    if not strategy:
        return api_error("INVALID_PARAMS", "strategy 不能为空", status_code=400, request=request)
    audit_service.record(
        event_type="backtest",
        resource="/api/backtests/run",
        action="blocked",
        detail={
            "strategy": strategy[:100],
            "reason": "canonical_backtest_runner_not_integrated",
            "fake_result_generated": False,
        },
    )
    return api_error(
        "BACKTEST_ENGINE_NOT_INTEGRATED",
        "Legacy Backtest Lab 随机执行器已退役；请使用 /api/vnext/backtests 查看已验证回测产物。",
        status_code=503,
        request=request,
    )


@router.get("/backtests")
async def list_backtests(
    request: Request,
    status: str = Query("", description="按状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List only real jobs created by an integrated backtest runner."""
    jobs = [
        job
        for job in job_service.list(status=status or None, limit=limit, offset=offset)
        if job.job_type == "backtest"
    ]
    return api_success(
        data={
            "backtests": [job.to_dict() for job in jobs],
            "total": len(jobs),
            "limit": limit,
            "offset": offset,
            "execution_available": False,
            "reason": "canonical_backtest_runner_not_integrated",
            "verified_artifacts_endpoint": "/api/vnext/backtests",
        },
        request=request,
    )


@router.get("/backtests/{run_id}")
async def get_backtest(request: Request, run_id: str = Path(..., description="回测 run_id")):
    """Return a real in-process job only; never synthesize a missing result."""
    job = job_service.get(run_id)
    if not job or job.job_type != "backtest":
        return api_error("NOT_FOUND", f"回测 {run_id} 不存在", status_code=404, request=request)
    return api_success(data={"backtest": job.to_dict()}, request=request)
