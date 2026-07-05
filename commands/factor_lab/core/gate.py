"""Core Gate V2.14.2 — 统一 GateEngine"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GateCheck:
    name: str
    passed: bool = True
    severity: str = "warning"  # blocker/warning/info
    message: str = ""
    evidence: str = ""


@dataclass
class GateResult:
    gate_name: str
    checks: list = field(default_factory=list)
    verdict: str = "pass"  # pass / conditional_pass / fail / insufficient_evidence

    @property
    def blockers(self):
        return [c for c in self.checks if c.severity == "blocker" and not c.passed]

    @property
    def warnings(self):
        return [c for c in self.checks if c.severity == "warning" and not c.passed]

    @property
    def passed(self):
        return len(self.blockers) == 0


class GateEngine:
    """统一门禁引擎"""
    def __init__(self):
        self.results = []

    def add_check(self, gate: str, name: str, passed: bool, severity: str = "warning",
                  message: str = "", evidence: str = ""):
        result = self._find_or_create(gate)
        result.checks.append(GateCheck(name=name, passed=passed, severity=severity,
                                       message=message, evidence=evidence))

    def _find_or_create(self, gate: str) -> GateResult:
        for r in self.results:
            if r.gate_name == gate:
                return r
        gr = GateResult(gate_name=gate)
        self.results.append(gr)
        return gr

    def finalize(self):
        for r in self.results:
            blockers = r.blockers
            if blockers:
                r.verdict = "fail"
            elif r.warnings:
                r.verdict = "conditional_pass"
            else:
                r.verdict = "pass"

    def get_summary(self) -> dict:
        self.finalize()
        return {r.gate_name: {"verdict": r.verdict, "n_blockers": len(r.blockers),
                               "n_warnings": len(r.warnings)} for r in self.results}
