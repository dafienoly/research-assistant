"""任务管理 API — 后台任务提交、状态查询、流式输出。"""

from fastapi import APIRouter, Request, Path, Query
from factor_lab.api_server.response import api_success, api_error
from factor_lab.api_server.services.job_service import job_service
from factor_lab.api_server.services.command_runner import CommandRunner
from factor_lab.api_server.services.audit_service import audit_service

router = APIRouter()
runner = CommandRunner()


@router.get("/jobs")
async def list_jobs(
    request: Request,
    status: str = Query("", description="按状态过滤: pending/running/completed/failed/cancelled"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出所有任务，支持状态过滤和分页。"""
    jobs = job_service.list(status=status or None, limit=limit, offset=offset)
    total = job_service.count(status=status or None)
    return api_success(
        data={"jobs": [j.to_dict() for j in jobs], "total": total, "limit": limit, "offset": offset},
        request=request,
    )


@router.post("/jobs")
async def create_job(request: Request, body: dict):
    """创建新任务。"""
    name = body.get("name", "untitled")
    job_type = body.get("job_type", "generic")
    params = body.get("params", {})
    job = job_service.create(name=name, job_type=job_type, params=params)
    audit_service.record(
        event_type="job_run",
        resource="/api/jobs",
        action="create",
        detail={"run_id": job.run_id, "name": name, "job_type": job_type},
        run_id=job.run_id,
        ip_address=request.client.host if request.client else "",
    )
    return api_success(data={"job": job.to_dict()}, status_code=201, request=request)


@router.get("/jobs/{run_id}")
async def get_job(request: Request, run_id: str = Path(..., description="任务 run_id")):
    """查询单个任务状态。"""
    job = job_service.get(run_id)
    if not job:
        return api_error("NOT_FOUND", f"任务 {run_id} 不存在", status_code=404, request=request)
    return api_success(data={"job": job.to_dict()}, request=request)


@router.post("/jobs/run")
async def run_job(request: Request, body: dict):
    """提交并立即执行 CLI 命令任务。返回 run_id，异步执行。"""
    command = body.get("command", "")
    name = body.get("name", command[:60])
    job_type = body.get("job_type", "cli")
    cwd = body.get("cwd")
    params = body.get("params", {})

    if not command:
        return api_error("INVALID_PARAMS", "command 不能为空", status_code=400, request=request)

    import asyncio
    job = job_service.create(name=name, job_type=job_type, params={**params, "command": command, "cwd": cwd})
    job_service.update_status(job.run_id, "running", "任务已提交，正在执行...")

    # 异步执行
    async def _execute():
        try:
            result = await runner.run(command, job.run_id, cwd=cwd)
            if result.returncode == 0:
                job_service.update_status(job.run_id, "completed", "任务执行成功")
                job_service.set_result(job.run_id, result.to_dict())
            else:
                job_service.update_status(job.run_id, "failed", f"任务执行失败，返回码 {result.returncode}")
                job_service.set_error(job.run_id, result.stderr[:2000])
        except Exception as e:
            job_service.set_error(job.run_id, str(e))

    asyncio.create_task(_execute())

    audit_service.record(
        event_type="job_run",
        resource="/api/jobs/run",
        action="execute",
        detail={"run_id": job.run_id, "command": command[:200]},
        run_id=job.run_id,
        ip_address=request.client.host if request.client else "",
    )

    return api_success(data={"job": job.to_dict()}, status_code=202, request=request)


@router.get("/jobs/{run_id}/stream")
async def stream_job(request: Request, run_id: str = Path(..., description="任务 run_id")):
    """SSE 流式输出任务日志。"""
    from fastapi.responses import StreamingResponse

    job = job_service.get(run_id)
    if not job:
        return api_error("NOT_FOUND", f"任务 {run_id} 不存在", status_code=404, request=request)

    async def _generate():
        # 先发送已有日志
        for log_entry in job.log:
            yield f"data: {log_entry}\n\n"
        # 等待新日志（简化处理：轮询）
        import asyncio
        last_len = len(job.log)
        while job.status in ("pending", "running"):
            await asyncio.sleep(0.5)
            new_logs = job.log[last_len:]
            for entry in new_logs:
                yield f"data: {entry}\n\n"
            last_len = len(job.log)
        # 发送最终状态
        yield f"event: done\ndata: {job.status}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
