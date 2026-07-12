from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from factor_lab.api_server.routes_backtest import router


def test_legacy_backtest_run_fails_visible_without_creating_random_results():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/backtests/run",
        json={"strategy": "ret5", "universe": "hs300", "start_date": "2025-01-01", "end_date": "2026-06-30"},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "BACKTEST_ENGINE_NOT_INTEGRATED"

    history = client.get("/api/backtests")
    assert history.status_code == 200
    assert history.json()["data"]["execution_available"] is False
    assert history.json()["data"]["verified_artifacts_endpoint"] == "/api/vnext/backtests"


def test_legacy_backtest_source_contains_no_random_result_generator():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "factor_lab/api_server/routes_backtest.py"
    text = source.read_text(encoding="utf-8")
    assert "import random" not in text
    assert "random.uniform" not in text
    assert "asyncio.sleep" not in text
