from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from factor_lab.api_server.routes_decision_loop import router


def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HERMES_DECISION_LOOP_STATE_DIR", str(tmp_path / "state"))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_status_and_confirmed_position_import(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    assert api.get("/api/decision-loop/status").status_code == 200
    preview = api.post(
        "/api/decision-loop/positions/preview",
        json={
            "source": "clipboard",
            "content": "证券代码\t证券名称\t持仓数量\t可用数量\t成本价\n588200.SH\t设备ETF\t1000\t1000\t1.2",
        },
    ).json()["data"]
    assert preview["additions"][0]["symbol"] == "588200.SH"
    response = api.post(
        "/api/decision-loop/positions/confirm",
        json={
            "preview_id": preview["preview_id"],
            "expected_hash": preview["proposed_snapshot"]["content_hash"],
        },
    )
    assert response.status_code == 200
    status = api.get("/api/decision-loop/status").json()["data"]
    assert status["current_position_snapshot"]["confirmed"] is True


def test_guard_endpoint_blocks_action_when_core_data_missing(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    now = datetime.now().astimezone().isoformat()
    payload = {
        "position": {
            "symbol": "588200.SH",
            "quantity": 1000,
            "available_quantity": 1000,
            "cost_price": 1,
            "instrument_type": "etf",
            "book": "catalyst",
        },
        "quote": {
            "symbol": "588200.SH",
            "last_price": 1.1,
            "vwap": 1.1,
            "observed_at": now,
            "source": "test",
        },
        "data_items": [{"name": "quotes", "available": False, "fresh": False}],
    }
    response = api.post("/api/decision-loop/guard/evaluate", json=payload)
    assert response.status_code == 200
    assert response.json()["data"]["data_gate"]["mode"] == "blocked"


def test_empty_opportunity_passlist_is_explicit(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    response = api.post(
        "/api/decision-loop/opportunities/evaluate", json={"candidates": []}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["primary"] == []
    assert "保持现金" in data["no_opportunity_reason"]


def test_parameter_api_never_promotes_without_oos(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    candidate = api.post(
        "/api/decision-loop/parameters/candidates",
        json={
            "parameter": "giveback_points",
            "current_value": 3,
            "proposed_value": 2.8,
            "evidence": {"samples": 30},
        },
    ).json()["data"]
    blocked = api.post(
        f"/api/decision-loop/parameters/candidates/{candidate['candidate_id']}/weekly-decision",
        json={"approved": True, "reviewer": "ly"},
    )
    assert blocked.status_code == 409
    assert (
        api.post(
            f"/api/decision-loop/parameters/candidates/{candidate['candidate_id']}/oos",
            json={"passed": True, "metrics": {"calmar": 1.2}},
        ).status_code
        == 200
    )
    promoted = api.post(
        f"/api/decision-loop/parameters/candidates/{candidate['candidate_id']}/weekly-decision",
        json={"approved": True, "reviewer": "ly"},
    )
    assert promoted.json()["data"]["status"] == "promoted"
