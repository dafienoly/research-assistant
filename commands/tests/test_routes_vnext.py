import os

from fastapi.testclient import TestClient

from factor_lab.api_server.main import app


UI_TOKEN = os.environ.get("HERMES_UI_TOKEN", "").strip()
AUTH_HEADERS = {"Authorization": f"Bearer {UI_TOKEN}"} if UI_TOKEN else {}


def test_vnext_status_route_is_fail_visible(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_VNEXT_OUTPUT_DIR", str(tmp_path))
    with TestClient(app, headers=AUTH_HEADERS) as client:
        response = client.get("/api/vnext/status?date=2026-07-10")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "MISSING"


def test_vnext_api_can_be_disabled_without_affecting_legacy_routes(monkeypatch):
    monkeypatch.setenv("HERMES_VNEXT_ENABLED", "false")
    with TestClient(app, headers=AUTH_HEADERS) as client:
        blocked = client.get("/api/vnext/status")
        legacy = client.get("/api/health")
    assert blocked.status_code == 503
    assert legacy.status_code == 200


def test_vnext_formal_run_snapshot_and_reconciliation_routes_read_real_artifacts(monkeypatch):
    snapshot_id = "vnext-2026-07-10-3645917185de479e2cdc"
    with TestClient(app, headers=AUTH_HEADERS) as client:
        run = client.get("/api/vnext/runs/2026-07-10")
        snapshot = client.get(f"/api/vnext/snapshots/{snapshot_id}")
        reconciliation = client.get("/api/vnext/reconciliation/2026-07-10")

    assert run.status_code == 200
    assert run.json()["data"]["lineage"]["data_snapshot_ids"] == [snapshot_id]
    assert snapshot.status_code == 200
    assert snapshot.json()["data"]["payload"]["snapshot_id_valid"] is True
    assert reconciliation.status_code == 200
    assert reconciliation.json()["data"]["payload"]["same_snapshot_and_weights_proven"] is True


def test_vnext_artifact_routes_reject_unknown_or_invalid_identifiers(monkeypatch):
    with TestClient(app, headers=AUTH_HEADERS) as client:
        missing = client.get("/api/vnext/runs/not-a-real-run")
        invalid = client.get("/api/vnext/reconciliation/%20invalid%20")

    assert missing.status_code == 404
    assert invalid.status_code == 400
