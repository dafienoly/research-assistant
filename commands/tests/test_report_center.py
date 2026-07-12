import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from factor_lab.api_server.main import app


def _configured_ui_token():
    token = os.environ.get("HERMES_UI_TOKEN", "").strip()
    if token:
        return token
    env_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith("HERMES_UI_TOKEN="):
                return raw_line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def _client():
    client = TestClient(app)
    if token := _configured_ui_token():
        client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_report_center_only_discovers_research_reports(tmp_path, monkeypatch):
    backtest = tmp_path / "backtests" / "run-1"
    backtest.mkdir(parents=True)
    (backtest / "metrics.json").write_text(json.dumps({"strategy_name": "demo", "sharpe": 1.2}), encoding="utf-8")
    strategy = tmp_path / "strategies" / "daily"
    strategy.mkdir(parents=True)
    (strategy / "report.html").write_text("<h1>report</h1>", encoding="utf-8")
    (tmp_path / "version_reports").mkdir()
    (tmp_path / "version_reports" / "legacy.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HERMES_REPORTS_BASE", str(tmp_path))
    payload = _client().get("/api/reports").json()["data"]
    assert payload["total"] == 2
    assert {item["type"] for item in payload["reports"]} == {"backtest", "strategy"}


def test_retired_report_type_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_REPORTS_BASE", str(tmp_path))
    response = _client().get("/api/reports?type=roadmap")
    assert response.status_code == 400
