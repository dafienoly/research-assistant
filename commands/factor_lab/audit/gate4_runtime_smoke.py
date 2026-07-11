"""Gate 4 — Runtime Smoke / Integration Gate

检查代码是否真实可运行：
  1. 核心模块 import 检查
  2. CLI dry-run (hermes_cli.py --dry-run)
  3. 数据源 health check
  4. pytest 执行（委托 Gate 3 的 pytest runner）
  5. 报告产物生成检查
  6. 显式报错检查（不允许静默 fallback）
  7. 前端 TypeScript 类型检查（变更含 .ts/.tsx 时运行 tsc --noEmit）
  8. API 端点冒烟测试（变更路由 GET 无参端点做 curl 验证）
"""

from __future__ import annotations
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .base import AuditFinding, AuditReport, Severity
from .git_utils import get_all_changed_files, BASE, COMMANDS

VENV = str(BASE / ".venv_quant" / "bin" / "python3")
PYTHON = VENV
FRONTEND_DIR = BASE / "commands" / "frontend"
TSC_BIN = str(FRONTEND_DIR / "node_modules" / ".bin" / "tsc")
API_BASE = "http://127.0.0.1:8766"


def _git_diff_files() -> list[str]:
    return get_all_changed_files()


def _get_new_py_files() -> list[str]:
    """获取新增的 .py 文件（不含测试）。"""
    files = []
    for f in _git_diff_files():
        if not f.endswith(".py"):
            continue
        if "/tests/" in f or f.startswith("tests/") or f.startswith("test_"):
            continue
        files.append(f)
    return files


# ─── 1. Import 检查 ────────────────────────────────────────────

def _check_imports(file_paths: list[str]) -> list[AuditFinding]:
    """对新文件做 import 检查（编译 + 模块导入）。"""
    findings: list[AuditFinding] = []
    for fp in file_paths:
        candidates = [BASE / fp, COMMANDS / fp, Path(fp)]
        full = None
        for c in candidates:
            if c.is_file():
                full = c
                break
        if not full:
            continue

        # 语法检查
        try:
            compile(full.read_text(encoding="utf-8", errors="replace"),
                    filename=str(full), mode="exec")
        except SyntaxError as e:
            findings.append(AuditFinding(
                gate="gate4", severity="FAIL", category="SYNTAX_ERROR",
                file=fp, message=f"语法错误: {e.msg}",
                detail=f"line {e.lineno}: {e.text}",
            ))
            continue

        # 模块 import 检查（如果是可导入的模块路径）
        mod_path = _to_module_path(fp)
        if mod_path:
            try:
                interpreter = (
                    str(BASE / ".venv_vectorbt" / "bin" / "python")
                    if mod_path == "vectorbt_worker"
                    else PYTHON
                )
                environment = os.environ.copy()
                environment["PYTHONPATH"] = os.pathsep.join([str(BASE), str(COMMANDS)])
                r = subprocess.run(
                    [interpreter, "-c", f"import {mod_path}"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(BASE),
                    env=environment,
                )
                if r.returncode != 0:
                    err = (r.stderr or r.stdout)[:200]
                    findings.append(AuditFinding(
                        gate="gate4", severity="FAIL", category="IMPORT_FAILED",
                        file=fp, message=f"模块导入失败: {mod_path}",
                        detail=err,
                    ))
                else:
                    findings.append(AuditFinding(
                        gate="gate4", severity="INFO", category="IMPORT_OK",
                        file=fp, message=f"模块导入成功: {mod_path}",
                    ))
            except subprocess.TimeoutExpired:
                findings.append(AuditFinding(
                    gate="gate4", severity="WARN", category="IMPORT_TIMEOUT",
                    file=fp, message=f"模块导入超时: {mod_path}",
                ))

    return findings


def _to_module_path(fp: str) -> Optional[str]:
    """转换 commands/factor_lab/foo.py → factor_lab.foo"""
    p = Path(fp)
    if p.suffix != ".py":
        return None
    # 去掉 commands/ 前缀
    parts = fp.replace("\\", "/").split("/")
    if parts[0] == "commands":
        parts = parts[1:]
    # 去掉 .py
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    # 忽略 __init__ / conftest / setup
    if parts[-1] in ("__init__", "conftest", "setup"):
        return None
    if not parts or parts[-1] == "":
        return None
    return ".".join(parts)


# ─── 2. CLI dry-run ────────────────────────────────────────────

def _run_cli_dry_run() -> list[AuditFinding]:
    """运行 CLI dry-run 命令。"""
    findings: list[AuditFinding] = []
    cli = str(COMMANDS / "hermes_cli.py")

    cmds = [
        ("--dry-run", ["--dry-run"]),
    ]

    for label, args in cmds:
        try:
            r = subprocess.run(
                [PYTHON, cli] + args,
                capture_output=True, text=True, timeout=15,
                cwd=str(COMMANDS),
            )
            if r.returncode == 0:
                findings.append(AuditFinding(
                    gate="gate4", severity="INFO", category="CLI_SMOKE_OK",
                    file="", message=f"CLI {label} 运行成功 (exit=0)",
                ))
            else:
                findings.append(AuditFinding(
                    gate="gate4", severity="WARN", category="CLI_SMOKE_FAILED",
                    file="", message=f"CLI {label} 返回非零: exit={r.returncode}",
                    detail=(r.stderr or r.stdout)[:300],
                ))
        except FileNotFoundError:
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="RUNTIME_COMMAND_NOT_AVAILABLE",
                file="", message=f"CLI 命令不可用: {label}",
            ))
        except subprocess.TimeoutExpired:
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="CLI_SMOKE_FAILED",
                file="", message=f"CLI {label} 超时",
            ))

    return findings


