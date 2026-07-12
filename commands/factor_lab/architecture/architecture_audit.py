"""Release-only, source-only architecture inventory.

The former implementation recursively scanned ``/mnt/d/HermesReports`` and
treated generated artifacts as architecture evidence. That path is retired.
This module now does nothing unless a caller supplies an explicit major
version, and even then it reads only bounded source trees under the project.
Data, artifacts, caches, temporary files and GitNexus are never inspected.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factor_lab.audit.source_audit import EXCLUDED_PARTS, iter_source_files

CST = timezone(timedelta(hours=8))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC = PROJECT_ROOT / "commands"


def _disabled(major_version: str) -> dict:
    payload = {
        "status": "SKIPPED",
        "reason": "架构审计仅在显式大版本发布前执行",
        "major_version": major_version,
        "scan_policy": {
            "source_only": True,
            "data_scan": False,
            "temp_scan": False,
            "artifact_scan": False,
            "gitnexus": False,
        },
    }
    print("Architecture audit skipped: provide --major-version for release-only source audit.")
    return payload


def run_architecture_audit(
    output_dir=None,
    strict=False,
    include_tests=False,
    include_artifacts=False,
    major_version: str = "",
):
    """Run a bounded source inventory only for an explicit major version."""
    del strict, include_artifacts  # retained for compatibility; artifact scan is retired
    if not major_version:
        return _disabled(major_version)

    run_id = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    default_root = Path.home() / ".hermes/state/research-assistant/major-audits"
    out_dir = Path(output_dir or default_root / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_files = list(iter_source_files(PROJECT_ROOT, include_tests=include_tests))
    relative_sources = [path.relative_to(PROJECT_ROOT).as_posix() for path in source_files]

    modules = _scan_modules(relative_sources)
    cli_cmds = _scan_cli()
    gates = _scan_gates(source_files)
    configs = _scan_configs()
    safety = _check_safety_boundary(source_files)
    tests = _scan_tests(relative_sources)
    artifacts = [{
        "directory": "<disabled>",
        "html": 0,
        "csv": 0,
        "json": 0,
        "md": 0,
        "log": 0,
        "scan_status": "disabled",
        "reason": "generated artifacts and data trees are outside code-audit scope",
    }]
    audit_logs = [{
        "path": "<disabled>",
        "size": 0,
        "has_safety_flags": 0,
        "snippet": "audit log content is not scanned by release source audit",
    }]
    dups = _find_duplications()
    scores = {
        "maintainability": _score_maintainability(modules, cli_cmds, dups),
        "safety": _score_safety(safety),
        "extensibility": 8,
        "test_quality": _score_tests(tests),
        "v3_readiness": _score_v3_readiness(modules),
    }
    findings = [
        _finding("P1", "Gate 逻辑重复", "风险/执行/数据门禁仍有重复实现", "后续按领域提取统一 GateEngine"),
        _finding("P2", "CLI 参数语义不完全一致", "部分历史命令参数仍待统一", "逐步迁移至 CommandRegistry"),
        _finding("P2", "报告模板重复", "研究报告仍有多套模板", "后续提取统一 ReportBuilder"),
    ]
    overall = round(sum(scores.values()) / len(scores), 1)
    payload = {
        "run_id": run_id,
        "status": "PASS" if not safety else "REVIEW",
        "major_version": major_version,
        "overall_score": overall,
        "scores": scores,
        "findings": findings,
        "source_files": len(source_files),
        "scan_policy": {
            "source_only": True,
            "data_scan": False,
            "temp_scan": False,
            "artifact_scan": False,
            "gitnexus": False,
            "excluded_parts": sorted(EXCLUDED_PARTS),
        },
    }
    _write_csv(out_dir / "module_map.csv", modules)
    _write_csv(out_dir / "cli_command_inventory.csv", cli_cmds, ["command", "handler"])
    _write_csv(out_dir / "artifact_inventory.csv", artifacts)
    _write_csv(out_dir / "audit_log_inventory.csv", audit_logs)
    _write_csv(out_dir / "gate_inventory.csv", gates, ["file", "gates", "lines"])
    _write_csv(out_dir / "config_inventory.csv", configs, ["config", "path"])
    _write_csv(out_dir / "safety_boundary_report.csv", safety, ["file", "term", "context"])
    _write_csv(out_dir / "test_coverage_inventory.csv", tests)
    _write_csv(out_dir / "duplication_findings.csv", dups)
    (out_dir / "architecture_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "architecture_audit_summary.md").write_text(
        f"# Source-only Architecture Audit\n\nMajor version: **{major_version}**\n\n"
        f"Status: **{payload['status']}**\n\nScanned source files: **{len(source_files)}**\n\n"
        "Data/artifact/temp scan: **disabled**\n",
        encoding="utf-8",
    )
    (out_dir / "refactor_recommendations.md").write_text(
        "# 后续重构建议\n\n" + "\n".join(
            f"- [{item['severity']}] {item['title']}: {item['suggestion']}" for item in findings
        ) + "\n",
        encoding="utf-8",
    )
    (out_dir / "v3_alpha_factory_readiness.md").write_text(
        f"# V3 Alpha Factory Readiness\n\nStatus: **source-only/{payload['status']}**\n",
        encoding="utf-8",
    )
    (out_dir / "architecture_audit.log").write_text(
        f"SOURCE_ONLY_AUDIT\nrun_id={run_id}\nmajor_version={major_version}\n"
        f"source_files={len(source_files)}\ndata_scan=False\ntemp_scan=False\n",
        encoding="utf-8",
    )
    print(f"Source-only architecture audit: {payload['status']} ({len(source_files)} files) -> {out_dir}")
    return payload


def _scan_modules(relative_sources):
    rows = []
    factor_prefix = "commands/factor_lab/"
    groups: dict[str, int] = {}
    for relative in relative_sources:
        if relative.startswith(factor_prefix):
            name = relative[len(factor_prefix):].split("/", 1)[0]
            groups[name] = groups.get(name, 0) + 1
    for name in sorted(groups):
        rows.append({"module": name, "path": f"factor_lab/{name}", "py_files": groups[name], "type": "source-package"})
    return rows


def _scan_cli():
    path = SRC / "hermes_cli.py"
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    for line in content.splitlines():
        if "command == " in line or "elif command" in line:
            bits = line.split('"') if '"' in line else line.split("'")
            if len(bits) > 1 and bits[1]:
                rows.append({"command": bits[1], "handler": line.strip()[:80]})
    return rows


def _scan_gates(source_files):
    rows = []
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lower = text.lower()
        if "gate" not in lower and "verdict" not in lower:
            continue
        gate_types = [name for name in ("risk", "execution", "data", "config", "audit", "promotion") if name in lower]
        if gate_types:
            rows.append({"file": path.relative_to(PROJECT_ROOT).as_posix(), "gates": "|".join(gate_types), "lines": len(text.splitlines())})
    return rows


def _scan_configs():
    config_dir = SRC / "config"
    if not config_dir.exists():
        return []
    return [{"config": path.name, "path": path.relative_to(PROJECT_ROOT).as_posix()} for path in sorted(config_dir.iterdir()) if path.is_file()]


def _check_safety_boundary(source_files):
    rows = []
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for term in ("broker_adapter", "miniqmt", "live_execution", "place_order", "send_order"):
            if term in text:
                rows.append({"file": path.relative_to(PROJECT_ROOT).as_posix(), "term": term, "context": text[max(0, text.find(term) - 30):text.find(term) + 30]})
    return rows


def _scan_tests(relative_sources):
    rows = []
    for relative in relative_sources:
        path = Path(relative)
        if "commands/tests/" not in relative or not path.name.startswith("test_") or path.suffix != ".py":
            continue
        full = PROJECT_ROOT / path
        content = full.read_text(encoding="utf-8", errors="replace")
        rows.append({"file": relative, "tests": content.count("def test_"), "lines": len(content.splitlines()), "has_safety_test": "no_broker" in content or "no_trade" in content})
    return rows


def _find_duplications():
    return [{"area": "gate_logic", "files": "decision_loop/live_readiness/promotion", "impact": "重复风险/执行门禁，后续提取 GateEngine"}]


def _score_maintainability(modules, cli, dups):
    return max(4, 10 - int(len(modules) > 15) - int(len(cli) > 12) - 2 * int(len(dups) > 2))


def _score_safety(safety):
    return max(5, 10 - min(len(safety), 5))


def _score_tests(tests):
    count = sum(row["tests"] for row in tests)
    return 9 if count >= 200 else 7 if count >= 100 else 5


def _score_v3_readiness(modules):
    names = {row["module"] for row in modules}
    return 7 if {"adaptive", "paper"}.issubset(names) else 4


def _finding(severity, title, detail, suggestion):
    return {"severity": severity, "title": title, "detail": detail, "suggestion": suggestion}


def _write_csv(path: Path, rows, fieldnames=None):
    columns = fieldnames or (list(rows[0].keys()) if rows else ["status"])
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
