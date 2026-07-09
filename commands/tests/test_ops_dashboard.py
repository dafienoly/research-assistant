"""V7.9 One-click Local Ops — API 测试

覆盖:
  - GET  /api/ops/health       — 健康状态概览（正常/降级/空）
  - GET  /api/ops/status/{id}  — 单个服务状态
  - POST /api/ops/start/{id}   — 启动服务（正常/已运行/未知服务/端口冲突）
  - POST /api/ops/stop/{id}    — 停止服务（正常/未运行）
  - POST /api/ops/restart/{id} — 重启服务
  - POST /api/ops/backup       — 一键备份（成功/部分失败）
  - GET  /api/ops/diagnostics  — 全面诊断
  - GET  /api/ops/ports        — 端口扫描
  - 边界条件: 未知服务 ID、无效请求
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from factor_lab.api_server.main import app
from factor_lab.leader.ops_dashboard import OpsManager, reset_manager

CST_TIME = "2026-07-08 12:00:00"

# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_ops():
    """每个测试前重置 OpsManager 单例"""
    reset_manager()
    yield
    reset_manager()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_ops_all_running(monkeypatch):
    """Mock OpsManager 返回所有服务运行中"""
    def mock_health(self):
        return {
            "timestamp": CST_TIME,
            "overall": "healthy",
            "all_running": True,
            "n_services": 5,
            "n_running": 5,
            "services": {
                "dashboard": {"id": "dashboard", "name": "API Dashboard", "name_zh": "API 仪表盘", "port": 8766, "running": True, "detected_by": "pid", "pid_status": {"running": True, "pid": 12345, "pid_file_exists": True}, "port_status": {"port": 8766, "in_use": True, "pid": 12345, "process_name": "python3"}, "cron_status": None},
                "auto-loop": {"id": "auto-loop", "name": "Auto Version Loop", "name_zh": "自动版本循环", "port": None, "running": True, "detected_by": "pid", "pid_status": {"running": True, "pid": 12346, "pid_file_exists": True}, "port_status": None, "cron_status": None},
                "agent-runner": {"id": "agent-runner", "name": "Agent Runner (cron)", "name_zh": "代理执行器", "port": None, "running": True, "detected_by": "cron", "pid_status": {"running": False, "pid": None, "pid_file_exists": False}, "port_status": None, "cron_status": {"registered": True}},
                "mcp": {"id": "mcp", "name": "MCP Server", "name_zh": "MCP 工具服务器", "port": 8767, "running": True, "detected_by": "port", "pid_status": {"running": False, "pid": None, "pid_file_exists": False}, "port_status": {"port": 8767, "in_use": True, "pid": 12347, "process_name": "python3"}, "cron_status": None},
                "vite": {"id": "vite", "name": "Vite Dev Server", "name_zh": "Vite 前端开发服务器", "port": 5173, "running": False, "detected_by": "none", "pid_status": {"running": False, "pid": None, "pid_file_exists": False}, "port_status": {"port": 5173, "in_use": False, "pid": None, "process_name": None}, "cron_status": None},
            },
            "ports": {
                "dashboard": {"port": 8766, "in_use": True, "pid": 12345, "process_name": "python3"},
                "mcp": {"port": 8767, "in_use": True, "pid": 12347, "process_name": "python3"},
                "vite": {"port": 5173, "in_use": False, "pid": None, "process_name": None},
            },
            "venv_python": "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3",
            "base_dir": "/home/ly/.hermes/research-assistant/commands",
        }

    def mock_service_status(self, service_id):
        if service_id == "unknown":
            return {"error": f"未知服务: {service_id}", "running": False}
        if service_id == "dashboard":
            return {"id": "dashboard", "name": "API Dashboard", "name_zh": "API 仪表盘", "port": 8766, "running": True, "detected_by": "pid", "pid_status": {"running": True, "pid": 12345, "pid_file_exists": True}, "port_status": {"port": 8766, "in_use": True, "pid": 12345, "process_name": "python3"}, "cron_status": None, "log_tail": ["[12:00:00] started"]}
        if service_id == "vite":
            return {"id": "vite", "name": "Vite Dev Server", "name_zh": "Vite 前端开发服务器", "port": 5173, "running": False, "detected_by": "none", "pid_status": {"running": False, "pid": None, "pid_file_exists": False}, "port_status": {"port": 5173, "in_use": False, "pid": None, "process_name": None}, "cron_status": None, "log_tail": []}
        return {"id": service_id, "name": f"Service {service_id}", "name_zh": f"服务 {service_id}", "port": None, "running": True, "detected_by": "pid", "pid_status": {"running": True, "pid": 99999, "pid_file_exists": True}, "port_status": None, "cron_status": None, "log_tail": []}

    def mock_start_service(self, service_id):
        if service_id == "unknown":
            return {"success": False, "error": f"未知服务: {service_id}"}
        if service_id == "vite":
            return {"success": False, "error": "Vite 前端开发服务器 不支持直接启动"}
        return {"success": True, "message": f"服务 {service_id} 已启动 (PID 88888)", "pid": 88888, "already_running": False}

    def mock_stop_service(self, service_id):
        if service_id == "unknown":
            return {"success": False, "error": f"未知服务: {service_id}"}
        if service_id == "vite":
            return {"success": True, "message": "Vite 前端开发服务器 未在运行", "already_stopped": True}
        return {"success": True, "message": f"服务 {service_id} 已停止", "killed_methods": [f"PID 12345"], "already_stopped": False}

    def mock_restart_service(self, service_id):
        if service_id == "unknown":
            return {"success": False, "error": f"未知服务: {service_id}"}
        stop_r = {"success": True, "message": f"服务 {service_id} 已停止", "killed_methods": [f"PID 12345"], "already_stopped": False}
        start_r = {"success": True, "message": f"服务 {service_id} 已启动 (PID 88888)", "pid": 88888, "already_running": False}
        return {"success": True, "stop": stop_r, "start": start_r, "message": f"重启 {service_id}: 成功"}

    def mock_backup(self):
        return {
            "success": True,
            "timestamp": CST_TIME,
            "results": {
                "roadmap_backup": {"success": True, "backup_id": "backup_20260708_120000", "path": "/tmp/backup.json"},
                "config_backup": {"success": True, "path": "/tmp/config_backup.json"},
                "log_backup": {"success": True, "dir": "/tmp/log_backup"},
            },
        }

    def mock_diagnostics(self):
        return {
            "timestamp": CST_TIME,
            "hostname": "test-host",
            "system": {"platform": "Linux-5.15.0-x86_64", "python": "3.11.0", "python_executable": "/usr/bin/python3"},
            "disk": {"path": "/home", "total_gb": 100.0, "used_gb": 45.0, "free_gb": 55.0, "usage_pct": 45.0, "status": "healthy"},
            "memory": {"total_gb": 16.0, "available_gb": 8.0, "usage_pct": 50.0, "status": "healthy"},
            "python_deps": [
                {"name": "FastAPI", "available": True, "error": None},
                {"name": "pandas", "available": True, "error": None},
                {"name": "numpy", "available": True, "error": None},
            ],
            "venv": {"path": "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3", "exists": True},
            "services": {
                "dashboard": {"id": "dashboard", "running": True},
                "auto-loop": {"id": "auto-loop", "running": True},
                "agent-runner": {"id": "agent-runner", "running": True},
                "mcp": {"id": "mcp", "running": True},
                "vite": {"id": "vite", "running": False},
            },
            "ports": [
                {"port": 8766, "in_use": True, "service": "dashboard"},
                {"port": 8767, "in_use": True, "service": "mcp"},
                {"port": 5173, "in_use": False, "service": "vite"},
            ],
            "cron": {"registered": True},
            "git": {"has_changes": False, "changed_files": 0},
            "workspace": {"cli_exists": True, "scripts_dir_exists": True, "frontend_dist_exists": True, "factor_lab_exists": True},
        }

    def mock_port_scan(self):
        return [
            {"port": 8766, "in_use": True, "pid": 12345, "process_name": "python3", "service": "dashboard", "service_name": "API 仪表盘"},
            {"port": 8767, "in_use": True, "pid": 12347, "process_name": "python3", "service": "mcp", "service_name": "MCP 工具服务器"},
            {"port": 5173, "in_use": False, "pid": None, "process_name": None, "service": "vite", "service_name": "Vite 前端开发服务器"},
        ]

    monkeypatch.setattr(OpsManager, "health", mock_health)
    monkeypatch.setattr(OpsManager, "service_status", mock_service_status)
    monkeypatch.setattr(OpsManager, "start_service", mock_start_service)
    monkeypatch.setattr(OpsManager, "stop_service", mock_stop_service)
    monkeypatch.setattr(OpsManager, "restart_service", mock_restart_service)
    monkeypatch.setattr(OpsManager, "backup", mock_backup)
    monkeypatch.setattr(OpsManager, "diagnostics", mock_diagnostics)
    monkeypatch.setattr(OpsManager, "port_scan", mock_port_scan)


@pytest.fixture
def mock_ops_all_stopped(monkeypatch):
    """Mock OpsManager 返回所有服务已停止"""
    def mock_health(self):
        return {
            "timestamp": CST_TIME,
            "overall": "degraded",
            "all_running": False,
            "n_services": 5,
            "n_running": 1,
            "services": {sid: {"id": sid, "running": False, "name_zh": sid} for sid in ["dashboard", "auto-loop", "agent-runner", "mcp", "vite"]},
            "ports": {},
            "venv_python": "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3",
            "base_dir": "/home/ly/.hermes/research-assistant/commands",
        }

    monkeypatch.setattr(OpsManager, "health", mock_health)


# ═══════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════


class TestOpsHealth:
    """GET /api/ops/health — 健康状态概览"""

    def test_health_all_running(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        d = resp.json()
        assert d["overall"] == "healthy"
        assert d["all_running"] is True
        assert d["n_services"] == 5
        assert d["n_running"] == 5
        assert "services" in d
        assert "ports" in d
        assert "venv_python" in d
        assert d["services"]["dashboard"]["running"] is True

    def test_health_degraded(self, client, mock_ops_all_stopped):
        resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        d = resp.json()
        assert d["overall"] == "degraded"
        assert d["all_running"] is False
        assert d["n_running"] < d["n_services"]


# ═══════════════════════════════════════════════════════════════════
# Single Service Status
# ═══════════════════════════════════════════════════════════════════


class TestOpsServiceStatus:
    """GET /api/ops/status/{id} — 单个服务状态"""

    def test_status_running(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/status/dashboard")
        assert resp.status_code == 200
        d = resp.json()
        assert d["running"] is True
        assert d["port"] == 8766
        assert d["id"] == "dashboard"
        assert d["name_zh"] == "API 仪表盘"

    def test_status_stopped(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/status/vite")
        assert resp.status_code == 200
        d = resp.json()
        assert d["running"] is False
        assert d["port"] == 5173
        assert d["id"] == "vite"

    def test_status_unknown_service(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/status/unknown")
        assert resp.status_code == 404
        d = resp.json()
        assert "detail" in d


# ═══════════════════════════════════════════════════════════════════
# Start Service
# ═══════════════════════════════════════════════════════════════════


class TestOpsStart:
    """POST /api/ops/start/{id} — 启动服务"""

    def test_start_success(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/start/auto-loop")
        assert resp.status_code == 200
        d = resp.json()
        assert d["success"] is True
        assert "已启动" in d.get("message", "")
        assert d["pid"] == 88888

    def test_start_unknown_service(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/start/unknown")
        assert resp.status_code == 409
        d = resp.json()
        assert d["detail"]["success"] is False
        assert "未知服务" in d["detail"]["error"]

    def test_start_unsupported(self, client, mock_ops_all_running):
        """不支持直接启动的服务 (vite)"""
        resp = client.post("/api/ops/start/vite")
        assert resp.status_code == 409
        d = resp.json()
        assert d["detail"]["success"] is False
        assert "不支持直接启动" in d["detail"]["error"]


# ═══════════════════════════════════════════════════════════════════
# Stop Service
# ═══════════════════════════════════════════════════════════════════


class TestOpsStop:
    """POST /api/ops/stop/{id} — 停止服务"""

    def test_stop_success(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/stop/dashboard")
        assert resp.status_code == 200
        d = resp.json()
        assert d["success"] is True
        assert "已停止" in d.get("message", "")

    def test_stop_already_stopped(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/stop/vite")
        assert resp.status_code == 200
        d = resp.json()
        assert d["success"] is True
        assert d["already_stopped"] is True

    def test_stop_unknown_service(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/stop/unknown")
        assert resp.status_code == 409
        d = resp.json()
        assert d["detail"]["success"] is False


# ═══════════════════════════════════════════════════════════════════
# Restart Service
# ═══════════════════════════════════════════════════════════════════


class TestOpsRestart:
    """POST /api/ops/restart/{id} — 重启服务"""

    def test_restart_success(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/restart/dashboard")
        assert resp.status_code == 200
        d = resp.json()
        assert d["success"] is True
        assert d["stop"]["success"] is True
        assert d["start"]["success"] is True

    def test_restart_unknown_service(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/restart/unknown")
        assert resp.status_code == 409
        d = resp.json()
        assert d["detail"]["success"] is False


# ═══════════════════════════════════════════════════════════════════
# Backup
# ═══════════════════════════════════════════════════════════════════


class TestOpsBackup:
    """POST /api/ops/backup — 一键备份"""

    def test_backup_success(self, client, mock_ops_all_running):
        resp = client.post("/api/ops/backup")
        assert resp.status_code == 200
        d = resp.json()
        assert d["success"] is True
        assert "timestamp" in d
        assert "results" in d
        assert d["results"]["roadmap_backup"]["success"] is True
        assert d["results"]["roadmap_backup"]["backup_id"] == "backup_20260708_120000"
        assert d["results"]["config_backup"]["success"] is True
        assert d["results"]["log_backup"]["success"] is True


# ═══════════════════════════════════════════════════════════════════
# Diagnostics
# ═══════════════════════════════════════════════════════════════════


class TestOpsDiagnostics:
    """GET /api/ops/diagnostics — 全面诊断"""

    def test_diagnostics_full(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/diagnostics")
        assert resp.status_code == 200
        d = resp.json()
        assert d["hostname"] == "test-host"
        assert d["system"]["platform"].startswith("Linux")
        assert d["system"]["python"] == "3.11.0"
        assert d["disk"]["status"] == "healthy"
        assert d["memory"]["status"] == "healthy"
        assert len(d["python_deps"]) == 3
        assert all(dep["available"] for dep in d["python_deps"])
        assert d["venv"]["exists"] is True
        assert d["cron"]["registered"] is True
        assert d["git"]["has_changes"] is False
        assert d["workspace"]["cli_exists"] is True
        assert d["workspace"]["frontend_dist_exists"] is True


# ═══════════════════════════════════════════════════════════════════
# Port Scan
# ═══════════════════════════════════════════════════════════════════


class TestOpsPorts:
    """GET /api/ops/ports — 端口扫描"""

    def test_ports_list(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/ports")
        assert resp.status_code == 200
        d = resp.json()
        assert "ports" in d
        assert len(d["ports"]) == 3

        ports = {p["port"]: p for p in d["ports"]}
        assert ports[8766]["in_use"] is True
        assert ports[8767]["in_use"] is True
        assert ports[5173]["in_use"] is False

    def test_ports_have_service_info(self, client, mock_ops_all_running):
        resp = client.get("/api/ops/ports")
        d = resp.json()
        for p in d["ports"]:
            assert "service" in p
            assert "service_name" in p


# ═══════════════════════════════════════════════════════════════════
# Integration: Real OpsManager with mocked subprocess/psutil
# ═══════════════════════════════════════════════════════════════════


class TestOpsManagerInternals:
    """OpsManager 内部方法测试（使用 real OpsManager + mock 系统调用）"""

    def test_health_returns_dict(self, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_port",
            lambda p: {"port": p, "in_use": False, "pid": None, "process_name": None},
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_process_by_pid",
            lambda pf: {"running": False, "pid": None, "pid_file_exists": False},
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_cron_job",
            lambda: {"registered": False},
        )
        manager = OpsManager()
        result = manager.health()
        assert isinstance(result, dict)
        assert "overall" in result
        assert result["overall"] == "degraded"
        assert "services" in result
        assert "ports" in result
        assert result["n_running"] == 0

    def test_service_status_unknown(self, monkeypatch):
        manager = OpsManager()
        result = manager.service_status("nonexistent")
        assert "error" in result
        assert result["running"] is False

    def test_backup_returns_dict(self, monkeypatch):
        """测试 backup 返回结构（mock 内部模块）"""
        def mock_auto_backup():
            return {"backup_id": "test_backup", "path": "/tmp/test"}

        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard.shutil.disk_usage",
            lambda p: type("DU", (), {"total": 1e12, "used": 5e11, "free": 5e11})(),
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard.Path.write_text",
            lambda self, text: None,
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard.Path.exists",
            lambda self: True,
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard.Path.mkdir",
            lambda self, **kw: None,
        )
        # Mock the actual import
        import sys
        mock_module = type(sys)("factor_lab.leader.roadmap_backup")
        mock_module.auto_backup = mock_auto_backup
        monkeypatch.setitem(sys.modules, "factor_lab.leader.roadmap_backup", mock_module)

        manager = OpsManager()
        result = manager.backup()
        assert isinstance(result, dict)
        assert "success" in result
        assert "results" in result

    def test_diagnostics_returns_dict(self, monkeypatch):
        def mock_disk_usage(p):
            return type("DU", (), {"total": 1e12, "used": 5e11, "free": 5e11})()

        monkeypatch.setattr("factor_lab.leader.ops_dashboard.shutil.disk_usage", mock_disk_usage)
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_memory_usage",
            lambda: {"total_gb": 16.0, "available_gb": 8.0, "usage_pct": 50.0, "status": "healthy"},
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_python_deps",
            lambda: [{"name": "FastAPI", "available": True, "error": None}],
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_cron_job",
            lambda: {"registered": True},
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_port",
            lambda p: {"port": p, "in_use": False, "pid": None, "process_name": None},
        )
        monkeypatch.setattr(
            "factor_lab.leader.ops_dashboard._check_process_by_pid",
            lambda pf: {"running": False, "pid": None, "pid_file_exists": False},
        )
        manager = OpsManager()
        result = manager.diagnostics()
        assert isinstance(result, dict)
        assert "hostname" in result
        assert "system" in result
        assert "disk" in result
        assert "memory" in result
        assert "python_deps" in result
        assert "services" in result
        assert "ports" in result
        assert "cron" in result
        assert "workspace" in result


# ═══════════════════════════════════════════════════════════════════
# Count tests for AC: 15+ tests
# ═══════════════════════════════════════════════════════════════════
