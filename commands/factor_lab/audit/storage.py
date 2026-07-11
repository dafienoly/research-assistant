"""Single-writer storage for code audit runs outside the Git worktree."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .base import AuditReport


def audit_home() -> Path:
    configured = os.environ.get("HERMES_CODE_AUDIT_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".hermes/state/research-assistant/code-audits"


class AuditStore:
    def __init__(self, root: Path | None = None, keep_runs: int = 20, keep_days: int = 14):
        self.root = root or audit_home()
        self.keep_runs = keep_runs
        self.keep_days = keep_days

    def save(self, report: AuditReport) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        run_dir = self.root / report.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        target = run_dir / "report.json"
        temporary = run_dir / ".report.json.tmp"
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
        latest_tmp = self.root / ".latest.json.tmp"
        latest_tmp.write_text(payload, encoding="utf-8")
        os.replace(latest_tmp, self.root / "latest.json")
        self.prune()
        return target

    def list_runs(self, limit: int = 50) -> list[dict]:
        if not self.root.exists():
            return []
        reports = []
        for path in self.root.glob("*/report.json"):
            try:
                reports.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        reports.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        return reports[:limit]

    def load(self, run_id: str) -> dict | None:
        if not run_id or "/" in run_id or ".." in run_id:
            return None
        path = self.root / run_id / "report.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def prune(self) -> None:
        if not self.root.exists():
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.keep_days)
        run_dirs = sorted(
            (p for p in self.root.iterdir() if p.is_dir() and (p / "report.json").exists()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for index, path in enumerate(run_dirs):
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if index >= self.keep_runs and modified < cutoff:
                shutil.rmtree(path, ignore_errors=True)
