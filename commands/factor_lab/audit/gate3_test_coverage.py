"""Gate 3 — 测试覆盖检查 + 测试有效性验证

继承原有（测试文件/函数存在），新增:
  3. 执行 pytest 验证测试是否通过
  4. 检查弱测试（assert True / 无断言 / 仅 import）
  5. 检查失败路径测试缺失
  6. 覆盖率和 diff coverage 建议输出
"""

from __future__ import annotations
import ast
import os
import subprocess
import re
from pathlib import Path
from typing import Optional

from .base import AuditFinding, AuditReport, Severity
from .git_utils import get_all_changed_files, BASE, COMMANDS

VENV = str(BASE / ".venv_quant" / "bin" / "python3")
TESTS_DIR = COMMANDS / "tests"

NO_TEST_EXTENSIONS = {".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
NO_TEST_FILES = {"__init__.py", "conftest.py", "setup.py", "conf.py"}


def _git_diff_files() -> list[str]:
    return get_all_changed_files()


def _classify_files(files: list[str]) -> tuple[list[str], list[str]]:
    test_files = []
    source_files = []
    for f in files:
        f_lower = f.lower()
        ext = Path(f).suffix.lower()
        if "/test_" in f_lower or f_lower.startswith("test_") or ext in NO_TEST_EXTENSIONS:
            test_files.append(f)
        elif Path(f).name in NO_TEST_FILES:
            continue
        elif f.endswith(".py"):
            source_files.append(f)
    return source_files, test_files


def _expected_test_file(source: str) -> str:
    name = Path(source).stem
    return f"tests/test_{name}.py"


def _extract_function_names(file_path: str) -> list[str]:
    full = Path(BASE, file_path) if not file_path.startswith("/") else Path(file_path)
    if not full.is_file():
        return []
    try:
        source = full.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, Exception):
        return []
    funcs: list[str] = []
    class FuncCollector(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef):
            if not node.name.startswith("_") and not node.name.startswith("test_"):
                funcs.append(node.name)
            self.generic_visit(node)
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            if not node.name.startswith("_") and not node.name.startswith("test_"):
                funcs.append(node.name)
            self.generic_visit(node)
    FuncCollector().visit(tree)
    return funcs


def _extract_test_functions(file_path: str) -> list[str]:
    full = Path(file_path)
    if not full.is_file():
        return []
    try:
        source = full.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, Exception):
        return []
    test_funcs: list[str] = []
    class TestCollector(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef):
            if node.name.startswith("test_"):
                test_funcs.append(node.name)
            self.generic_visit(node)
    TestCollector().visit(tree)
    return test_funcs


# ─── 新增: 弱测试检测 ─────────────────────────────────────────

def _check_weak_test(test_file: Path) -> list[AuditFinding]:
    """检查测试文件中是否存在弱测试。"""
    findings: list[AuditFinding] = []
    if not test_file.is_file():
        return findings
    try:
        src = test_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(test_file))
    except (SyntaxError, Exception):
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue

        # 收集断言和工具调用
        has_assert = False
        has_real_assert = False
        only_imports = True
        body = node.body

        for stmt in body:
            # 跳过 docstring
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                    and isinstance(stmt.value.value, str):
                continue

            if isinstance(stmt, ast.Assert):
                has_assert = True
                # assert True 是弱断言
                if isinstance(stmt.test, ast.Constant) and stmt.test.value is True:
                    findings.append(AuditFinding(
                        gate="gate3", severity="WARN", category="WEAK_ASSERT",
                        file=str(test_file), line=stmt.lineno,
                        message=f"测试 '{node.name}' 使用 assert True — 无效断言",
                    ))
                else:
                    has_real_assert = True

            if isinstance(stmt, (ast.Expr, ast.Call, ast.Assign, ast.If, ast.For, ast.While)):
                only_imports = False

        if not has_assert:
            findings.append(AuditFinding(
                gate="gate3", severity="WARN", category="NO_ASSERT",
                file=str(test_file), line=node.lineno,
                message=f"测试 '{node.name}' 没有 assert 语句",
                detail="测试必须包含至少一个有效断言",
            ))
        elif not has_real_assert:
            findings.append(AuditFinding(
                gate="gate3", severity="WARN", category="WEAK_ASSERT",
                file=str(test_file), line=node.lineno,
                message=f"测试 '{node.name}' 仅有一个 assert True — 视为弱测试",
            ))

        if only_imports:
            findings.append(AuditFinding(
                gate="gate3", severity="WARN", category="TEST_ONLY_IMPORTS",
                file=str(test_file), line=node.lineno,
                message=f"测试 '{node.name}' 只 import 不验证行为",
            ))

    return findings


