from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factor_lab.api_server.main import app
from factor_lab.leader.ops_dashboard import OpsManager, SERVICE_DEFS, reset_manager


def _configured_ui_token():
    import os

    token = os.environ.get("HERMES_UI_TOKEN", "").strip()
    if token:
        return token
    env_path = Path(__file__).resolve().parents[1].parent / ".env"
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith("HERMES_UI_TOKEN="):
                return raw_line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


@pytest.fixture(autouse=True)
def reset_ops_manager():
    reset_manager()
    yield
    reset_manager()


@pytest.fixture
def client():
    client = TestClient(app)
    if token := _configured_ui_token():
        client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_service_catalog_contains_only_operations_services():
    assert set(SERVICE_DEFS) == {"dashboard", "mcp", "vite"}
    assert "auto-loop" not in SERVICE_DEFS
    assert "agent-runner" not in SERVICE_DEFS


def test_health_api(client, monkeypatch):
    monkeypatch.setattr(OpsManager, "health", lambda self: {
        "overall": "healthy", "all_running": True, "n_services": 3,
        "n_running": 3, "services": {}, "ports": {},
    })
    response = client.get("/api/ops/health")
    assert response.status_code == 200
    assert response.json()["n_services"] == 3


def test_optional_services_do_not_degrade_health(monkeypatch):
    states = {
        "dashboard": {"running": True},
        "mcp": {"running": False},
        "vite": {"running": False},
    }
    monkeypatch.setattr(OpsManager, "service_status", lambda self, sid: states[sid])
    monkeypatch.setattr(
        "factor_lab.leader.ops_dashboard._check_port",
        lambda port: {"port": port, "in_use": False, "pid": None, "process_name": None},
    )
    result = OpsManager().health()
    assert result["overall"] == "healthy"
    assert result["all_running"] is True
    assert result["n_running"] == 1


def test_unknown_service_is_structured_404(client):
    response = client.get("/api/ops/status/unknown")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_stop_service_uses_owned_pid_without_pkill(monkeypatch, tmp_path):
    pid_file = tmp_path / "service.pid"
    pid_file.write_text("12345", encoding="utf-8")
    manager = OpsManager()
    manager._service_defs = {
        "owned": {
            "name": "Owned", "name_zh": "自有服务", "port": None,
            "pid_file": str(pid_file), "log_file": None, "command": None,
            "health_url": None, "depends_on": [], "env": {},
        }
    }
    killed = []
    monkeypatch.setattr("factor_lab.leader.ops_dashboard.os.kill", lambda pid, sig: killed.append((pid, sig)))
    result = manager.stop_service("owned")
    assert result["success"] is True
    assert killed
    assert all("pkill" not in method for method in result["killed_methods"])


def test_backup_contains_config_and_logs_only(monkeypatch, tmp_path):
    monkeypatch.setattr("factor_lab.leader.ops_dashboard.LOGS_DIR", tmp_path)
    manager = OpsManager()
    result = manager.backup()
    assert set(result["results"]) == {"config_backup", "log_backup"}
    assert "roadmap_backup" not in result["results"]


def test_diagnostics_has_no_agent_services(monkeypatch):
    monkeypatch.setattr("factor_lab.leader.ops_dashboard._check_port", lambda port: {"port": port, "in_use": False, "pid": None, "process_name": None})
    monkeypatch.setattr("factor_lab.leader.ops_dashboard._check_process_by_pid", lambda _: {"running": False, "pid": None, "pid_file_exists": False})
    result = OpsManager().diagnostics()
    assert set(result["services"]) == {"dashboard", "mcp", "vite"}
