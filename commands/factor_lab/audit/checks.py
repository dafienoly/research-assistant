"""Deterministic checks for fast, full and security audit profiles."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .base import AuditFinding, AuditReport

INTERESTING = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".yaml", ".yml", ".json", ".toml"}
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(token|secret|password)\s*[=:]\s*['\"][^'\"]{12,}['\"]"),
)


def _run(command: list[str], root: Path, timeout: int = 30, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        return subprocess.CompletedProcess(command, 124, stdout, stderr + "\nTIMEOUT")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def changed_files(root: Path, scope: str, base_ref: str = "main", paths: list[str] | None = None) -> list[str]:
    if paths:
        candidates = paths
    elif scope == "staged":
        candidates = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], root).stdout.splitlines()
    elif scope == "compare":
        result = _run(["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"], root)
        candidates = result.stdout.splitlines() if result.returncode == 0 else []
    else:
        candidates = []
        for command in (
            ["git", "diff", "--name-only", "--diff-filter=ACMR"],
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            candidates.extend(_run(command, root).stdout.splitlines())
    normalized = []
    for value in candidates:
        relative = value.strip().replace("\\", "/")
        target = (root / relative).resolve()
        if relative and target.is_relative_to(root.resolve()) and target.is_file() and target.suffix.lower() in INTERESTING:
            normalized.append(relative)
    return sorted(set(normalized))


def change_hash(root: Path, files: list[str], profile: str, scope: str) -> str:
    digest = hashlib.sha256(f"{profile}:{scope}".encode())
    for relative in files:
        digest.update(relative.encode())
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()[:24]


def _finding(gate: str, severity: str, rule: str, file: str, message: str, detail: str = "", *, blocking: bool | None = None) -> AuditFinding:
    return AuditFinding(gate=gate, severity=severity, category=rule.upper().replace("-", "_"), file=file,
                        message=message, detail=detail[:2000], rule_id=rule, blocking=blocking)


def fast_checks(report: AuditReport, root: Path, files: list[str]) -> None:
    started = time.perf_counter()
    report.gates_run.append("fast")
    for relative in files:
        path = root / relative
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=relative)
            except SyntaxError as exc:
                report.add(_finding("fast", "FAIL", "python-syntax", relative, str(exc), blocking=True))
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                report.add(_finding("fast", "FAIL", "secret-scan", relative, "疑似凭据进入变更集", blocking=True))
                break
        if path.suffix == ".sh" and re.search(r"\bpkill\s+(?:-[^\s]+\s+)*-f\b", text):
            report.add(_finding("fast", "FAIL", "global-process-kill", relative, "禁止使用 pkill -f；必须终止自有 PID/进程组", blocking=True))

    diff_check = _run(["git", "diff", "--check"], root)
    if diff_check.returncode:
        report.add(_finding("fast", "FAIL", "diff-whitespace", "", "Git diff 格式检查失败", diff_check.stdout + diff_check.stderr))

    python_files = [f for f in files if f.endswith(".py")]
    ruff = shutil.which("ruff")
    if ruff and python_files:
        result = _run(
            [ruff, "check", "--select", "E9,F63,F7,F82", *python_files],
            root,
            timeout=20,
        )
        if result.returncode:
            report.add(_finding("fast", "FAIL", "ruff", "", "Ruff 检查失败", result.stdout + result.stderr))
    elif python_files:
        report.add(_finding("fast", "INFO", "ruff-unavailable", "", "Ruff 未安装，快速审计跳过该可选检查", blocking=False))

    mapping = root / "agent_tasks/traceability/latest_mapping.json"
    if mapping.exists():
        try:
            payload = json.loads(mapping.read_text(encoding="utf-8"))
            if not isinstance(payload.get("requirements"), list):
                raise ValueError("requirements must be a list")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            report.add(_finding("fast", "FAIL", "traceability-schema", str(mapping.relative_to(root)), str(exc)))
    report.durations["fast"] = round(time.perf_counter() - started, 3)


def _selected_tests(root: Path, files: list[str]) -> list[str]:
    tests: set[str] = set()
    for relative in files:
        path = Path(relative)
        if path.suffix == ".py" and "commands/factor_lab/" in relative:
            candidate = root / "commands/tests" / f"test_{path.stem}.py"
            if candidate.exists():
                tests.add(str(candidate.relative_to(root)))
        if "/audit/" in relative:
            core = root / "commands/tests/test_code_audit_system.py"
            if core.exists():
                tests.add(str(core.relative_to(root)))
            for gate in ("gate1_traceability", "gate3_test_coverage", "gate4_runtime_smoke"):
                if path.stem == gate:
                    candidate = root / "commands/tests" / f"test_{gate}.py"
                    if candidate.exists():
                        tests.add(str(candidate.relative_to(root)))
        if (
            "commands/factor_lab/decision_loop/" in relative
            or path.name in {"routes_decision_loop.py", "routes_qmt.py", "qmt_bridge.py"}
            or path.name == "decision_guard_once.py"
        ):
            for test_name in (
                "test_decision_loop.py",
                "test_decision_loop_api.py",
                "test_decision_loop_production.py",
                "test_qmt_integration.py",
            ):
                candidate = root / "commands/tests" / test_name
                if candidate.exists():
                    tests.add(str(candidate.relative_to(root)))
        if (
            "data_audit" in relative
            or "data_manager" in relative
            or "data_pipeline" in relative
            or relative.startswith("scripts/backup_data_to_d")
            or relative.startswith("scripts/restore_data_from_d")
            or relative.startswith("scripts/data_recovery_guard")
        ):
            for test_name in (
                "test_data_audit.py",
                "test_data_manager.py",
                "test_data_pipeline.py",
                "test_test_data_isolation.py",
            ):
                candidate = root / "commands/tests" / test_name
                if candidate.exists():
                    tests.add(str(candidate.relative_to(root)))
    return sorted(tests)


def full_checks(report: AuditReport, root: Path, files: list[str], scope: str, base_ref: str) -> None:
    started = time.perf_counter()
    report.gates_run.append("full")
    runner = root / ".gitnexus/run.cjs"
    if runner.exists():
        gn_scope = "staged" if scope == "staged" else ("compare" if scope == "compare" else "unstaged")
        command = ["node", str(runner), "detect-changes", "--scope", gn_scope]
        if gn_scope == "compare":
            command.extend(["--base-ref", base_ref])
        result = _run(command, root, timeout=30)
        report.extras["gitnexus"] = (result.stdout or result.stderr)[-4000:]
        if result.returncode:
            report.add(_finding("full", "WARN", "gitnexus-unavailable", "", "GitNexus 影响分析不可用", result.stderr, blocking=False))

    tests = _selected_tests(root, files)
    report.extras["selected_tests"] = tests
    if tests:
        python = root / ".venv_quant/bin/python"
        executable = str(python) if python.exists() else sys.executable
        temp_root = f"/tmp/hermes-code-audit-{report.run_id}"
        test_env = os.environ.copy()
        commands_path = str(root / "commands")
        existing_pythonpath = test_env.get("PYTHONPATH", "")
        test_env["PYTHONPATH"] = commands_path + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        test_env.update({"TMPDIR": "/tmp", "TEMP": "/tmp", "TMP": "/tmp"})
        # Internal TestClient suites validate contracts, not deployment auth.
        # An explicit empty value prevents a developer .env from changing test behavior.
        test_env["HERMES_UI_TOKEN"] = ""
        result = _run(
            [executable, "-m", "pytest", "-q", "-s", "--basetemp", temp_root, *tests],
            root,
            timeout=180,
            env=test_env,
        )
        report.extras["pytest"] = (result.stdout + result.stderr)[-8000:]
        if result.returncode:
            report.add(_finding("full", "FAIL", "impacted-tests", "", "受影响测试失败", result.stdout + result.stderr))
    else:
        report.add(_finding("full", "INFO", "no-impacted-tests", "", "本次变更未匹配到受影响测试", blocking=False))

    try:
        commands = str(root / "commands")
        if commands not in sys.path:
            sys.path.insert(0, commands)
        from fastapi.testclient import TestClient
        from factor_lab.api_server.main import app
        client = TestClient(app)
        token = os.environ.get("HERMES_UI_TOKEN", "").strip()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for endpoint in ("/api/health", "/api/status"):
            response = client.get(endpoint, headers=headers)
            if response.status_code != 200:
                report.add(_finding("full", "FAIL", "api-contract-smoke", endpoint, f"HTTP {response.status_code}"))
    except Exception as exc:
        report.add(_finding("full", "FAIL", "api-contract-smoke", "", "API 合约冒烟异常", str(exc)))
    report.durations["full"] = round(time.perf_counter() - started, 3)


def security_checks(report: AuditReport, root: Path, files: list[str]) -> None:
    started = time.perf_counter()
    report.gates_run.append("security")
    bundled = root / ".venv_quant/bin/semgrep"
    semgrep = shutil.which("semgrep") or (str(bundled) if bundled.exists() else None)
    config = root / "configs/audit/semgrep.yml"
    if not semgrep:
        report.add(_finding("security", "FAIL", "semgrep-unavailable", "", "安全档要求 Semgrep，但当前环境未安装"))
    elif files:
        scan_env = os.environ.copy()
        scan_env["SEMGREP_SEND_METRICS"] = "off"
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            value = scan_env.get(key, "").strip()
            if not value or value == "." or ("://" not in value and ":" not in value):
                scan_env.pop(key, None)
        result = _run(
            [semgrep, "--config", str(config), "--error", "--quiet", "--metrics", "off", *files],
            root, timeout=120, env=scan_env,
        )
        if result.returncode:
            report.add(_finding("security", "FAIL", "semgrep", "", "Semgrep 安全规则失败", result.stdout + result.stderr))
    report.add(_finding("security", "INFO", "llm-advisory", "", "LLM 语义审查默认关闭且不影响退出码", blocking=False))
    report.durations["security"] = round(time.perf_counter() - started, 3)
