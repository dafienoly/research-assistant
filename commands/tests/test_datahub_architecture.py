"""Architecture gate: downstream runtime modules must consume DataHub, not providers."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOTS = (
    ROOT / "commands/factor_lab/decision_loop",
    ROOT / "commands/factor_lab/api_server",
)
PROHIBITED_MODULES = {
    "akshare",
    "baostock",
    "tushare",
    "factor_lab.data.tushare_client",
    "eastmoney_direct",
    "provider_matrix",
    "rsscast_mcp",
}


def provider_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name in PROHIBITED_MODULES or any(name.startswith(f"{item}.") for item in PROHIBITED_MODULES):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
    return found


def test_runtime_modules_do_not_bypass_datahub():
    violations = []
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*.py"):
            violations.extend(provider_imports(path))
    assert violations == [], "runtime provider bypasses:\n" + "\n".join(violations)


def test_vnext_and_decision_loop_do_not_implement_notification_networking():
    violations = []
    for root in (ROOT / "commands/factor_lab/vnext", ROOT / "commands/factor_lab/decision_loop"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(name.startswith(("urllib", "requests", "httpx")) for name in names):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{','.join(names)}")
    assert violations == [], "notification transport bypasses:\n" + "\n".join(violations)


def test_vnext_event_truth_is_read_only_datahub_consumer():
    path = ROOT / "commands/factor_lab/vnext/event_truth_sources.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "data/normalized/events/event_truth" in source
    assert "._query(" not in source


def test_vnext_policy_dataset_is_read_only_datahub_consumer():
    path = ROOT / "commands/factor_lab/vnext/datasets.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "data/normalized/market_series" in source
    assert "get_ts_client" not in source
