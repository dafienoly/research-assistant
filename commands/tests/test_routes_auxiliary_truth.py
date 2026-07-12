from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

import factor_lab.api_server.routes_live as live_routes
import factor_lab.api_server.routes_portfolio as portfolio_routes
import factor_lab.api_server.routes_theme as theme_routes
from factor_lab.api_server.services.job_service import job_service
from factor_lab.decision_loop.storage import DecisionLoopStore
from factor_lab.datahub_access import read_benchmark_projection


def test_live_readiness_latest_defaults_to_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(live_routes, "STORE", DecisionLoopStore(tmp_path / "decision-loop"))
    app = FastAPI()
    app.include_router(live_routes.router, prefix="/api")
    payload = TestClient(app).get("/api/live-readiness/latest").json()["data"]
    assert payload["overall"] == "NOT_RUN"
    assert payload["live_activation_allowed"] is False


def test_live_readiness_persists_real_gate_result(tmp_path, monkeypatch):
    store = DecisionLoopStore(tmp_path / "decision-loop")
    monkeypatch.setattr(live_routes, "STORE", store)
    report = SimpleNamespace(
        overall="NOT_READY",
        to_dict=lambda: {
            "overall": "NOT_READY",
            "run_id": "readiness_real_1",
            "scanned_at": "2026-07-12T09:00:00+08:00",
            "gates": [{"gate_name": "QMT", "passed": False}],
            "blockers": [{"gate_name": "QMT", "message": "not connected"}],
            "warnings": [],
        },
    )
    import live_readiness

    monkeypatch.setattr(live_readiness, "run_live_readiness_check", lambda _strict: report)
    job = job_service.create("readiness-test", "live_readiness")
    job_service.update_status(job.run_id, "running")
    asyncio.run(live_routes._execute_real_readiness(job.run_id, True))

    persisted = store.read_json("readiness/latest.json")
    assert persisted["overall"] == "NOT_READY"
    assert persisted["live_activation_allowed"] is False
    assert job_service.get(job.run_id).result["gates"][0]["gate_name"] == "QMT"


def test_portfolio_latest_uses_persisted_vnext_artifact(tmp_path):
    artifact = tmp_path / "portfolio_optimization.json"
    payload = {
        "status": "OK",
        "data_snapshot_id": "snapshot-real",
        "target_weights_hash": "weights-real",
        "generated_at": "2026-07-11T09:00:00+08:00",
        "as_of": "2026-07-10",
        "real_broker_called": False,
        "order_output": False,
        "methods": {
            "cost_aware": {
                "status": "OK",
                "weights": {"technology": 0.3, "bond": 0.2},
                "cash_weight": 0.5,
                "annualized_return_estimate": 0.1,
                "annualized_volatility": 0.2,
                "sharpe_estimate": 0.5,
                "hard_constraints": {"cash_minimum": 0.35},
            }
        },
    }
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    result = portfolio_routes._latest_optimization(artifact)
    assert result["data_snapshot_id"] == "snapshot-real"
    assert result["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert sum(item["weight"] for item in result["holdings"]) == 100.0
    assert result["real_broker_called"] is False
    assert result["order_output"] is False


def test_portfolio_legacy_run_and_theme_status_fail_visible():
    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/api")
    app.include_router(theme_routes.router, prefix="/api")
    client = TestClient(app)
    assert client.post("/api/portfolio/recommendation/run", json={"strategy": "multi_factor"}).status_code == 503
    assert client.get("/api/theme/semiconductor/status").status_code == 503
    subsectors = client.get("/api/theme/semiconductor/subsectors").json()["data"]
    assert subsectors["status"] == "MISSING"
    assert subsectors["items"] == []


def test_benchmark_projection_hash_and_real_theme_history(tmp_path, monkeypatch):
    root = tmp_path / "benchmarks"
    root.mkdir()
    datasets = {}
    for name, returns in {
        "semiconductor_ew": [0.01, -0.01, 0.02, 0.00, 0.01],
        "ew_a_share": [0.00, 0.01, 0.00, -0.01, 0.01],
        "semiconductor_core_ew": [0.02, -0.01, 0.01, 0.01, 0.00],
    }.items():
        path = root / f"{name}.csv"
        pd.DataFrame({"date": pd.date_range("2026-07-06", periods=5), "return": returns}).to_csv(path, index=False)
        datasets[name] = {"path": path.name, "rows": 5, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "status": "OK"}
    (root / "manifest.json").write_text(
        json.dumps({"status": "OK", "generated_at": "2026-07-12T09:00:00+08:00", "source": "canonical", "datasets": datasets}),
        encoding="utf-8",
    )

    def reader(name):
        return read_benchmark_projection(name, root)

    monkeypatch.setattr(theme_routes, "read_benchmark_projection", reader)
    series, lineage = theme_routes._history_series(5)
    assert len(series) == 5
    assert series[-1]["semi_ew"] != series[-1]["all_a_ew"]
    assert lineage["semi_ew"]["sha256"] == datasets["semiconductor_ew"]["sha256"]

    (root / "semiconductor_ew.csv").write_text("tampered", encoding="utf-8")
    try:
        read_benchmark_projection("semiconductor_ew", root)
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered benchmark projection must fail closed")


def test_auxiliary_routes_contain_no_simulated_result_generators():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "factor_lab/api_server"
    sources = "\n".join((root / name).read_text(encoding="utf-8") for name in ("routes_live.py", "routes_portfolio.py", "routes_theme.py"))
    assert "asyncio.sleep" not in sources
    assert "_simulate" not in sources
    assert "math.sin" not in sources
    assert "8500000" not in sources