# ─── 3. 数据源 health check ────────────────────────────────────

def _run_data_health_checks() -> list[AuditFinding]:
    """运行数据源健康检查。"""
    findings: list[AuditFinding] = []
    # 检查是否有 data:health-check 命令
    cli = str(COMMANDS / "hermes_cli.py")
    checks = [
        ("data:health-check --dry-run", ["data:health-check", "--dry-run"]),
        ("factor:signal --dry-run", ["factor:signal", "--dry-run"]),
        ("premarket --dry-run", ["premarket", "--dry-run"]),
        ("alpha:factory --status", ["alpha:factory", "--status"]),
    ]

    for label, args in checks:
        try:
            r = subprocess.run(
                [PYTHON, cli] + args,
                capture_output=True, text=True, timeout=15,
                cwd=str(COMMANDS),
            )
            if r.returncode == 0:
                findings.append(AuditFinding(
                    gate="gate4", severity="INFO", category="DATA_HEALTH_OK",
                    file="", message=f"数据源 {label}: 正常",
                ))
            else:
                out = (r.stderr or r.stdout)[:200]
                if "not found" in out.lower() or "unknown" in out.lower() or "not recognized" in out.lower():
                    findings.append(AuditFinding(
                        gate="gate4", severity="WARN", category="RUNTIME_COMMAND_NOT_AVAILABLE",
                        file="", message=f"命令不可用: {label}",
                        detail=out,
                    ))
                else:
                    findings.append(AuditFinding(
                        gate="gate4", severity="WARN", category="DATA_HEALTH_FAILED",
                        file="", message=f"数据源 {label}: 异常 (exit={r.returncode})",
                        detail=out,
                    ))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="RUNTIME_COMMAND_NOT_AVAILABLE",
                file="", message=f"命令不可用: {label}",
            ))

    return findings


# ─── 4. pytest 委托 ────────────────────────────────────────────

