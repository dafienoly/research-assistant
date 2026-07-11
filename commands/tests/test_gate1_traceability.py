"""Gate 1 — 需求→代码追溯 单元测试"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ─── Plan 解析测试 ───────────────────────────────────────────────

class TestPlanParsing:
    def test_parse_empty(self):
        from factor_lab.audit.gate1_traceability import _parse_plan_md
        tasks = _parse_plan_md("# No tasks here")
        assert tasks == []

    def test_parse_single_task(self):
        from factor_lab.audit.gate1_traceability import _parse_plan_md
        md = """
### Task 1: Create ranking module

- **Create:** `commands/ranking.py`
- **Modify:** `commands/runner.py`

Implement the ranking function.
"""
        tasks = _parse_plan_md(md)
        assert len(tasks) == 1
        assert "ranking" in tasks[0].title
        assert "commands/ranking.py" in tasks[0].expected_creates
        assert "commands/runner.py" in tasks[0].expected_modifies

    def test_parse_multi_task(self):
        from factor_lab.audit.gate1_traceability import _parse_plan_md
        md = """
### Task 2: Add tests
- **Create:** `tests/test_ranking.py`

### Task 3: Wire API
- **Modify:** `api/main.py`
"""
        tasks = _parse_plan_md(md)
        assert len(tasks) == 2
        assert tasks[0].expected_creates == ["tests/test_ranking.py"]
        assert tasks[1].expected_modifies == ["api/main.py"]


# ─── 文件存在检查 ───────────────────────────────────────────────

class TestCheckFilesExist:
    def test_existing_file(self):
        from factor_lab.audit.gate1_traceability import _check_files_exist
        findings = _check_files_exist(["tests/test_git_utils.py"])
        fails = [f for f in findings if f.severity == "FAIL"]
        assert len(fails) == 0, f"test_git_utils.py 应该存在，但返回了 FAIL: {fails}"

    def test_missing_file(self):
        from factor_lab.audit.gate1_traceability import _check_files_exist
        findings = _check_files_exist(["path/to/nonexistent_file_xyz.py"])
        fails = [f for f in findings if f.severity == "FAIL"]
        assert len(fails) >= 1

    def test_mixed(self):
        from factor_lab.audit.gate1_traceability import _check_files_exist
        findings = _check_files_exist([
            "tests/test_git_utils.py",
            "tests/test_nonexistent_xyz.py",
        ])
        fails = [f for f in findings if f.severity == "FAIL"]
        passes = [f for f in findings if f.severity == "INFO"]
        assert len(fails) >= 1
        assert len(passes) >= 1


# ─── 函数提取 ───────────────────────────────────────────────────

class TestExtractFunctions:
    def test_extract_from_code(self):
        from factor_lab.audit.gate1_traceability import _extract_functions_from_code
        # __file__ is this test file — it has module-level classes, not module-level defs
        funcs = _extract_functions_from_code(__file__)
        assert len(funcs) > 0
        # 应包含类名（module-level 的对象）
        assert any("Test" in f for f in funcs)

    def test_extract_includes_classes(self):
        from factor_lab.audit.gate1_traceability import _extract_functions_from_code
        funcs = _extract_functions_from_code(__file__)
        assert "TestPlanParsing" in funcs


# ─── run_gate1 集成 ─────────────────────────────────────────────

class TestRunGate1:
    def test_no_plan_fallback(self):
        from factor_lab.audit.base import AuditReport
        from factor_lab.audit.gate1_traceability import run_gate1
        r = AuditReport(version="test")
        run_gate1(r)
        # 不应崩溃
        assert len(r.findings) >= 1
        # 应该有 NO_TASKS 或 NO_PLAN 或 CHANGED_FILES
        categories = {f.category for f in r.findings}
        assert categories & {"NO_TASKS", "NO_PLAN", "CHANGED_FILES", "GIT_DIFF"}

    def test_plan_with_multiple_expected_files_does_not_hash_nested_lists(self, tmp_path):
        from factor_lab.audit.base import AuditReport
        from factor_lab.audit.gate1_traceability import run_gate1

        plan = tmp_path / "plan.md"
        plan.write_text(
            "### Task 1: Files\n"
            "- **Create:** `commands/a.py`, `commands/b.py`\n"
            "- **Modify:** `commands/c.py`\n",
            encoding="utf-8",
        )
        report = AuditReport(version="test")
        run_gate1(report, plan_path=str(plan))
        assert any(f.category == "PLAN_FOUND" for f in report.findings)
