"""Code audit CLI and compatibility entrypoints."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from .base import AuditReport
from .coordinator import AuditCoordinator, AuditRequest
from .storage import AuditStore

BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT", "/home/ly/.hermes/research-assistant"))


def run_code_audit(
    profile: str = "fast",
    scope: str = "working-tree",
    base_ref: str = "main",
    paths: Optional[list[str]] = None,
    trigger: str = "manual",
    requested_by: str = "local",
    major_version: str = "",
) -> AuditReport:
    """Run source-only audit, but only when a major version is explicit.

    This policy is intentionally fail-open for old automation: legacy calls
    return a structured ``skipped`` report without touching data, temp files,
    pytest, Semgrep or GitNexus. A release engineer must pass ``major_version``
    to opt into the bounded source audit.
    """
    request = AuditRequest(
        repo_root=BASE,
        profile=profile,
        scope=scope,
        base_ref=base_ref,
        paths=paths or [],
        trigger=trigger,
        requested_by=requested_by,
        major_version=major_version,
    )
    return AuditCoordinator().run(request)


def run_all_gates(
    version: str = "",
    skip_gates: Optional[list[str]] = None,
    plan_path: Optional[str] = None,
    enable_gate5: bool = False,
    risk: str = "auto",
    output_dir: Optional[str] = None,
) -> AuditReport:
    """Compatibility wrapper; legacy gate flags no longer execute any audit."""
    report = run_code_audit(
        profile="full",
        scope="working-tree",
        trigger="legacy-cli",
        major_version=version,
    )
    report.extras["legacy_options"] = {
        "legacy_runner_retired": True,
        "skip_gates_ignored": skip_gates or [],
        "plan_path": plan_path or "",
        "enable_gate5_ignored": enable_gate5,
        "risk_hint": risk,
        "output_dir_ignored": output_dir or "",
    }
    return report


def save_report(report: AuditReport) -> str:
    """Return the canonical report path without creating a duplicate report."""
    target = AuditStore().root / report.run_id / "report.json"
    if not target.exists():
        AuditStore().save(report)
    return str(target)


def cmd_main(args: list[str] | None = None, deprecated: bool = False) -> int:
    parser = argparse.ArgumentParser(description="Hermes major-version source audit")
    parser.add_argument("--profile", choices=["fast", "full", "security"], default="full" if deprecated else "fast")
    parser.add_argument("--scope", choices=["working-tree", "staged", "compare", "paths"], default="working-tree")
    parser.add_argument("--base", default="main")
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--major-version", default="", help="显式大版本号，例如 2.0.0；缺省时审计停用")
    parser.add_argument("--json", action="store_true")
    # Accepted only so existing hooks fail gracefully during the deprecation window.
    parser.add_argument("--version", default="", help=argparse.SUPPRESS)
    parser.add_argument("--skip", nargs="*", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--enable-gate5", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--risk", default="auto", help=argparse.SUPPRESS)
    parser.add_argument("--output", default="", help=argparse.SUPPRESS)
    options, unknown = parser.parse_known_args(args or [])
    if unknown:
        parser.error(f"unknown arguments: {' '.join(unknown)}")
    major_version = options.major_version.strip() or (options.version.strip() if options.version.strip() else "")
    if major_version and not re.match(r"^\d+\.\d+(?:\.\d+)?(?:[-+].*)?$", major_version):
        parser.error("--major-version 必须是类似 2.0 或 2.0.0 的版本号")
    if deprecated:
        print("DEPRECATED: legacy anti-cheat audit is disabled; use --major-version for release audit.", file=sys.stderr)
    report = run_code_audit(
        profile=options.profile,
        scope=options.scope,
        base_ref=options.base,
        paths=options.paths,
        trigger="legacy-cli" if deprecated else ("major-version" if major_version else "policy-check"),
        major_version=major_version,
    )
    if options.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.summary_text())
        if report.state != "skipped":
            print(f"\n报告: {save_report(report)}")
        else:
            print("\n未执行源码扫描：只有显式大版本发布前审计才会运行。")
    return 0 if report.state == "skipped" or (report.passed and report.state == "passed") else 1


if __name__ == "__main__":
    raise SystemExit(cmd_main())
