from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import factor_lab.api_server.routes_events as routes


def _event(event_id: str = "corp_real") -> dict:
    return {
        "id": event_id,
        "event_date": "2026-07-10",
        "ts_code": "688012.SH",
        "name": "中微公司",
        "event_type": "回购",
        "event_direction": "positive",
        "event_strength": 4,
        "event_source": "datahub:tushare",
        "title": "回购",
        "detail": '{"ann_date":"20260710"}',
        "risk_flags": ["canonical_manifest_partial"],
        "source_ref": "688012.SH.csv#sha256=abc",
        "observed_at": "2026-07-10T18:00:00+08:00",
    }


def test_events_routes_return_canonical_schema_without_fabricated_performance(monkeypatch):
    monkeypatch.setattr(routes, "_canonical_events", lambda: [_event()])
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/events", params={"event_type": "回购", "direction": "positive"})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["events"][0]["event_source"] == "datahub:tushare"
    assert payload["events"][0]["source_ref"].endswith("sha256=abc")
    assert payload["factor_performance"] == []

    detail = client.get("/api/events/corp_real")
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == "corp_real"


def test_events_route_returns_empty_not_demo_rows(monkeypatch):
    monkeypatch.setattr(routes, "_canonical_events", lambda: [])
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    response = TestClient(app).get("/api/events")
    assert response.status_code == 200
    assert response.json()["data"]["events"] == []
    assert response.json()["data"]["total"] == 0
