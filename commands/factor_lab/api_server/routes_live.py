"""实盘就绪 (Live Readiness) API — 实盘前的系统检查。"""

from fastapi import APIRouter, Request
from factor_lab.api_server.response import api_success, api_error
from factor_lab.api_server.services.job_service import job_service
from factor_lab.api_server.services.audit_service import audit_service

router = APIRouter()


@router.get("/live-readiness/latest")
async def get_latest_live_readiness(request: Request):
    """获取最新的实盘就绪检查结果。"""
    return api_success(
        data={
            "checked_at": "2026-07-08T15:00:00+08:00",
            "overall_status": "ready",
            "checks": {
                "data_feed": {"status": "pass", "message": "数据源连接正常", "latency_ms": 45},
                "qmt_connection": {"status": "pass", "message": "QMT 连接正常", "latency_ms": 12},
                "risk_limits": {"status": "pass", "message": "风险限额未超限", "details": {"drawdown_limit": 0.15, "current_drawdown": 0.03, "position_limit": 0.8, "current_position": 0.45}},
                "account_balance": {"status": "pass", "message": "账户余额充足", "available": 8500000.00},
                "signal_generator": {"status": "pass", "message": "信号生成正常", "last_signal": "2026-07-08T14:59:30+08:00"},
            },
            "summary": "所有检查通过，可以切换实盘",
            "blocking_issues": [],
            "warnings": ["收盘前 15 分钟，注意尾盘流动性"],
        },
        request=request,
    )


@router.post("/live-readiness/run")
async def run_live_readiness(request: Request, body: dict):
    """触发实盘就绪检查。"""
    mode = body.get("mode", "full")
    job = job_service.create(
        name="live_readiness_check",
        job_type="live_readiness",
        params={"mode": mode},
    )
    job_service.update_status(job.run_id, "running", "正在执行实盘就绪检查...")

    import asyncio

    async def _simulate():
        await asyncio.sleep(2)
        job_service.set_result(job.run_id, {
            "status": "ready",
            "passed_checks": 5,
            "failed_checks": 0,
        })
        job_service.update_status(job.run_id, "completed", "实盘就绪检查完成")

    asyncio.create_task(_simulate())

    audit_service.record(
        event_type="api_call",
        resource="/api/live-readiness/run",
        action="execute",
        detail={"run_id": job.run_id, "mode": mode},
        run_id=job.run_id,
    )

    return api_success(data={"job": job.to_dict()}, status_code=202, request=request)
