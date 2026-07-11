"""Single-flight coordinator for code audit runs."""

from __future__ import annotations

import fcntl
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .base import CST, AuditFinding, AuditReport
from .checks import change_hash, changed_files, fast_checks, full_checks, security_checks
from .storage import AuditStore


@dataclass(frozen=True)
class AuditRequest:
    repo_root: Path
    profile: str = "fast"
    scope: str = "working-tree"
    base_ref: str = "main"
    paths: list[str] = field(default_factory=list)
    trigger: str = "manual"
    requested_by: str = "local"


class AuditCoordinator:
    def __init__(self, store: AuditStore | None = None):
        self.store = store or AuditStore()

    def run(self, request: AuditRequest) -> AuditReport:
        root = request.repo_root.resolve()
        files = changed_files(root, request.scope, request.base_ref, request.paths)
        digest = change_hash(root, files, request.profile, request.scope)
        existing = next((item for item in self.store.list_runs() if item.get("change_set_hash") == digest and item.get("profile") == request.profile), None)
        if existing and existing.get("state") == "passed":
            return self._from_dict(existing)

        self.store.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.store.root / ".audit.lock"
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("已有代码审计正在运行") from exc
            run_id = f"audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            report = AuditReport(run_id=run_id, profile=request.profile, scope=request.scope,
                                 change_set_hash=digest, trigger=request.trigger,
                                 requested_by=request.requested_by)
            report.extras["files"] = files
            try:
                fast_checks(report, root, files)
                if request.profile in {"full", "security"}:
                    full_checks(report, root, files, request.scope, request.base_ref)
                if request.profile == "security":
                    security_checks(report, root, files)
                self._deduplicate(report)
                report.state = "passed" if report.passed else "failed"
            except Exception as exc:
                report.add(AuditFinding(gate="coordinator", severity="FAIL", category="RUN_ERROR",
                                        file="", message="审计运行异常", detail=str(exc)))
                report.state = "error"
            report.finished_at = datetime.now(CST).isoformat()
            self.store.save(report)
            return report

    @staticmethod
    def _deduplicate(report: AuditReport) -> None:
        unique = {}
        for finding in report.findings:
            unique[finding.fingerprint] = finding
        report.findings = list(unique.values())

    @staticmethod
    def _from_dict(data: dict) -> AuditReport:
        report = AuditReport(
            run_id=data.get("run_id", ""), profile=data.get("profile", "fast"),
            scope=data.get("scope", "working-tree"), state=data.get("state", "passed"),
            change_set_hash=data.get("change_set_hash", ""), passed=data.get("passed", True),
            gates_run=data.get("gates_run", []), started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""), durations=data.get("durations", {}),
            extras=data.get("extras", {}), trigger=data.get("trigger", "manual"),
            requested_by=data.get("requested_by", "local"),
        )
        for item in data.get("findings", []):
            report.add(AuditFinding(**{key: value for key, value in item.items() if key in AuditFinding.__dataclass_fields__}))
        return report
