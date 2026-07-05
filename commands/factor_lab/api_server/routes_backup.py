"""API Backup routes — 备份列表与恢复"""
from fastapi import APIRouter
from factor_lab.leader.roadmap_backup import auto_backup, list_backups, recover
from factor_lab.leader.version_report import generate_report

router = APIRouter()


@router.get("/backups")
async def get_backups():
    return {"backups": list_backups()}


@router.post("/backups")
async def create_backup():
    b = auto_backup()
    return b


@router.post("/backups/{backup_id}/recover")
async def recover_backup(backup_id: str):
    return recover(backup_id)


@router.post("/auto-run")
async def trigger_auto_run():
    from factor_lab.leader.auto_executor import auto_run_once
    result = auto_run_once()
    return result


@router.get("/versions/report")
async def version_report():
    return generate_report()