def _run_pytest_standard() -> tuple[str, list[AuditFinding]]:
    """运行标准 pytest 测试套件。"""
    findings: list[AuditFinding] = []
    log = ""
    try:
        test_files = sorted(str(path) for path in (COMMANDS / "tests").glob("test_vnext*.py"))
        test_files.append(str(COMMANDS / "tests" / "test_routes_vnext.py"))
        environment = os.environ.copy()
        environment["TMPDIR"] = "/tmp"
        environment["PYTHONPATH"] = os.pathsep.join([str(BASE), str(COMMANDS)])
        r = subprocess.run(
            [VENV, "-m", "pytest", *test_files, "-q", "--tb=line", "--no-header",
             "--basetemp=/tmp/hermes-anti-cheat-gate4"],
            capture_output=True, text=True, timeout=180,
            cwd=str(COMMANDS), env=environment,
        )
        output = r.stdout + r.stderr
        log = output[:3000]

        if r.returncode == 0:
            findings.append(AuditFinding(
                gate="gate4", severity="INFO", category="PYTEST_PASSED",
                file="", message="标准 pytest 套件通过",
            ))
        else:
            fail_lines = [l for l in output.splitlines() if "FAILED" in l]
            for fl in fail_lines[:5]:
                findings.append(AuditFinding(
                    gate="gate4", severity="FAIL", category="PYTEST_FAILED",
                    file="", message=f"标准 pytest 失败: {fl.strip()[:120]}",
                ))
            if not fail_lines:
                findings.append(AuditFinding(
                    gate="gate4", severity="FAIL", category="PYTEST_FAILED",
                    file="", message=f"标准 pytest 返回码 {r.returncode}",
                ))

    except subprocess.TimeoutExpired:
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="PYTEST_TIMEOUT",
            file="", message="标准 pytest 超时（120s）",
        ))
    except Exception as e:
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="PYTEST_ERROR",
            file="", message=f"标准 pytest 执行失败: {e}",
        ))
    return log, findings


# ─── 5. 静默 fallback 检查 ─────────────────────────────────────

def _check_silent_fallback(file_paths: list[str]) -> list[AuditFinding]:
    """检查新增代码中是否存在静默 fallback（异常被吞且无日志/标记）。
    排除审计系统自身文件（audit/ 目录）。
    """
    findings: list[AuditFinding] = []
    for fp in file_paths:
        if not fp.endswith(".py"):
            continue
        # 排除审计系统自身
        if "/audit/" in fp or "/factor_lab/audit/" in fp:
            continue
        candidates = [BASE / fp, COMMANDS / fp, Path(fp)]
        full = None
        for c in candidates:
            if c.is_file():
                full = c
                break
        if not full:
            continue
        try:
            src = full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # 检查 except 后无日志/无审计记录
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # except ...: pass 但前面没有 logger
            if "except" in stripped and "pass" in stripped:
                # 检查前几行是否有 logger/logging/audit
                ctx = lines[max(0, i - 5):i]
                ctx_text = "\n".join(ctx)
                if not re.search(r"(logger|logging|audit|print|warn|error|raise)", ctx_text):
                    findings.append(AuditFinding(
                        gate="gate4", severity="WARN", category="SILENT_FALLBACK",
                        file=fp, line=i,
                        message="静默异常处理（except + pass 且无日志）",
                        detail="建议至少使用 logger.warning() 记录异常",
                    ))

    return findings


# ─── 7. 前端 TypeScript 类型检查 ─────────────────────────────