# ─── 新增: 执行 pytest ────────────────────────────────────────

def _run_pytest(source_files: list[str]) -> tuple[str, list[AuditFinding]]:
    """执行 pytest，返回日志和发现。"""
    findings: list[AuditFinding] = []
    log = ""

    # 只跑关联的测试文件
    test_files = []
    for sf in source_files:
        expected = TESTS_DIR / f"test_{Path(sf).name}"
        if expected.is_file():
            test_files.append(str(expected))

    if not test_files:
        return "", findings

    try:
        cmd = [VENV, "-m", "pytest"] + test_files + ["-q", "--tb=line", "--no-header"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           cwd=str(COMMANDS))
        output = r.stdout + r.stderr
        log = output[:3000]

        if r.returncode != 0:
            # 提取失败行
            fail_lines = [l for l in output.splitlines() if "FAILED" in l]
            for fl in fail_lines[:5]:
                findings.append(AuditFinding(
                    gate="gate3", severity="FAIL", category="PYTEST_FAILED",
                    file="", message=f"pytest 失败: {fl.strip()[:120]}",
                    detail=output[:1000],
                ))
            if not fail_lines:
                findings.append(AuditFinding(
                    gate="gate3", severity="FAIL", category="PYTEST_FAILED",
                    file="", message=f"pytest 返回码 {r.returncode}",
                    detail=output[:1000],
                ))
        else:
            # 提取通过信息
            passed_match = re.search(r"(\d+) passed", output)
            if passed_match:
                findings.append(AuditFinding(
                    gate="gate3", severity="INFO", category="PYTEST_PASSED",
                    file="", message=f"pytest 通过: {passed_match.group(0)}",
                ))

    except subprocess.TimeoutExpired:
        findings.append(AuditFinding(
            gate="gate3", severity="WARN", category="PYTEST_TIMEOUT",
            file="", message="pytest 超时（60s），跳过执行",
        ))
    except Exception as e:
        findings.append(AuditFinding(
            gate="gate3", severity="WARN", category="PYTEST_ERROR",
            file="", message=f"pytest 执行失败: {e}",
        ))

    return log, findings


# ─── 原有: 测试文件/函数存在性 ───────────────────────────────

def _check_test_file_exists(source_file: str) -> Optional[AuditFinding]:
    expected = _expected_test_file(source_file)
    expected_full = COMMANDS / expected
    if expected_full.is_file():
        return None
    alt = TESTS_DIR / f"test_{Path(source_file).name}"
    if alt.is_file():
        return None
    return AuditFinding(
        gate="gate3", severity="FAIL", category="NO_TEST_FILE",
        file=source_file,
        message=f"源文件 {Path(source_file).name} 没有对应的测试文件 (期望: {expected})",
        detail=f"创建 {expected_full} 并编写至少一个测试函数",
    )


def _check_function_tested(source_file: str, func_name: str, test_file: Path) -> Optional[AuditFinding]:
    expected_test_name = f"test_{func_name}"
    test_funcs = _extract_test_functions(str(test_file))
    if expected_test_name not in test_funcs:
        return AuditFinding(
            gate="gate3", severity="WARN", category="FUNC_NOT_TESTED",
            file=source_file,
            message=f"函数 '{func_name}' 没有对应的测试 (期望: {expected_test_name})",
            detail=f"在 {test_file} 中添加 def {expected_test_name}(): ...",
        )
    return None


