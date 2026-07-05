"""Automated acceptance and local CI for Hermes research system.

This module is intentionally conservative: it validates CLI wiring, migration
artifacts, registry state, safety boundaries, and optionally runs the full test
suite. It does not trigger order placement, broker calls, or strategy config
changes.
"""

from __future__ import annotations

import ast
import csv
import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

CST = timezone(timedelta(hours=8))
RESEARCH_ROOT = Path("/home/ly/.hermes/research-assistant")
COMMANDS_ROOT = RESEARCH_ROOT / "commands"
HERMES_CLI = COMMANDS_ROOT / "hermes_cli.py"
PYTHON = RESEARCH_ROOT / ".venv_quant" / "bin" / "python3"
REPORT_ROOT = Path("/mnt/d/HermesReports")
MIGRATION_ROOT = REPORT_ROOT / "alpha_factor_migration"
ACCEPTANCE_ROOT = REPORT_ROOT / "leader_acceptance"
ALPHA_REGISTRY_ROOT = Path("/mnt/d/HermesData/alpha_registry")

REQUIRED_MIGRATION_FILES = (
    "factor_migration_report.html",
    "factor_migration_summary.md",
    "factor_catalog_registry.csv",
    "factor_category_summary.csv",
    "factor_alpha_mapping.csv",
    "migrated_factors.csv",
    "skipped_factors.csv",
    "duplicate_factors.csv",
    "factor_expression_validation.csv",
    "factor_data_requirements.csv",
    "factor_correlation_baseline.csv",
    "alpha_registry_update_preview.json",
    "manifest.json",
    "audit.jsonl",
    "audit.log",
)

