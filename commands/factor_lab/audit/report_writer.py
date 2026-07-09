"""
Report Writer — 增强审计报告输出

每次审计输出:
  1. Markdown 报告 (*.md)
  2. JSON 报告 (*.json)
  3. findings JSONL (*.jsonl)
  4. audit manifest (*.manifest.json)
  5. gate summary
  6. runtime smoke log
  7. pytest log

输出目录: /mnt/d/HermesReports/code_audit/YYYYMMDD/<run_id>/
本地备份: agent_tasks/audit_reports/
"""

from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .base import AuditReport, AuditFinding

CST = timezone(timedelta(hours=8))
OUTPUT_BASE = Path("/mnt/d/HermesReports/code_audit")
LOCAL_FALLBACK = Path.home() / ".hermes" / "research-assistant" / "agent_tasks" / "audit_reports"


def _ensure_dir(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run_id() -> str:
    return datetime.now(CST).strftime("%Y%m%d_%H%M%S")


def _day_dir() -> Path:
    return OUTPUT_BASE / datetime.now(CST).strftime("%Y%m%d")


def write_report(report: AuditReport,
                  extra: Optional[dict] = None,
                  output_dir: Optional[str] = None,
                  runtime_log: str = "",
                  pytest_log: str = "") -> dict[str, str]:
    """输出完整审计产物。

    Returns:
        {format: path} 字典
    """
    rid = _run_id()
    extra = extra or {}

    # 输出目录
    if output_dir:
        base = Path(output_dir)
    else:
        base = _day_dir() / rid
    _ensure_dir(base)

    # 本地备份
    local = _ensure_dir(LOCAL_FALLBACK)

    paths: dict[str, str] = {}

    # 1. JSON 报告
    report_dict = report.to_dict()
    report_dict["extra"] = extra
    report_dict["risk"] = extra.get("risk", "UNKNOWN")
    report_dict["run_id"] = rid
    for p, label in [(base / "audit_report.json", "json_report"),
                      (local / f"audit_{rid}.json", "json_backup")]:
        p.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False))
        paths[label] = str(p)

    # 2. Markdown 报告
    md = _format_markdown(report, extra, rid, runtime_log, pytest_log)
    for p, label in [(base / "audit_report.md", "md_report"),
                      (local / f"audit_{rid}.md", "md_backup")]:
        p.write_text(md, encoding="utf-8")
        paths[label] = str(p)

    # 3. Findings JSONL
    jsonl_lines = []
    for f in report.findings:
        jsonl_lines.append(json.dumps({
            "gate": f.gate, "severity": f.severity, "category": f.category,
            "file": f.file, "line": f.line, "message": f.message,
            "detail": f.detail, "run_id": rid,
        }, ensure_ascii=False))
    jsonl_path = base / "findings.jsonl"
    jsonl_path.write_text("\n".join(jsonl_lines) + "\n", encoding="utf-8")
    paths["jsonl"] = str(jsonl_path)

    # 4. Manifest
    manifest = {
        "run_id": rid,
        "timestamp": datetime.now(CST).isoformat(),
        "version": report.version,
        "passed": report.passed,
        "gates_run": report.gates_run,
        "total_findings": len(report.findings),
        "fail_count": len(report.fails),
        "warn_count": len(report.warns),
        "risk": extra.get("risk", "UNKNOWN"),
        "skip_info": extra.get("skip_info", []),
        "artifacts": {
            "report_json": str(base / "audit_report.json"),
            "report_md": str(base / "audit_report.md"),
            "findings_jsonl": str(jsonl_path),
            "runtime_log": str(base / "runtime_smoke.log") if runtime_log else "",
            "pytest_log": str(base / "pytest.log") if pytest_log else "",
        },
    }
    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    paths["manifest"] = str(manifest_path)

    # 5. Runtime / pytest logs
    if runtime_log:
        (base / "runtime_smoke.log").write_text(runtime_log)
    if pytest_log:
        (base / "pytest.log").write_text(pytest_log)

    # 6. 更新 latest 指针
    latest = local / "audit_latest.json"
    latest.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False))

    return paths


def _format_markdown(report: AuditReport, extra: dict, rid: str,
                     runtime_log: str, pytest_log: str) -> str:
    """生成 Markdown 审计报告。"""
    lines: list[str] = []
    lines.append(f"# Code Audit Report — {rid}")
    lines.append(f"")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Status | {'✅ PASS' if report.passed else '❌ FAIL'} |")
    lines.append(f"| Version | {report.version or '(unversioned)'} |")
    lines.append(f"| Risk | {extra.get('risk', 'UNKNOWN')} |")
    lines.append(f"| Gates | {', '.join(report.gates_run) or '(none)'} |")
    lines.append(f"| Findings | {len(report.findings)} |")
    lines.append(f"| Time | {report.started_at} → {report.finished_at} |")
    lines.append(f"")

    # 统计
    gates = report.summary_counts()
    lines.append(f"## Gate Summary")
    lines.append(f"")
    lines.append(f"| Gate | FAIL | WARN | INFO |")
    lines.append(f"|------|:----:|:----:|:----:|")
    for g in report.gates_run:
        gs = gates.get(g, {})
        lines.append(f"| {g} | {gs.get('fail', 0)} | {gs.get('warn', 0)} | {gs.get('pass', 0)} |")
    lines.append(f"")

    # 按 severity 分组
    if report.fails:
        lines.append(f"## ❌ FAIL Items")
        lines.append(f"")
        for f in report.fails:
            lines.append(f"- **{f.gate}/{f.category}** `{f.file}:{f.line}` — {f.message}")
            if f.detail:
                lines.append(f"  ```")
                lines.append(f"  {f.detail[:200]}")
                lines.append(f"  ```")
        lines.append(f"")

    if report.warns:
        lines.append(f"## ⚠️ WARN Items")
        lines.append(f"")
        for f in report.warns:
            lines.append(f"- **{f.gate}/{f.category}** `{f.file}:{f.line}` — {f.message}")
        lines.append(f"")

    # Skip 记录
    skip_info = extra.get("skip_info", [])
    if skip_info:
        lines.append(f"## ⏭️ Skipped Gates")
        lines.append(f"")
        for s in skip_info:
            lines.append(f"- `{s.get('gate')}` — {s.get('reason', '(无原因)')}")
        lines.append(f"")

    # Runtime / pytest logs
    if runtime_log:
        lines.append(f"## 🏃 Runtime Smoke Log")
        lines.append(f"```")
        lines.append(f"{runtime_log[:2000]}")
        lines.append(f"```")
        lines.append(f"")
    if pytest_log:
        lines.append(f"## 🧪 pytest Log")
        lines.append(f"```")
        lines.append(f"{pytest_log[:2000]}")
        lines.append(f"```")
        lines.append(f"")

    # Artifacts
    lines.append(f"## 📁 Artifacts")
    lines.append(f"")
    lines.append(f"Output: `{_day_dir() / rid}`")
    lines.append(f"")

    return "\n".join(lines)
