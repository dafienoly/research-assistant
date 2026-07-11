import json
import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from factor_lab.api_server.main import app
import factor_lab.api_server.routes_code_audit as code_audit_routes
from factor_lab.api_server.services.audit_service import AuditService
from factor_lab.audit.coordinator import AuditCoordinator, AuditRequest
from factor_lab.audit.storage import AuditStore
from factor_lab.leader.ops_dashboard import SERVICE_DEFS


def _repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "audit@test.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Audit Test"], cwd=path, check=True)
    return path


def test_fast_profile_is_path_scoped_and_persists_outside_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    source = repo / "broken.py"
    source.write_text("def broken(:\n", encoding="utf-8")
    store = AuditStore(tmp_path / "state")
    report = AuditCoordinator(store).run(AuditRequest(repo_root=repo, profile="fast", paths=["broken.py"]))
    assert report.state == "failed"
    assert any(item.rule_id == "python-syntax" for item in report.findings)
    assert (tmp_path / "state" / report.run_id / "report.json").exists()
    assert not (repo / "agent_tasks").exists()


def test_same_change_hash_reuses_completed_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    (repo / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
    coordinator = AuditCoordinator(AuditStore(tmp_path / "state"))
    request = AuditRequest(repo_root=repo, profile="fast", paths=["ok.py"])
    first = coordinator.run(request)
    second = coordinator.run(request)
    assert second.run_id == first.run_id


def test_same_failed_change_hash_is_retried(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    (repo / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    coordinator = AuditCoordinator(AuditStore(tmp_path / "state"))
    request = AuditRequest(repo_root=repo, profile="fast", paths=["broken.py"])
    first = coordinator.run(request)
    second = coordinator.run(request)
    assert first.state == second.state == "failed"
    assert second.run_id != first.run_id


def test_operational_ledger_survives_restart_and_has_hash_chain(tmp_path):
    path = tmp_path / "events.jsonl"
    service = AuditService(path=path)
    first = service.record("config_change", action="update")
    second = service.record("config_change", action="update")
    assert second.prev_hash == first.event_hash
    restored = AuditService(path=path)
    assert restored.get_stats()["total_events"] == 2
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["event_hash"] == second.event_hash


def test_removed_agent_routes_are_not_registered():
    paths = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        original = getattr(route, "original_router", None)
        prefix = getattr(getattr(route, "include_context", None), "prefix", "")
        if original:
            paths.update(prefix + child.path for child in original.routes if hasattr(child, "path"))
    assert "/api/code-audits/runs" in paths
    assert "/api/roadmap" not in paths
    assert "/api/jobs/run" not in paths
    assert "/api/agent-console/sessions" not in paths


def test_ops_catalog_contains_no_agent_automation():
    assert set(SERVICE_DEFS) == {"dashboard", "mcp", "vite"}


def test_code_audit_api_preserves_paths_scope(monkeypatch):
    class Report:
        def __init__(self, request):
            self.request = request

        def to_dict(self):
            return {"scope": self.request.scope, "paths": self.request.paths}

    class Coordinator:
        def run(self, request):
            return Report(request)

    monkeypatch.setattr(code_audit_routes, "AuditCoordinator", Coordinator)
    token = os.environ.get("HERMES_UI_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = TestClient(app).post(
        "/api/code-audits/trigger",
        headers=headers,
        json={
            "profile": "fast",
            "scope": "paths",
            "paths": ["commands/factor_lab/audit/runner.py"],
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["scope"] == "paths"
    assert response.json()["data"]["paths"] == ["commands/factor_lab/audit/runner.py"]
