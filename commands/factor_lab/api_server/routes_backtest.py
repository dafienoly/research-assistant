"""回测 (Backtest) API — 提交回测、查询回测结果。"""

from fastapi import APIRouter, Request, Path, Query
from factor_lab.api_server.response import api_success, api_error
from factor_lab.api_server.services.job_service import job_service
from factor_lab.api_server.services.audit_service import audit_service

router = APIRouter()


@router.post("/backtests/run")
async def run_backtest(request: Request, body: dict):
    """提交回测任务。"""
    strategy = body.get("strategy", "")
    universe = body.get("universe", "hs300")
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2026-06-30")
    params = body.get("params", {})

    if not strategy:
        return api_error("INVALID_PARAMS", "strategy 不能为空", status_code=400, request=request)

    job = job_service.create(
        name=f"backtest_{strategy[:30]}",
        job_type="backtest",
        params={"strategy": strategy, "universe": universe, "start_date": start_date, "end_date": end_date, **params},
    )
    job_service.update_status(job.run_id, "running", "回测任务已提交...")
    job_service.update_progress(job.run_id, 0.1, "正在初始化回测引擎...")

    # 模拟回测执行（异步）
    import asyncio

    async def _simulate():
        import random
        await asyncio.sleep(2)
        job_service.update_progress(job.run_id, 0.5, "正在计算因子收益...")
        await asyncio.sleep(2)
        job_service.update_progress(job.run_id, 0.8, "正在生成回测报告...")
        await asyncio.sleep(1)
        sharpe = round(random.uniform(0.5, 2.5), 2)
        cagr = round(random.uniform(5, 30), 1)
        mdd = round(random.uniform(-25, -5), 1)
        job_service.set_result(job.run_id, {
            "sharpe": sharpe,
            "cagr": cagr,
            "max_drawdown": mdd,
            "total_return": round(random.uniform(10, 80), 1),
            "win_rate": round(random.uniform(45, 65), 1),
            "total_trades": random.randint(50, 500),
            "start_date": start_date,
            "end_date": end_date,
        })
        job_service.update_status(job.run_id, "completed", "回测完成")

    asyncio.create_task(_simulate())

    audit_service.record(
        event_type="backtest",
        resource="/api/backtests/run",
        action="execute",
        detail={"run_id": job.run_id, "strategy": strategy[:100], "universe": universe},
        run_id=job.run_id,
    )

    return api_success(data={"job": job.to_dict()}, status_code=202, request=request)


@router.get("/backtests")
async def list_backtests(
    request: Request,
    status: str = Query("", description="按状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出所有回测任务。"""
    jobs = job_service.list(status=status or None, limit=limit, offset=offset)
    # 只返回 backtest 类型的任务
    jobs = [j for j in jobs if j.job_type == "backtest"]
    return api_success(
        data={
            "backtests": [j.to_dict() for j in jobs],
            "total": len(jobs),
            "limit": limit,
            "offset": offset,
        },
        request=request,
    )


@router.get("/backtests/{run_id}")
async def get_backtest(request: Request, run_id: str = Path(..., description="回测 run_id")):
    """查询单个回测结果。"""
    job = job_service.get(run_id)
    if not job:
        return api_error("NOT_FOUND", f"回测 {run_id} 不存在", status_code=404, request=request)
    return api_success(data={"backtest": job.to_dict()}, request=request)
