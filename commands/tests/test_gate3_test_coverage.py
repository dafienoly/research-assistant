"""Gate 3 — 测试覆盖检查 单元测试"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestClassifyFiles:
    def test_classify_source(self):
        from factor_lab.audit.gate3_test_coverage import _classify_files
        src, test = _classify_files(["commands/foo.py", "commands/bar.py"])
        assert src == ["commands/foo.py", "commands/bar.py"]
        assert test == []

    def test_classify_test(self):
        from factor_lab.audit.gate3_test_coverage import _classify_files
        src, test = _classify_files(["tests/test_foo.py", "commands/foo.py"])
        assert src == ["commands/foo.py"]
        assert test == ["tests/test_foo.py"]

    def test_classify_non_code(self):
        from factor_lab.audit.gate3_test_coverage import _classify_files
        src, test = _classify_files(["docs/readme.md", "config.yaml", "commands/foo.py"])
        assert src == ["commands/foo.py"]
        assert test == ["docs/readme.md", "config.yaml"]


class TestExpectedTestFile:
    def test_basic(self):
        from factor_lab.audit.gate3_test_coverage import _expected_test_file
        expected = _expected_test_file("commands/foo.py")
        assert expected == "tests/test_foo.py"

    def test_subdir(self):
        from factor_lab.audit.gate3_test_coverage import _expected_test_file
        expected = _expected_test_file("commands/factor_lab/audit/bar.py")
        assert expected == "tests/test_bar.py"


class TestExtractFunctions:
    def test_extract_source(self):
        from factor_lab.audit.gate3_test_coverage import _extract_function_names
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write("""\
def compute_alpha(df):
    return 1

class Helper:
    def run(self):
        pass
""")
        f.close()
        funcs = _extract_function_names(f.name)
        os.unlink(f.name)
        assert "compute_alpha" in funcs
        assert "run" in funcs

    def test_skip_private(self):
        from factor_lab.audit.gate3_test_coverage import _extract_function_names
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write("""\
def _helper():
    pass

def public_func():
    pass
""")
        f.close()
        funcs = _extract_function_names(f.name)
        os.unlink(f.name)
        assert "_helper" not in funcs
        assert "public_func" in funcs

    def test_skip_test_functions(self):
        from factor_lab.audit.gate3_test_coverage import _extract_function_names
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write("""\
def test_something():
    pass

def real_func():
    pass
""")
        f.close()
        funcs = _extract_function_names(f.name)
        os.unlink(f.name)
        assert "test_something" not in funcs
        assert "real_func" in funcs


class TestExtractTestFunctions:
    def test_extract_test_funcs(self):
        from factor_lab.audit.gate3_test_coverage import _extract_test_functions
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write("""\
def test_compute():
    pass

def helper():
    pass
""")
        f.close()
        funcs = _extract_test_functions(f.name)
        os.unlink(f.name)
        assert "test_compute" in funcs
        assert "helper" not in funcs


class TestRunGate3:
    def test_run_gate3_no_crash(self):
        from factor_lab.audit.base import AuditReport
        from factor_lab.audit.gate3_test_coverage import run_gate3
        r = AuditReport(version="test")
        run_gate3(r)
        assert len(r.findings) >= 1
