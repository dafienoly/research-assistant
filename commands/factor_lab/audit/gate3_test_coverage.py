"""Gate 3 — 测试覆盖检查

检测目标:
  1. 新代码（非测试文件）→ 检查对应测试文件是否存在
  2. 新函数 → 检查对应测试函数是否存在
  3. pytest-cov 覆盖率检查: 新代码覆盖不足 = 没写测试
  4. 排除 __init__.py / 配置 / 文档等不需要测试的文件

依赖: pytest-cov (pip install pytest-cov)
"""

from __future__ import annotations
import ast
import os
import subprocess
import re
from pathlib import Path
from typing import Optional

from .base import AuditFinding, AuditReport, Severity

BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT",
                           "/home/ly/.hermes/research-assistant"))
COMMANDS = BASE / "commands"
VENV = str(BASE / ".venv_quant" / "bin" / "python3")
TESTS_DIR = COMMANDS / "tests"

# 不需要测试的文件
NO_TEST_EXTENSIONS = {".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
NO_TEST_FILES = {"__init__.py", "conftest.py", "setup.py", "conf.py"}


# ─── Git 辅助 ───────────────────────────────────────────────────

def _git_diff_files() -> list[str]:
    files: set[str] = set()
    for cmd in [["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass
    if not files:
        try:
            r = subprocess.run(["git", "diff", "--name-only", "HEAD~3", "HEAD"],
                               capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass
    return sorted(f for f in files if f.strip())


# ─── Test 文件映射 ──────────────────────────────────────────────

def _classify_files(files: list[str]) -> tuple[list[str], list[str]]:
    """分离测试文件和非测试文件"""
    test_files = []
    source_files = []
    for f in files:
        f_lower = f.lower()
        ext = Path(f).suffix.lower()
        if "/test_" in f_lower or f_lower.startswith("test_") or ext in NO_TEST_EXTENSIONS:
            test_files.append(f)
        elif Path(f).name in NO_TEST_FILES:
            continue  # 忽略
        elif f.endswith(".py"):
            source_files.append(f)
    return source_files, test_files


def _expected_test_file(source: str) -> str:
    """给定源文件路径，推断对应的测试文件路径"""
    # 规则: src/module.py → tests/test_module.py
    #        commands/factor_lab/foo.py → commands/tests/test_foo.py
    name = Path(source).stem
    return f"tests/test_{name}.py"


def _extract_function_names(file_path: str) -> list[str]:
    """从 Python 源文件中提取非测试、非特殊函数名"""
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
            # 跳过私有/魔术方法
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
    """从测试文件中提取 test_ 函数名"""
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


# ─── 核心检测 ───────────────────────────────────────────────────

def _check_test_file_exists(source_file: str) -> Optional[AuditFinding]:
    """检查源文件是否有对应的测试文件"""
    expected = _expected_test_file(source_file)
    expected_full = COMMANDS / expected
    if expected_full.is_file():
        return None  # 测试文件存在
    # 也检查 tests 目录下是否有带子路径的测试文件
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
    """检查源文件的函数是否有对应的测试"""
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
    """使用 pytest-cov 检查新代码的测试覆盖（只跑关联测试文件，30s 超时）"""
    findings: list[AuditFinding] = []
    if not source_files:
        return findings

    # 只跑关联的测试文件
    test_files = []
    for sf in source_files:
        expected = TESTS_DIR / f"test_{Path(sf).name}"
        if expected.is_file():
            test_files.append(str(expected))

    if not test_files:
        return findings

    # 构建 --cov 参数（源文件目录）
    cov_args = []
    seen = set()
    for sf in source_files:
        full = Path(BASE, sf) if not sf.startswith("/") else Path(sf)
        if full.is_file():
            parent = str(full)
            if parent not in seen:
                seen.add(parent)
                cov_args.extend(["--cov", parent])
            # also add module dir
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

    # 解析覆盖率输出
    for line in output.splitlines():
        line_s = line.strip()
        # 匹配 "src/module.py   85%  12 lines" 等
        m = re.match(r"^([\w./-]+\.py)\s+(\d+)%\s+", line_s)
        if m:
            mod = m.group(1)
            cov_pct = int(m.group(2))
            if cov_pct < 60:
                findings.append(AuditFinding(
                    gate="gate3", severity="FAIL", category="LOW_COVERAGE",
                    file=mod, message=f"覆盖率 {cov_pct}% (< 60%)",
                    detail=f"新代码测试覆盖不足，请在 tests/ 中添加对应测试",
                ))
            elif cov_pct < 80:
                findings.append(AuditFinding(
                    gate="gate3", severity="WARN", category="LOW_COVERAGE",
                    file=mod, message=f"覆盖率 {cov_pct}% (< 80%)",
                ))

    return findings


# ─── 主入口 ─────────────────────────────────────────────────────

def run_gate3(report: AuditReport) -> AuditReport:
    """执行 Gate 3: 测试覆盖检查"""
    report.gates_run.append("gate3")

    # 1. 获取变更文件
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
            file="", message="变更中无可测试源文件（仅测试/文档/配置变更）",
        ))
        return report

    report.add(AuditFinding(
        gate="gate3", severity="INFO", category="SOURCE_FILES",
        file="", message=f"发现 {len(source_files)} 个源文件需要测试覆盖",
        detail="\n".join(source_files[:10]),
    ))

    # 2. 测试文件存在性检查
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

    # 3. 函数级测试检查
    untested_funcs = 0
    for sf in source_files:
        expected_test = COMMANDS / _expected_test_file(sf)
        if not expected_test.is_file():
            continue  # 已在缺失文件步骤中报告
        funcs = _extract_function_names(sf)
        for fn in funcs:
            finding = _check_function_tested(sf, fn, expected_test)
            if finding:
                report.add(finding)
                untested_funcs += 1

    if untested_funcs == 0 and missing_test == 0:
        report.add(AuditFinding(
            gate="gate3", severity="INFO", category="FUNCTIONS_TESTED",
            file="", message="所有新函数都有对应的测试",
        ))

    # 4. pytest-cov 覆盖率检查
    cov_findings = _run_pytest_coverage(source_files)
    report.extend(cov_findings)

    return report
