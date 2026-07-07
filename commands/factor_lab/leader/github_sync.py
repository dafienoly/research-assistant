"""GitHub sync helper for Hermes version milestones.

The helper is deliberately small and explicit. It stages repository changes,
creates a version commit when needed, and pushes to the configured GitHub repo.
It should be called only after local tests/acceptance for a version have passed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
REPO_ROOT = Path("/home/ly/.hermes/research-assistant")
REMOTE_URL = "https://github.com/dafienoly/research-assistant.git"
SYNC_LOG = REPO_ROOT / "agent_tasks" / "github_sync_latest.json"


@dataclass(frozen=True)
class GitHubSyncResult:
    status: str
    branch: str
    commit: str
    remote: str
    pushed: bool
    message: str
    generated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def sync_version(version: str, summary: str = "", dry_run: bool = False) -> dict:
    """Commit and push current repository state for a completed version."""
    _ensure_git_repo()
    _ensure_remote()
    branch = _git(["branch", "--show-current"]).strip() or "main"
    if branch != "main":
        # Keep this project simple: version milestones land on main unless the
        # user later asks for branch/PR release flow.
        _git(["checkout", "-B", "main"])
        branch = "main"

    status_before = _git(["status", "--porcelain"])
    if not status_before.strip():
        commit = _git(["rev-parse", "HEAD"]).strip()
        result = GitHubSyncResult(
            status="clean",
            branch=branch,
            commit=commit,
            remote=REMOTE_URL,
            pushed=False,
            message="No local changes to commit.",
            generated_at=_now(),
        )
        _write_sync_log(result)
        return result.to_dict()

    if dry_run:
        result = GitHubSyncResult(
            status="dry_run",
            branch=branch,
            commit="",
            remote=REMOTE_URL,
            pushed=False,
            message=status_before,
            generated_at=_now(),
        )
        _write_sync_log(result)
        return result.to_dict()

    _git(["add", "."])
    msg = f"chore: publish Hermes {version}"
    if summary:
        msg += f"\n\n{summary}"
    _git(["commit", "-m", msg])
    commit = _git(["rev-parse", "HEAD"]).strip()
    _git(["push", "-u", "origin", branch])
    result = GitHubSyncResult(
        status="pushed",
        branch=branch,
        commit=commit,
        remote=REMOTE_URL,
        pushed=True,
        message=msg,
        generated_at=_now(),
    )
    _write_sync_log(result)
    return result.to_dict()


def _ensure_git_repo() -> None:
    if not (REPO_ROOT / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=REPO_ROOT, check=True, timeout=30)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=REPO_ROOT, check=True, timeout=30)
        subprocess.run(["git", "config", "core.filemode", "false"], cwd=REPO_ROOT, check=True, timeout=30)


def _ensure_remote() -> None:
    remotes = _git(["remote"]).splitlines()
    if "origin" not in remotes:
        _git(["remote", "add", "origin", REMOTE_URL])
        return
    current = _git(["remote", "get-url", "origin"]).strip()
    if current != REMOTE_URL:
        _git(["remote", "set-url", "origin", REMOTE_URL])


def _git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return result.stdout


def _write_sync_log(result: GitHubSyncResult) -> None:
    SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
    SYNC_LOG.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now(CST).isoformat()
