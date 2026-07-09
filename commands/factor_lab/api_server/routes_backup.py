"""API Backup routes — 备份列表与恢复"""
import asyncio
from fastapi import APIRouter
from factor_lab.api_server.response import api_success, api_error
from factor_lab.leader.roadmap_backup import auto_backup, list_backups, recover
from factor_lab.leader.version_report import generate_report

router = APIRouter()


@router.get("/backups")
async def get_backups():
    return api_success(data={"backups": list_backups()})


@router.post("/backups")
async def create_backup():
    b = auto_backup()
    return api_success(data=b)


@router.post("/backups/{backup_id}/recover")
async def recover_backup(backup_id: str):
    return api_success(data=recover(backup_id))


@router.post("/auto-run")
async def trigger_auto_run():
    """异步执行 auto_run_once，立即返回 task_id。"""
    from factor_lab.leader.auto_executor import auto_run_once

    # 在后台线程中执行
    run_id = f"auto_run_{asyncio.get_event_loop().time():.0f}"

    async def _background_run():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, auto_run_once)

    asyncio.create_task(_background_run())

    return api_success(data={
        "status": "submitted",
        "task_id": run_id,
        "message": "auto_run_once 已提交后台执行",
    })


@router.get("/versions/report")
async def version_report():
    return api_success(data=generate_report())


@router.get("/data/health")
async def data_health():
    try:
        from factor_lab.data_health import health_check
        result = health_check()
        return api_success(data=result)
    except Exception as e:
        return api_error(
            "DATA_HEALTH_ERROR",
            f"数据健康检查失败: {type(e).__name__}",
            status_code=500,
        )


@router.get("/data/sources")
async def data_sources():
    from factor_lab.data_source_registry import list_sources
    return api_success(data=list_sources())