def _check_frontend_tsc() -> list[AuditFinding]:
    """当变更含 .ts/.tsx 时，运行 tsc --noEmit 验证类型。"""
    findings: list[AuditFinding] = []

    changed = _git_diff_files()
    has_ts_changes = any(
        f.endswith((".ts", ".tsx")) and "frontend/src/" in f.replace("\\", "/")
        for f in changed
    )
    if not has_ts_changes:
        findings.append(AuditFinding(
            gate="gate4", severity="INFO", category="FE_TSC_SKIP",
            file="", message="无前端 TypeScript 变更，跳过 tsc 检查",
        ))
        return findings

    if not Path(TSC_BIN).is_file():
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="FE_TSC_NOT_FOUND",
            file="", message="tsc 未找到，请执行 npm install",
            detail=f"期待路径: {TSC_BIN}",
        ))
        return findings

    if not FRONTEND_DIR.is_dir():
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="FE_TSC_NOT_FOUND",
            file="", message="前端目录不存在",
            detail=str(FRONTEND_DIR),
        ))
        return findings

    try:
        r = subprocess.run(
            [TSC_BIN, "--noEmit"],
            capture_output=True, text=True, timeout=60,
            cwd=str(FRONTEND_DIR),
        )
        if r.returncode == 0:
            findings.append(AuditFinding(
                gate="gate4", severity="INFO", category="FE_TSC_PASSED",
                file="", message="TypeScript 类型检查通过 (tsc --noEmit)",
            ))
        else:
            # 提取前 10 个错误
            err_lines = (r.stdout or r.stderr).splitlines()
            ts_errors = [l.strip() for l in err_lines if "error TS" in l or "error " in l.lower()]
            for err in ts_errors[:10]:
                findings.append(AuditFinding(
                    gate="gate4", severity="FAIL", category="FE_TSC_ERROR",
                    file="", message=f"TypeScript 类型错误",
                    detail=err[:200],
                ))
            if not ts_errors:
                findings.append(AuditFinding(
                    gate="gate4", severity="FAIL", category="FE_TSC_ERROR",
                    file="", message="TypeScript 类型检查失败 (tsc --noEmit)",
                    detail=(r.stdout or r.stderr)[:500],
                ))
    except subprocess.TimeoutExpired:
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="FE_TSC_TIMEOUT",
            file="", message="tsc --noEmit 超时（60s）",
        ))
    except FileNotFoundError:
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="FE_TSC_NOT_FOUND",
            file="", message="tsc 命令不可用",
        ))
    except Exception as e:
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="FE_TSC_ERROR",
            file="", message=f"tsc 执行异常: {e}",
        ))

    return findings


# ─── 8. API 端点冒烟测试 ─────────────────────────────────────

def _has_route_decorators(filepath: Path) -> bool:
    """检查文件是否包含 FastAPI 路由装饰器。"""
    if not filepath.is_file():
        return False
    try:
        src = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return bool(re.search(r"@(router|app)\.(get|post|put|delete|patch)\(", src))


def _extract_routes_from_file(filepath: Path) -> list[tuple[str, str]]:
    """从 Python 路由文件中提取定义的 URL 路径和 HTTP 方法。"""
    if not filepath.is_file():
        return []
    try:
        src = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    routes = []
    for m in re.finditer(
        r"""@(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']""",
        src,
    ):
        routes.append((m.group(1).upper(), m.group(2)))
    return routes


def _router_prefix(filepath: Path) -> str:
    """Extract a static APIRouter prefix so app and router mounts compose correctly."""
    src = filepath.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"APIRouter\s*\(\s*prefix\s*=\s*[\"']([^\"']*)[\"']", src)
    return match.group(1) if match else ""


