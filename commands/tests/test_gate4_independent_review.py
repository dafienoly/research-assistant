"""Gate 4 — 独立需求审计 单元测试"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestBuildAuditPrompt:
    def test_build_audit_prompt_returns_string(self):
        from factor_lab.audit.gate4_independent_review import build_audit_prompt
        prompt = build_audit_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_prompt_contains_key_sections(self):
        from factor_lab.audit.gate4_independent_review import build_audit_prompt
        prompt = build_audit_prompt()
        assert "IMPLEMENTED" in prompt
        assert "MOCK_DATA" in prompt
        assert "STUB" in prompt
        assert "MISSING" in prompt

    def test_prompt_contains_verdict_format(self):
        from factor_lab.audit.gate4_independent_review import build_audit_prompt
        prompt = build_audit_prompt()
        assert '"verdicts"' in prompt or "'verdicts'" in prompt
        assert '"summary"' in prompt or "'summary'" in prompt


class TestRuleBasedAnalysis:
    def test_no_diff(self):
        from factor_lab.audit.gate4_independent_review import _rule_based_analysis
        findings = _rule_based_analysis("", [], "")
        assert len(findings) >= 1
        cats = {f.category for f in findings}
        assert "RULE_NO_DIFF" in cats or "RULE_NO_PY" in cats

    def test_todo_detection(self):
        from factor_lab.audit.gate4_independent_review import _rule_based_analysis
        diff = """\
+def foo():
+    return 1  # TODO: implement properly
+def bar():
+    pass  # FIXME: not done
"""
        findings = _rule_based_analysis(diff, ["test.py"], "")
        cats = {f.category for f in findings}
        assert "RULE_TODO_LEFT" in cats

    def test_empty_function_detection(self):
        from factor_lab.audit.gate4_independent_review import _rule_based_analysis
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write("""\
def compute():
    pass

def real():
    return 42
""")
        f.close()
        findings = _rule_based_analysis("", [f.name], "")
        os.unlink(f.name)
        cats = {f.category for f in findings}
        assert "RULE_EMPTY_FUNCTIONS" in cats

    def test_no_substance_detection(self):
        from factor_lab.audit.gate4_independent_review import _rule_based_analysis
        diff = """\
+import os
+import sys
+from pathlib import Path
+
+ # comment
"""
        findings = _rule_based_analysis(diff, ["test.py"], "")
        cats = {f.category for f in findings}
        assert "RULE_NO_SUBSTANCE" in cats


class TestRunGate4:
    def test_run_gate4_no_crash(self):
        from factor_lab.audit.base import AuditReport
        from factor_lab.audit.gate4_independent_review import run_gate4
        r = AuditReport(version="test")
        run_gate4(r)
        assert len(r.findings) >= 1
