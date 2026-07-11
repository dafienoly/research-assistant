import json

from fastapi.testclient import TestClient

from factor_lab.api_server.main import app


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
    client = TestClient(app)
    payload = client.get("/api/reports").json()["data"]
    assert payload["total"] == 2
    assert {item["type"] for item in payload["reports"]} == {"backtest", "strategy"}


def test_retired_report_type_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_REPORTS_BASE", str(tmp_path))
    response = TestClient(app).get("/api/reports?type=roadmap")
    assert response.status_code == 400
