from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROVIDER_MODULES = {"akshare", "baostock", "jqdatasdk", "tushare"}
ALLOWED_PREFIXES = (
    "commands/data_providers/",
    "commands/factor_lab/data/",
    "commands/factor_lab/data_source/",
    "commands/factor_lab/datahub_ingestion/",
)
ALLOWED_FILES = {
    "commands/provider_matrix.py",
    "commands/rsscast_mcp.py",
    "commands/eastmoney_direct.py",
}


def test_provider_sdks_exist_only_at_datahub_ingestion_boundaries() -> None:
    violations: list[str] = []
    for path in (ROOT / "commands").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if "/tests/" in f"/{relative}" or relative in ALLOWED_FILES or relative.startswith(ALLOWED_PREFIXES):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            else:
                continue
            for module in modules:
                if module in PROVIDER_MODULES:
                    violations.append(f"{relative}:{node.lineno}:{module}")
    assert violations == [], "provider SDK outside DataHub boundary:\n" + "\n".join(violations)


def test_global_dns_monkeypatch_module_is_retired() -> None:
    assert not (ROOT / "commands/dns_patch.py").exists()


def test_vnext_health_and_snapshot_use_canonical_datahub_contracts() -> None:
    service_source = (ROOT / "commands/factor_lab/vnext/service.py").read_text(encoding="utf-8")
    snapshot_source = (ROOT / "commands/factor_lab/vnext/snapshot.py").read_text(encoding="utf-8")
    assert "/mnt/c/Users/" not in service_source
    assert "/mnt/c/Users/" not in snapshot_source
    assert "data/audit/health" not in service_source
    assert '"coverage.json"' in service_source
    assert '"freshness.json"' in service_source
    assert '"integrity.json"' in service_source
    assert "LIVE_SNAPSHOT_PATH" in snapshot_source
    assert "read_live_snapshot" in snapshot_source