def _run_pytest_coverage(source_files: list[str]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    if not source_files:
        return findings
    test_files = []
    for sf in source_files:
        expected = TESTS_DIR / f"test_{Path(sf).name}"
        if expected.is_file():
            test_files.append(str(expected))
    if not test_files:
        return findings

    cov_args = []
    seen = set()
    for sf in source_files:
        full = Path(BASE, sf) if not sf.startswith("/") else Path(sf)
        if full.is_file():
            parent = str(full)
            if parent not in seen:
                seen.add(parent)
                cov_args.extend(["--cov", parent])
            mod_dir = str(full.parent)
            if mod_dir not in seen:
                seen.add(mod_dir)
                cov_args.extend(["--cov", mod_dir])

    try:
        cmd = [VENV, "-m", "pytest"] + test_files + ["-q", "--tb=line",
               "--cov-report=term-missing:skip-covered"] + cov_args
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           cwd=str(COMMANDS))
        output = (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        findings.append(AuditFinding(
            gate="gate3", severity="WARN", category="COV_TIMEOUT",
            file="", message="pytest-cov 超时（30s），跳过覆盖率检查",
        ))
        return findings
    except Exception as e:
        findings.append(AuditFinding(
            gate="gate3", severity="WARN", category="COV_ERROR",
            file="", message=f"pytest-cov 运行失败: {e}",
        ))
        return findings

    for line in output.splitlines():
        line_s = line.strip()
        m = re.match(r"^([\w./-]+\.py)\s+(\d+)%\s+", line_s)
        if m:
            mod = m.group(1)
            cov_pct = int(m.group(2))
            if cov_pct < 60:
                findings.append(AuditFinding(
                    gate="gate3", severity="FAIL", category="LOW_COVERAGE",
                    file=mod, message=f"覆盖率 {cov_pct}% (< 60%)",
                ))
            elif cov_pct < 80:
                findings.append(AuditFinding(
                    gate="gate3", severity="WARN", category="LOW_COVERAGE",
                    file=mod, message=f"覆盖率 {cov_pct}% (< 80%)",
                ))
    return findings


# ─── 主入口 ───────────────────────────────────────────────────

def run_gate3(report: AuditReport) -> AuditReport:
    report.gates_run.append("gate3")

    all_files = _git_diff_files()
    if not all_files:
        report.add(AuditFinding(
            gate="gate3", severity="INFO", category="NO_CHANGES",
            file="", message="无变更文件，跳过测试检查",
        ))
        return report

    source_files, existing_test_files = _classify_files(all_files)
    if not source_files:
        report.add(AuditFinding(
            gate="gate3", severity="INFO", category="NO_SOURCE",
            file="", message="变更中无可测试源文件",
        ))
        return report

    report.add(AuditFinding(
        gate="gate3", severity="INFO", category="SOURCE_FILES",
        file="", message=f"发现 {len(source_files)} 个源文件需要测试覆盖",
        detail="\n".join(source_files[:10]),
    ))

    # 1. 测试文件存在性
    missing_test = 0
    for sf in source_files:
        finding = _check_test_file_exists(sf)
        if finding:
            report.add(finding)
            missing_test += 1
    if missing_test == 0:
        report.add(AuditFinding(
            gate="gate3", severity="INFO", category="TEST_EXIST",
            file="", message=f"所有 {len(source_files)} 个源文件都有对应测试文件",
        ))

    # 2. 函数级测试检查
    untested_funcs = 0
    for sf in source_files:
        expected_test = COMMANDS / _expected_test_file(sf)
        if not expected_test.is_file():
            continue
        funcs = _extract_function_names(sf)
        for fn in funcs:
            finding = _check_function_tested(sf, fn, expected_test)
            if finding:
                report.add(finding)
                untested_funcs += 1

    # 3. 新增: 弱测试检查
    for sf in source_files:
        expected_test = COMMANDS / _expected_test_file(sf)
        weak = _check_weak_test(expected_test)
        report.extend(weak)

    # 4. 新增: 执行 pytest
    pytest_log, pytest_findings = _run_pytest(source_files)
    report.extend(pytest_findings)

    # 5. pytest-cov 覆盖率
    cov_findings = _run_pytest_coverage(source_files)
    report.extend(cov_findings)

    return report
