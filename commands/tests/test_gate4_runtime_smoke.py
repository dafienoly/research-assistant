from __future__ import annotations

from pathlib import Path

from factor_lab.audit.gate4_runtime_smoke import _check_imports, _router_prefix, _to_module_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_router_prefix_composes_vnext_mount() -> None:
    route_file = PROJECT_ROOT / "commands" / "factor_lab" / "api_server" / "routes_vnext.py"
    assert _router_prefix(route_file) == "/vnext"


def test_module_paths_include_root_level_scripts() -> None:
    assert _to_module_path("scripts/mx_fetch_step.py") == "scripts.mx_fetch_step"
    assert _to_module_path("commands/vectorbt_worker.py") == "vectorbt_worker"


def test_isolated_worker_and_root_script_import_with_correct_environment() -> None:
    findings = _check_imports(["commands/vectorbt_worker.py", "scripts/mx_fetch_step.py"])
    failures = [finding for finding in findings if finding.severity == "FAIL"]
    assert failures == []