def _check_api_endpoint_smoke() -> list[AuditFinding]:
    """对变更路由文件中定义的 GET 无参端点做 curl 冒烟测试。"""
    findings: list[AuditFinding] = []

    changed_py = _get_new_py_files()
    route_files = []
    for fp in changed_py:
        candidates = [BASE / fp, COMMANDS / fp, Path(fp)]
        for c in candidates:
            if c.is_file() and _has_route_decorators(c):
                route_files.append(c)
                break

    if not route_files:
        findings.append(AuditFinding(
            gate="gate4", severity="INFO", category="API_SMOKE_SKIP",
            file="", message="无路由文件变更，跳过 API 端点冒烟测试",
        ))
        return findings

    # 收集所有变更路由文件中的 GET 无参路径
    test_targets = []
    for rf in route_files:
        routes = _extract_routes_from_file(rf)
        router_prefix = _router_prefix(rf)
        for method, route in routes:
            if method != "GET":
                continue
            # 跳过含路径参数的端点（{param} 或 :param）
            if "{" in route or ":" in route.replace("\\", "/"):
                continue
            test_targets.append((str(rf), f"{router_prefix}{route}"))

    if not test_targets:
        findings.append(AuditFinding(
            gate="gate4", severity="INFO", category="API_SMOKE_SKIP",
            file="", message="变更路由中无 GET 无参端点可测",
        ))
        return findings

    tested = 0
    for rf_path, route in test_targets:
        url = f"{API_BASE}/api{route}" if not route.startswith("/api") else f"{API_BASE}{route}"
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=10,
            )
            http_code = r.stdout.strip()
            tested += 1

            if http_code in ("200", "201", "204"):
                findings.append(AuditFinding(
                    gate="gate4", severity="INFO", category="API_SMOKE_OK",
                    file=rf_path, message=f"GET {route} → {http_code}",
                ))
            elif http_code in ("401", "403"):
                # 带认证的端点，非错误
                findings.append(AuditFinding(
                    gate="gate4", severity="INFO", category="API_SMOKE_AUTH",
                    file=rf_path, message=f"GET {route} → {http_code} (需要认证)",
                ))
            elif http_code == "404":
                findings.append(AuditFinding(
                    gate="gate4", severity="WARN", category="API_SMOKE_404",
                    file=rf_path, message=f"GET {route} → 404 (路由未注册或挂载前缀不匹配)",
                ))
            elif http_code == "500":
                findings.append(AuditFinding(
                    gate="gate4", severity="FAIL", category="API_SMOKE_500",
                    file=rf_path, message=f"GET {route} → 500 (服务端错误)",
                ))
            else:
                findings.append(AuditFinding(
                    gate="gate4", severity="WARN", category="API_SMOKE_UNEXPECTED",
                    file=rf_path, message=f"GET {route} → HTTP {http_code}",
                ))
        except subprocess.TimeoutExpired:
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="API_SMOKE_TIMEOUT",
                file=rf_path, message=f"GET {route} 超时（10s）",
            ))
        except Exception as e:
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="API_SMOKE_ERROR",
                file=rf_path, message=f"GET {route} 请求失败: {e}",
            ))

    findings.append(AuditFinding(
        gate="gate4", severity="INFO", category="API_SMOKE_SUMMARY",
        file="", message=f"API 端点冒烟: {tested}/{len(test_targets)} 端点已测试",
    ))
    return findings


# ─── 主入口 ───────────────────────────────────────────────────

def run_gate4(report: AuditReport) -> AuditReport:
    """执行 Gate 4: Runtime Smoke / Integration Gate"""
    report.gates_run.append("gate4")

    new_py_files = _get_new_py_files()
    report.add(AuditFinding(
        gate="gate4", severity="INFO", category="RUNTIME_GATE_START",
        file="", message=f"Runtime Smoke Gate: {len(new_py_files)} 个新 Python 文件",
    ))

    # 1. Import 检查
    import_findings = _check_imports(new_py_files)
    report.extend(import_findings)

    # 2. CLI dry-run
    cli_findings = _run_cli_dry_run()
    report.extend(cli_findings)

    # 3. 数据源 health check
    health_findings = _run_data_health_checks()
    report.extend(health_findings)

    # 4. 标准 pytest（新增/关联测试）
    pytest_log, pytest_findings = _run_pytest_standard()
    report.extend(pytest_findings)

    # 5. 静默 fallback 检查
    fallback_findings = _check_silent_fallback(new_py_files)
    report.extend(fallback_findings)

    # 6. 前端 TypeScript 类型检查
    tsc_findings = _check_frontend_tsc()
    report.extend(tsc_findings)

    # 7. API 端点冒烟测试
    api_findings = _check_api_endpoint_smoke()
    report.extend(api_findings)

    return report
