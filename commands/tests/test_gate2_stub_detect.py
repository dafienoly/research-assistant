"""Gate 2 — 虚假实现检测 单元测试"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


STUB_PASS = """\
def compute_score(data):
    pass
"""

STUB_ELLIPSIS = """\
def fetch_data(url):
    ...
"""

STUB_RETURN_NONE = """\
def calculate_alpha(df):
    return None
"""

STUB_RETURN_LITERAL = """\
def get_prediction(features):
    return 0.85
"""

STUB_RETURN_LIST = """\
def get_ranks(items):
    return [1, 2, 3]
"""

STUB_RETURN_DICT = """\
def compute_metrics(data):
    return {"sharpe": 1.5, "vol": 0.2}
"""

REAL_FUNCTION = """\
def compute_alpha(df):
    mean = df["ret"].mean()
    std = df["ret"].std()
    return mean / std if std != 0 else 0
"""

DOCSTRING_ONLY = """\
def process(data):
    '''Placeholder for future use.'''
"""


class TestStubDetector:
    def make_file(self, code, suffix=".py"):
        f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
        f.write(code)
        f.close()
        return f.name

    def test_detect_pass(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = "def compute_score(data): pass"
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        fail = [f for f in d.findings if f.severity == "FAIL" and "STUB_PASS" in f.category]
        assert len(fail) >= 1, f"应检测到 pass stub, 但找到: {[str(f) for f in d.findings]}"

    def test_detect_ellipsis(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = "def fetch_data(url): ..."
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        fail = [f for f in d.findings if f.severity == "FAIL" and "STUB_ELLIPSIS" in f.category]
        assert len(fail) >= 1

    def test_detect_return_literal(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = "def predict(x): return 0.85"
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        warn = [f for f in d.findings if "STUB_RETURN_LITERAL" in f.category]
        assert len(warn) >= 1

    def test_detect_return_list(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = "def rank(items): return [1, 2, 3]"
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        warn = [f for f in d.findings if "STUB_RETURN_LIST" in f.category]
        assert len(warn) >= 1

    def test_detect_return_dict(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = "def metrics(d): return {'a': 1}"
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        warn = [f for f in d.findings if "STUB_RETURN_DICT" in f.category]
        assert len(warn) >= 1

    def test_real_function_not_flagged(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = """\
def compute_alpha(df):
    mean = df["ret"].mean()
    std = df["ret"].std()
    return mean / std if std != 0 else 0
"""
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        fails = [f for f in d.findings if f.severity == "FAIL"]
        assert len(fails) == 0, f"真实函数不应有 FAIL: {[str(f) for f in fails]}"

    def test_class_method_detection(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = """\
class Calculator:
    def compute(self, x):
        pass
"""
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        fail = [f for f in d.findings if f.severity == "FAIL"]
        assert len(fail) >= 1

    def test_visitor_method_ignored(self):
        from factor_lab.audit.gate2_stub_detect import StubDetector
        import ast
        code = """\
class MyVisitor(ast.NodeVisitor):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
"""
        tree = ast.parse(code)
        d = StubDetector("test.py")
        d.visit(tree)
        # visit_* 方法是设计上短方法，不应被标记为 stub
        too_simple = [f for f in d.findings if "STUB_TOO_SIMPLE" in f.category]
        assert len(too_simple) == 0, f"visitor 方法不应标记为 too_simple: {[str(f) for f in too_simple]}"


class TestRunGate2:
    def test_run_gate2_no_crash(self):
        from factor_lab.audit.base import AuditReport
        from factor_lab.audit.gate2_stub_detect import run_gate2
        r = AuditReport(version="test")
        run_gate2(r)
        assert len(r.findings) >= 1
