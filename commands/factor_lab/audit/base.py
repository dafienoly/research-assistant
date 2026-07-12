"""Anti-Cheat Audit — 基础数据结构"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import hashlib
from typing import Literal, Any

CST = timezone(timedelta(hours=8))
Severity = Literal["FAIL", "WARN", "INFO"]


@dataclass
class AuditFinding:
    """一条审计发现"""
    gate: str                     # "gate1" | "gate2" | "gate3" | "gate4"
    severity: Severity            # FAIL / WARN / INFO
    category: str                 # 分类: "MISSING_FILE" | "STUB_FUNC" | "NO_TEST" | ...
    file: str                     # 关联文件路径
    line: int = 0                 # 行号（0 = 不适用）
    message: str = ""             # 简短描述
    detail: str = ""              # 详细证据
    rule_id: str = ""
    confidence: str = "high"
    blocking: bool | None = None
    fingerprint: str = ""

    def __post_init__(self):
        if not self.rule_id:
            self.rule_id = f"{self.gate}.{self.category}".lower()
        if self.blocking is None:
            self.blocking = self.severity == "FAIL"
        if not self.fingerprint:
            raw = "|".join((self.rule_id, self.file, str(self.line), self.message))
            self.fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def __str__(self) -> str:
        tag = {"FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(self.severity, "❓")
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{tag} [{self.gate}/{self.category}] {loc} — {self.message}"


@dataclass
class AuditReport:
    """完整审计报告"""
    version: str = ""
    passed: bool = True
    findings: list[AuditFinding] = field(default_factory=list)
    gates_run: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    extras: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    profile: str = "full"
    scope: str = "working-tree"
    state: str = "running"
    change_set_hash: str = ""
    durations: dict[str, float] = field(default_factory=dict)
    trigger: str = "manual"
    requested_by: str = "local"

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(CST).isoformat()
        if not self.finished_at:
            self.finished_at = self.started_at

    @property
    def fails(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.severity == "FAIL"]

    @property
    def warns(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.severity == "WARN"]

    @property
    def infos(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.severity == "INFO"]

    def add(self, finding: AuditFinding):
        self.findings.append(finding)
        if finding.severity == "FAIL" and finding.blocking:
            self.passed = False

    def extend(self, findings: list[AuditFinding]):
        for f in findings:
            self.add(f)

    def summary_counts(self) -> dict[str, dict[str, int]]:
        """Return explicit info/fail/warn counts; INFO is never called pass."""
        gates: dict[str, dict[str, int]] = {}
        for f in self.findings:
            g = gates.setdefault(f.gate, {"pass": 0, "info": 0, "fail": 0, "warn": 0})
            if f.severity == "FAIL":
                g["fail"] += 1
            elif f.severity == "WARN":
                g["warn"] += 1
            else:
                g["info"] += 1
        return gates

    def summary_text(self) -> str:
        status = "⏭️ SKIPPED" if self.state == "skipped" else ("✅ PASS" if self.passed else "❌ FAIL")
        lines = [
            "═══ Code Audit Report ═══",
            f"Version: {self.version or '(unversioned)'}",
            f"Status:  {status}",
            f"Gates:   {', '.join(self.gates_run) or '(none)'}",
            "",
        ]
        gates = self.summary_counts()
        grand_info = sum(g["info"] for g in gates.values())
        grand_fail = sum(g["fail"] for g in gates.values())
        grand_warn = sum(g["warn"] for g in gates.values())
        lines.append(f"Total:   {grand_fail} fail | {grand_warn} warn | {grand_info} info")
        lines.append("")

        for gname in self.gates_run:
            g = gates.get(gname, {"pass": 0, "info": 0, "fail": 0, "warn": 0})
            label = {
                "gate1": "Gate 1 — 需求→代码追溯",
                "gate2": "Gate 2 — 虚假实现检测",
                "gate3": "Gate 3 — 测试覆盖检查",
                "gate4": "Gate 4 — 独立需求审计",
            }.get(gname, gname)
            lines.append(f"  {label}: {g['fail']} fail | {g['warn']} warn | {g['info']} info")

        if self.fails:
            lines.append("\n❌ FAIL Items:")
            for f in self.fails:
                lines.append(f"  {f}")
        if self.warns:
            lines.append("\n⚠️ WARN Items:")
            for f in self.warns:
                lines.append(f"  {f}")

        lines.append(f"\nFinished: {self.finished_at}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "profile": self.profile,
            "scope": self.scope,
            "state": self.state,
            "change_set_hash": self.change_set_hash,
            "version": self.version,
            "passed": self.passed,
            "gates_run": self.gates_run,
            "findings": [
                {"gate": f.gate, "severity": f.severity, "category": f.category,
                 "file": f.file, "line": f.line, "message": f.message,
                 "detail": f.detail, "rule_id": f.rule_id,
                 "confidence": f.confidence, "blocking": f.blocking,
                 "fingerprint": f.fingerprint}
                for f in self.findings
            ],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "durations": self.durations,
            "trigger": self.trigger,
            "requested_by": self.requested_by,
            "extras": self.extras,
        }
