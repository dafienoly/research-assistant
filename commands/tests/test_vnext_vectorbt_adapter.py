from __future__ import annotations

import ast
from pathlib import Path

from factor_lab.vnext.vectorbt_adapter import inspect_worker_boundary


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_vectorbt_worker_has_no_data_client_or_execution_imports():
    audit = inspect_worker_boundary(PROJECT_ROOT / "commands" / "vectorbt_worker.py")
    assert audit["status"] == "OK"
    assert audit["violations"] == []
    assert audit["broker_import_allowed"] is False
    assert audit["data_client_import_allowed"] is False


def test_vectorbt_adapter_does_not_import_worker_or_execution_sdk_into_core():
    path = PROJECT_ROOT / "commands" / "factor_lab" / "vnext" / "vectorbt_adapter.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert "vectorbt" not in imports
    assert not any("broker" in name.lower() or "qmt" in name.lower() for name in imports)


def test_vectorbt_environment_is_isolated_from_core_environment():
    assert (PROJECT_ROOT / ".venv_vectorbt" / "bin" / "python").exists()
    assert (PROJECT_ROOT / "requirements" / "vectorbt.lock").exists()
    assert not (PROJECT_ROOT / ".venv_quant" / "lib" / "python3.14" / "site-packages" / "vectorbt").exists()
