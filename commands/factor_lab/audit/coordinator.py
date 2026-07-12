"""Single-flight coordinator for code audit runs."""

from __future__ import annotations

import fcntl
from dataclasses import dataclass, field
from pathlib import Path

from .base import AuditReport
from .source_audit import run_source_audit
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
    major_version: str = ""


class AuditCoordinator:
    def __init__(self, store: AuditStore | None = None):
        self.store = store or AuditStore()

    def run(self, request: AuditRequest) -> AuditReport:
        root = request.repo_root.resolve()
        if not request.major_version:
            # 旧 API/CLI 调用保持兼容，但不再触发任何扫描、pytest、Semgrep
            # 或 GitNexus。只有显式的大版本号才能进入源码审计内核。
            report = AuditReport(
                profile=request.profile,
                scope=request.scope,
                trigger=request.trigger,
                requested_by=request.requested_by,
                state="skipped",
            )
            report.gates_run.append("policy")
            report.extras["audit_mode"] = "major-version-only"
            report.extras["reason"] = "未提供 major_version，旧式代码审计已停用"
            report.extras["scan_policy"] = {
                "source_only": True,
                "data_scan": False,
                "temp_scan": False,
                "pytest": False,
                "semgrep": False,
                "gitnexus": False,
            }
            return report

        self.store.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.store.root / ".audit.lock"
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("已有大版本源码审计正在运行") from exc
            return run_source_audit(
                repo_root=root,
                store=self.store,
                profile=request.profile,
                scope=request.scope,
                base_ref=request.base_ref,
                paths=request.paths,
                major_version=request.major_version,
                trigger=request.trigger,
                requested_by=request.requested_by,
            )
