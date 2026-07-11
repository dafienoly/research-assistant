#!/usr/bin/env python3
"""Hermes VNext dependency, secret and execution-boundary CI gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^=\s]+$")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]([A-Za-z0-9_./+:-]{16,})['\"]"
)
BANNED_BOUNDARY_RE = re.compile(
    r"(^|\n)\s*(?:from|import)\s+(?:vnpy|xtquant)(?:\.|\s|$)|MiniQMTLiveBroker|\bsend_order\s*\("
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class VNextCIGate:
    def run(self, project_root: str | Path) -> dict[str, Any]:
        root = Path(project_root).resolve()
        errors: list[str] = []
        checks: dict[str, Any] = {}
        approval_path = root / "approved_dependencies.yaml"
        approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))

        lock_results = []
        for name, environment in approval.get("environments", {}).items():
            lock_path = root / str(environment["lock_file"])
            expected = str(environment["sha256"])
            actual = _sha256(lock_path) if lock_path.exists() else None
            hash_ok = actual == expected
            if not hash_ok:
                errors.append(f"LOCK_HASH_MISMATCH:{name}")
            pin_errors: list[str] = []
            if lock_path.suffix == ".lock":
                active_lines = [
                    line.strip()
                    for line in lock_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ]
                if environment["status"] in {"active", "active_isolated"}:
                    pin_errors = [line for line in active_lines if not PIN_RE.fullmatch(line)]
                elif active_lines:
                    pin_errors = ["deferred environment contains active requirements"]
                if pin_errors:
                    errors.append(f"UNPINNED_OR_UNAPPROVED_LOCK:{name}")
            lock_results.append(
                {"environment": name, "path": str(lock_path.relative_to(root)), "hash_ok": hash_ok, "pin_errors": pin_errors}
            )
        checks["dependency_locks"] = lock_results

        core = approval["environments"]["hermes-core"]
        core_packages = {
            line.split("==", 1)[0].lower()
            for line in (root / core["lock_file"]).read_text(encoding="utf-8").splitlines()
            if PIN_RE.fullmatch(line.strip())
        }
        prohibited = sorted(set(map(str.lower, core.get("prohibited_packages", []))).intersection(core_packages))
        if prohibited:
            errors.append("PROHIBITED_CORE_DEPENDENCY:" + ",".join(prohibited))
        checks["core_prohibited_packages"] = prohibited

        boundary_findings = []
        boundary_roots = [root / "commands" / "frontend" / "src", root / "commands" / "factor_lab" / "api_server"]
        for source_root in boundary_roots:
            for path in source_root.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                    continue
                if BANNED_BOUNDARY_RE.search(path.read_text(encoding="utf-8", errors="ignore")):
                    boundary_findings.append(str(path.relative_to(root)))
        if boundary_findings:
            errors.append("UI_API_BROKER_BOUNDARY_VIOLATION")
        checks["ui_api_broker_boundary"] = {"findings": sorted(boundary_findings)}

        secret_findings = []
        ignored_parts = {
            ".git",
            ".venv_quant",
            ".venv_vectorbt",
            "node_modules",
            "data",
            "artifacts",
            "agent_tasks",
            "tests",
            "docs",
            "third_party",
            "analysis_report",
        }
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json", ".sh"}:
                continue
            relative = path.relative_to(root)
            if any(part in ignored_parts for part in relative.parts) or path.name == "package-lock.json":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in SECRET_RE.finditer(text):
                value = match.group(2)
                if value.lower().startswith(("test-", "example", "changeme", "your-")):
                    continue
                secret_findings.append({"file": str(relative), "line": text.count("\n", 0, match.start()) + 1})
        if secret_findings:
            errors.append("SECRET_LEAK_PATTERN")
        checks["secret_scan"] = {"findings": secret_findings}

        snapshot = json.loads((root / "artifacts" / "vnext" / "snapshot_manifest.json").read_text(encoding="utf-8"))
        data_audit = json.loads((root / "artifacts" / "vnext" / "data_audit_report.json").read_text(encoding="utf-8"))
        truth_ok = snapshot.get("silent_fallback_used") is False and data_audit.get("no_mock_or_fallback") is True
        if not truth_ok:
            errors.append("MOCK_OR_SILENT_FALLBACK_EVIDENCE_FAILED")
        checks["production_truthfulness"] = {
            "silent_fallback_used": snapshot.get("silent_fallback_used"),
            "no_mock_or_fallback": data_audit.get("no_mock_or_fallback"),
        }

        frameworks = approval.get("upstream_frameworks", {})
        license_ok = (
            frameworks.get("openbb", {}).get("decision") == "optional_out_of_process_sidecar_only"
            and frameworks.get("vectorbt", {}).get("decision") == "conditional_research_only"
        )
        if not license_ok:
            errors.append("DANGEROUS_LICENSE_POLICY_MISMATCH")
        checks["license_policy"] = {"passed": license_ok}
        return {"status": "OK" if not errors else "BLOCKED", "errors": errors, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = VNextCIGate().run(args.root)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