REQUIRED_ALPHA_FIELDS = (
    "alpha_id",
    "name",
    "description",
    "hypothesis",
    "factor_expression",
    "universe",
    "signal_direction",
    "rebalance_frequency",
    "source",
    "author",
    "created_at",
    "version",
    "status",
    "enabled",
    "paper_enabled",
    "live_enabled",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    severity: str
    detail: str
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def run_acceptance(full_tests: bool = False, smoke: bool = True) -> dict:
    """Run automated acceptance checks and write an acceptance report."""
    run_id = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = ACCEPTANCE_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    checks: list[CheckResult] = []
    checks.extend(_check_alpha_cli_contract())
    checks.extend(_check_latest_migration_artifacts())
    checks.extend(_check_alpha_registry_contract())
    checks.extend(_check_safety_source_scan())
    if smoke:
        checks.extend(_run_smoke_commands(out_dir))
    if full_tests:
        checks.append(_run_full_pytest(out_dir))

    verdict = "passed" if all(c.status == "passed" or c.severity != "blocker" for c in checks) else "failed"
    summary = {
        "run_id": run_id,
        "generated_at": _now_iso(),
        "verdict": verdict,
        "full_tests": full_tests,
        "smoke": smoke,
        "checks_total": len(checks),
        "passed": sum(1 for c in checks if c.status == "passed"),
        "failed": sum(1 for c in checks if c.status == "failed"),
        "blockers": sum(1 for c in checks if c.status == "failed" and c.severity == "blocker"),
        "checks": [c.to_dict() for c in checks],
        "output_dir": str(out_dir),
    }
    (out_dir / "acceptance.json").write_text(_json(summary), encoding="utf-8")
    (out_dir / "acceptance_report.md").write_text(_render_markdown(summary), encoding="utf-8")
    (out_dir / "audit.jsonl").write_text(json.dumps({
        "event": "leader_acceptance",
        "run_id": run_id,
        "verdict": verdict,
        "generated_at": summary["generated_at"],
        "safety": _safety_flags(),
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "manifest.json").write_text(_json({
        "run_id": run_id,
        "files": ["acceptance.json", "acceptance_report.md", "audit.jsonl", "manifest.json"],
        "safety": _safety_flags(),
    }), encoding="utf-8")
    (ACCEPTANCE_ROOT / "latest.json").write_text(_json({
        "run_id": run_id,
        "verdict": verdict,
        "output_dir": str(out_dir),
        "generated_at": summary["generated_at"],
    }), encoding="utf-8")
    return summary


def _check_alpha_cli_contract() -> list[CheckResult]:
    src = HERMES_CLI.read_text(encoding="utf-8") if HERMES_CLI.exists() else ""
    alpha_src = (COMMANDS_ROOT / "factor_lab" / "alpha" / "alpha_cli.py").read_text(encoding="utf-8")
    checks = []
    checks.append(_bool_check(
        "alpha register CLI help listed",
        "alpha:register" in src,
        "warning",
        "hermes_cli.py help should list alpha:register --spec <path>",
        "hermes_cli.py",
    ))
    checks.append(_bool_check(
        "alpha router exists",
        "command.startswith(\"alpha:\")" in src or "command.startswith('alpha:')" in src,
        "blocker",
        "hermes_cli.py must route alpha:* to alpha_cli",
        "hermes_cli.py",
    ))
    checks.append(_bool_check(
        "alpha_cli register subcommand exists",
        "sub.add_parser(\"register\")" in alpha_src or "sub.add_parser('register')" in alpha_src,
        "blocker",
        "alpha_cli.py must implement register --spec",
        "factor_lab/alpha/alpha_cli.py",
    ))
    checks.append(_bool_check(
        "migration CLI exists",
        "migrate-existing-factors" in alpha_src,
        "blocker",
        "alpha_cli.py must implement migrate-existing-factors",
        "factor_lab/alpha/alpha_cli.py",
    ))
    return checks


def _check_latest_migration_artifacts() -> list[CheckResult]:
    checks: list[CheckResult] = []
    latest = _latest_dir(MIGRATION_ROOT)
    checks.append(_bool_check(
        "migration report directory exists",
        latest is not None,
        "blocker",
        "Expected /mnt/d/HermesReports/alpha_factor_migration/<run_id>",
        str(MIGRATION_ROOT),
    ))
    if latest is None:
        return checks
    existing = {p.name for p in latest.iterdir() if p.is_file()}
    missing = [f for f in REQUIRED_MIGRATION_FILES if f not in existing]
    checks.append(_bool_check(
        "migration required files complete",
        not missing,
        "blocker",
        "Missing files: " + ", ".join(missing) if missing else "All required files present",
        str(latest),
    ))
    category_file = latest / "factor_category_summary.csv"
    if category_file.exists():
        categories = _read_csv_rows(category_file)
        category_names = {r.get("category", "") for r in categories}
        required = {"momentum", "trend", "volume", "volatility", "reversal", "liquidity", "quality", "fund_flow", "sentiment"}
        missing_categories = sorted(required - category_names)
        checks.append(_bool_check(
            "required factor categories covered",
            not missing_categories,
            "warning",
            "Missing categories: " + ", ".join(missing_categories) if missing_categories else "Core categories covered",
            str(category_file),
        ))
    return checks


def _check_alpha_registry_contract() -> list[CheckResult]:
    checks: list[CheckResult] = []
    index = ALPHA_REGISTRY_ROOT / "registry_index.json"
    checks.append(_bool_check(
        "alpha registry index exists",
        index.exists(),
        "blocker",
        "Expected registry_index.json",
        str(index),
    ))
    if not index.exists():
        return checks
    try:
        alphas = json.loads(index.read_text(encoding="utf-8"))
    except Exception as exc:
        checks.append(CheckResult("alpha registry index parse", "failed", "blocker", str(exc), str(index)))
        return checks
    checks.append(_bool_check(
        "alpha registry has migrated factors",
        len(alphas) >= 86,
        "blocker",
        f"registry_count={len(alphas)}",
        str(index),
    ))
    sample_ids = [a.get("alpha_id") for a in alphas[: min(20, len(alphas))] if a.get("alpha_id")]
    missing_spec = []
    unsafe = []
    missing_fields = []
    for alpha_id in sample_ids:
        alpha_dir = ALPHA_REGISTRY_ROOT / alpha_id
        spec_path = alpha_dir / "alpha_spec.json"
        if not spec_path.exists():
            missing_spec.append(alpha_id)
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        for field in REQUIRED_ALPHA_FIELDS:
            if field not in spec:
                missing_fields.append(f"{alpha_id}:{field}")
        if spec.get("enabled") or spec.get("paper_enabled") or spec.get("live_enabled"):
            unsafe.append(alpha_id)
        for sub in ("versions", "artifacts", "evaluation", "promotion_history"):
            if not (alpha_dir / sub).exists():
                missing_fields.append(f"{alpha_id}:{sub}/")
    checks.append(_bool_check(
        "sample alpha specs exist",
        not missing_spec,
        "blocker",
        "Missing specs: " + ", ".join(missing_spec[:10]) if missing_spec else "Sample specs exist",
        str(ALPHA_REGISTRY_ROOT),
    ))
    checks.append(_bool_check(
        "sample alpha specs have required fields",
        not missing_fields,
        "warning",
        "Missing fields: " + ", ".join(missing_fields[:20]) if missing_fields else "Required fields present in sample",
        str(ALPHA_REGISTRY_ROOT),
    ))
    checks.append(_bool_check(
        "migrated alpha defaults disabled",
        not unsafe,
        "blocker",
        "Unsafe enabled flags in: " + ", ".join(unsafe[:10]) if unsafe else "All sampled Alpha disabled",
        str(ALPHA_REGISTRY_ROOT),
    ))
    return checks


def _check_safety_source_scan() -> list[CheckResult]:
    risky_names = {"send_order", "place_order", "execute_trade"}
    roots = [COMMANDS_ROOT / "factor_lab" / "alpha", COMMANDS_ROOT / "factor_lab" / "leader"]
    hits = []
    for root in roots:
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            src = py.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in risky_names:
                    hits.append(f"{py.relative_to(COMMANDS_ROOT)}:{name}")
    return [_bool_check(
        "alpha and leader source has no order execution calls",
        not hits,
        "blocker",
        "Risky calls: " + ", ".join(hits) if hits else "No order execution calls found",
        "factor_lab/alpha + factor_lab/leader",
    )]


def _run_smoke_commands(out_dir: Path) -> list[CheckResult]:
    commands = [
        [str(PYTHON), str(HERMES_CLI), "alpha:list"],
        [str(PYTHON), str(HERMES_CLI), "leader:inspect"],
    ]
    checks = []
    for i, cmd in enumerate(commands, 1):
        log_path = out_dir / f"smoke_{i}.log"
        result = subprocess.run(cmd, cwd=str(COMMANDS_ROOT), capture_output=True, text=True, timeout=120)
        log_path.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
        checks.append(_bool_check(
            "smoke command " + " ".join(cmd[-2:]),
            result.returncode == 0,
            "blocker",
            f"returncode={result.returncode}",
            str(log_path),
        ))
    return checks


def _run_full_pytest(out_dir: Path) -> CheckResult:
    log_path = out_dir / "pytest_full.log"
    result = subprocess.run([str(PYTHON), "-m", "pytest", "-q"], cwd=str(COMMANDS_ROOT), capture_output=True, text=True, timeout=1800)
    log_path.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    return _bool_check(
        "full pytest suite",
        result.returncode == 0,
        "blocker",
        f"returncode={result.returncode}",
        str(log_path),
    )


def _latest_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    dirs = [p for p in root.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _bool_check(name: str, ok: bool, severity: str, detail: str, evidence: str = "") -> CheckResult:
    return CheckResult(name=name, status="passed" if ok else "failed", severity=severity, detail=detail, evidence=evidence)


def _render_markdown(summary: dict) -> str:
    rows = "\n".join(
        f"| {c['status']} | {c['severity']} | {c['name']} | {c['detail']} | {c.get('evidence', '')} |"
        for c in summary["checks"]
    )
    return f"""# Hermes Leader Acceptance Report

Run: {summary['run_id']}  
Generated: {summary['generated_at']}  
Verdict: **{summary['verdict']}**  
Full tests: `{summary['full_tests']}`  
Smoke: `{summary['smoke']}`

## Summary

- Checks: {summary['checks_total']}
- Passed: {summary['passed']}
- Failed: {summary['failed']}
- Blockers: {summary['blockers']}

## Checks

| Status | Severity | Check | Detail | Evidence |
|--------|----------|-------|--------|----------|
{rows}

## Safety

- no order execution
- no broker adapter invocation
- no miniqmt invocation
- no paper or production config modification
- acceptance writes report artifacts only
"""


def _safety_flags() -> dict:
    return {
        "no_order_execution": True,
        "no_broker_call": True,
        "no_miniqmt_call": True,
        "no_config_change": True,
        "report_only": True,
    }


def _json(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(CST).isoformat()
