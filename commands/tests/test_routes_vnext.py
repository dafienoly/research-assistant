from fastapi.testclient import TestClient

from factor_lab.api_server.main import app


def test_vnext_status_route_is_fail_visible(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_VNEXT_OUTPUT_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/vnext/status?date=2026-07-10")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "MISSING"


def test_vnext_api_can_be_disabled_without_affecting_legacy_routes(monkeypatch):
    monkeypatch.setenv("HERMES_VNEXT_ENABLED", "false")
    with TestClient(app) as client:
        blocked = client.get("/api/vnext/status")
        legacy = client.get("/api/health")
    assert blocked.status_code == 503
    assert legacy.status_code == 200
