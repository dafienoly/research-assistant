"""One-click Local Ops API routes — V7.9 本地一键运维

提供本地服务健康检查、一键启停、备份、诊断等 REST API:
  - GET  /api/ops/health       — 所有服务健康状态概览
  - GET  /api/ops/status/{id}  — 单个服务详细状态
  - POST /api/ops/start/{id}   — 启动服务
  - POST /api/ops/stop/{id}    — 停止服务
  - POST /api/ops/restart/{id} — 重启服务
  - POST /api/ops/backup       — 触发一键备份
  - GET  /api/ops/diagnostics  — 运行全面诊断
  - GET  /api/ops/ports        — 端口占用扫描

通过模块级 OpsManager 单例连接底层运维引擎。
测试时可用 monkeypatch 替换 get_manager()。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException

from factor_lab.leader.ops_dashboard import OpsManager, get_manager, reset_manager

router = APIRouter()

# ===================================================================
# 端点
# ===================================================================


@router.get("/ops/health")
def ops_health():
    """GET /api/ops/health — 所有服务健康状态概览

    返回整体状态、每个服务的运行状态、端口占用情况。
    """
    mgr = get_manager()
    return mgr.health()


@router.get("/ops/status/{service_id}")
def ops_service_status(service_id: str):
    """GET /api/ops/status/{service_id} — 单个服务详细状态

    service_id: dashboard | mcp | vite
    """
    mgr = get_manager()
    status = mgr.service_status(service_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status


@router.post("/ops/start/{service_id}")
def ops_start_service(service_id: str):
    """POST /api/ops/start/{service_id} — 启动服务"""
    mgr = get_manager()
    result = mgr.start_service(service_id)
    if not result.get("success") and result.get("error"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/ops/stop/{service_id}")
def ops_stop_service(service_id: str):
    """POST /api/ops/stop/{service_id} — 停止服务"""
    mgr = get_manager()
    result = mgr.stop_service(service_id)
    if not result.get("success") and result.get("error"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/ops/restart/{service_id}")
def ops_restart_service(service_id: str):
    """POST /api/ops/restart/{service_id} — 重启服务"""
    mgr = get_manager()
    result = mgr.restart_service(service_id)
    if not result.get("success"):
        if result.get("error"):
            raise HTTPException(status_code=409, detail=result)
        if result.get("stop", {}).get("error"):
            raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/ops/backup")
def ops_backup():
    """POST /api/ops/backup — 触发一键备份

    执行状态备份 + 配置备份 + 日志轮转。
    """
    mgr = get_manager()
    return mgr.backup()


@router.get("/ops/diagnostics")
def ops_diagnostics():
    """GET /api/ops/diagnostics — 运行全面诊断

    返回: 系统信息、磁盘/内存使用率、Python 依赖、
          各服务状态、端口占用、Cron 状态、Git 状态、工作目录检查。
    """
    mgr = get_manager()
    return mgr.diagnostics()


@router.get("/ops/ports")
def ops_ports():
    """GET /api/ops/ports — 扫描所有关注端口的状态"""
    mgr = get_manager()
    return {"ports": mgr.port_scan()}


# ===================================================================
# 测试辅助
# ===================================================================


def _reset_ops_manager():
    """重置单例（测试用）"""
    reset_manager()
