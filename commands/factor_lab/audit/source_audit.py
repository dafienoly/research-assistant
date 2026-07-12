"""受控源码审计。

这是 Hermes 代码审计的新唯一执行内核。它只读取 Git 变更中的源码文件，
明确排除 data/artifacts/临时目录，不运行 pytest、Semgrep、GitNexus 或任何
会递归扫描数据盘的旧 Gate。大版本发布前由 runner 显式调用。
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .base import AuditFinding, AuditReport
from .storage import AuditStore


SOURCE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".yml", ".yaml", ".toml"})
EXCLUDED_PARTS = frozenset({
    ".git",
    ".venv",
    ".venv_quant",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "cache",
    "caches",
    "tmp",
    "temp",
    "data",
    "artifacts",
    "research_outputs",
    "logs",
})
SOURCE_ROOTS = ("commands", "scripts", ".github", "configs")
MAX_SOURCE_FILES = 20_000
MAX_SOURCE_BYTES = 2_000_000
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(token|secret|password)\s*[=:]\s*['\"][^'\"]{20,}['\"]"),
)


@dataclass(frozen=True)
class SourceSelection:
    files: list[str]
    skipped: list[str]


def _excluded(relative: str) -> bool:
    parts = set(Path(relative).parts)
    return bool(parts & EXCLUDED_PARTS)


def _is_source(relative: str) -> bool:
    path = Path(relative)
    return bool(relative) and not _excluded(relative) and path.suffix.lower() in SOURCE_SUFFIXES


def iter_source_files(root: Path, include_tests: bool = True):
    """Yield bounded source files; never descends into data or temp trees."""
    stack: list[tuple[Path, int]] = []
    for name in SOURCE_ROOTS:
        candidate = root / name
        if candidate.is_dir():
            stack.append((candidate, 0))
        elif candidate.is_file() and _is_source(name):
            yield candidate
    for name in ("pyproject.toml", "setup.cfg", "package.json"):
        candidate = root / name
        if candidate.is_file() and _is_source(name):
            yield candidate

    yielded = 0
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        directories: list[Path] = []
        files: list[Path] = []
        for entry in entries:
            if entry.is_symlink():
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    relative = Path(entry.path).relative_to(root).as_posix()
                    if _excluded(relative) or (not include_tests and "tests" in Path(relative).parts):
                        continue
                    directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    relative = Path(entry.path).relative_to(root).as_posix()
                    if _is_source(relative):
                        files.append(Path(entry.path))
            except OSError:
                continue
        for path in sorted(files, key=lambda item: item.as_posix()):
            if yielded >= MAX_SOURCE_FILES:
                return
            yielded += 1
            yield path
        for path in reversed(sorted(directories, key=lambda item: item.as_posix())):
            stack.append((path, depth + 1))


def _git_paths(root: Path, scope: str, base_ref: str, paths: list[str]) -> list[str]:
    if paths:
        return [str(Path(item).as_posix()) for item in paths]
    commands = {
        "staged": ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        "compare": ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        "working-tree": ["git", "diff", "--name-only", "--diff-filter=ACMR"],
    }
    command = commands.get(scope, commands["working-tree"])
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    values = result.stdout.splitlines() if result.returncode == 0 else []
    if scope == "working-tree":
        staged = subprocess.run(commands["staged"], cwd=root, text=True, capture_output=True, check=False)
        values.extend(staged.stdout.splitlines())
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        values.extend(untracked.stdout.splitlines())
    return values


def select_sources(root: Path, scope: str, base_ref: str, paths: list[str] | None = None) -> SourceSelection:
    selected: set[str] = set()
    skipped: set[str] = set()
    for raw in _git_paths(root, scope, base_ref, paths or []):
        relative = raw.strip().replace("\\", "/")
        if not relative:
            continue
        if _excluded(relative) or Path(relative).suffix.lower() not in SOURCE_SUFFIXES:
            skipped.add(relative)
            continue
        target = (root / relative).resolve()
        if target.is_file() and target.is_relative_to(root.resolve()) and _is_source(relative):
            try:
                if target.stat().st_size > MAX_SOURCE_BYTES:
                    skipped.add(relative)
                else:
                    selected.add(relative)
            except OSError:
                skipped.add(relative)
    return SourceSelection(sorted(selected), sorted(skipped))


def _digest(root: Path, files: list[str], profile: str, scope: str, major_version: str) -> str:
    digest = hashlib.sha256(f"source-only:{major_version}:{profile}:{scope}".encode())
    for relative in files:
        digest.update(relative.encode())
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()[:24]


def _finding(gate: str, severity: str, rule: str, file: str, message: str, detail: str = "") -> AuditFinding:
    return AuditFinding(
        gate=gate,
        severity=severity,
        category=rule.upper().replace("-", "_"),
        file=file,
        message=message,
        detail=detail[:2000],
        rule_id=rule,
        blocking=severity == "FAIL",
    )


def run_source_audit(
    *,
    repo_root: Path,
    store: AuditStore,
    profile: str,
    scope: str,
    base_ref: str,
    paths: list[str],
    major_version: str,
    trigger: str,
    requested_by: str,
) -> AuditReport:
    root = repo_root.resolve()
    selection = select_sources(root, scope, base_ref, paths)
    digest = _digest(root, selection.files, profile, scope, major_version)
    existing = next(
        (
            item
            for item in store.list_runs()
            if item.get("change_set_hash") == digest
            and item.get("profile") == profile
            and item.get("version") == major_version
            and item.get("state") == "passed"
        ),
        None,
    )
    if existing:
        return _from_dict(existing)

    report = AuditReport(
        run_id=f"audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        version=major_version,
        profile=profile,
        scope=scope,
        change_set_hash=digest,
        trigger=trigger,
        requested_by=requested_by,
    )
    report.gates_run.append("source")
    report.extras["files"] = selection.files
    report.extras["skipped_paths"] = selection.skipped
    report.extras["scan_policy"] = {
        "mode": "major-version-only",
        "source_only": True,
        "excluded_parts": sorted(EXCLUDED_PARTS),
        "max_source_files": MAX_SOURCE_FILES,
        "max_source_bytes": MAX_SOURCE_BYTES,
        "pytest": False,
        "semgrep": False,
        "gitnexus": False,
        "data_scan": False,
        "temp_scan": False,
    }
    if not selection.files:
        report.add(_finding("source", "INFO", "no-source-changes", "", "没有可审计的源码变更"))

    python_files: list[str] = []
    for relative in selection.files:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.add(_finding("source", "FAIL", "read-source", relative, "源码读取失败", str(exc)))
            continue
        if path.suffix.lower() == ".py":
            python_files.append(relative)
            try:
                ast.parse(text, filename=relative)
            except SyntaxError as exc:
                report.add(_finding("source", "FAIL", "python-syntax", relative, str(exc)))
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            report.add(_finding("source", "FAIL", "secret-scan", relative, "疑似凭据进入源码变更"))
        if path.suffix.lower() == ".sh" and re.search(r"\bpkill\s+(?:-[^\s]+\s+)*-f\b", text):
            report.add(_finding("source", "FAIL", "global-process-kill", relative, "禁止使用 pkill -f"))

    ruff = shutil.which("ruff")
    if ruff and python_files:
        result = subprocess.run(
            [ruff, "check", "--select", "E9,F63,F7,F82", *python_files],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode:
            report.add(_finding("source", "FAIL", "ruff", "", "Ruff 源码检查失败", result.stdout + result.stderr))
    elif python_files:
        report.add(_finding("source", "WARN", "ruff-unavailable", "", "Ruff 不可用，跳过源码 lint"))

    report.state = "passed" if report.passed else "failed"
    report.finished_at = report.started_at
    store.save(report)
    return report


def _from_dict(data: dict) -> AuditReport:
    report = AuditReport(
        run_id=data.get("run_id", ""),
        profile=data.get("profile", "fast"),
        scope=data.get("scope", "working-tree"),
        state=data.get("state", "passed"),
        passed=data.get("passed", True),
        version=data.get("version", ""),
        change_set_hash=data.get("change_set_hash", ""),
        gates_run=data.get("gates_run", []),
        started_at=data.get("started_at", ""),
        finished_at=data.get("finished_at", ""),
        extras=data.get("extras", {}),
        trigger=data.get("trigger", "major-version"),
        requested_by=data.get("requested_by", "local"),
    )
    for item in data.get("findings", []):
        report.add(AuditFinding(**{key: value for key, value in item.items() if key in AuditFinding.__dataclass_fields__}))
    return report
