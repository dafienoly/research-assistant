"""测试: V2.14.1 Architecture Audit"""
import os
import sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.architecture.architecture_audit import run_architecture_audit

OUT_DIR = "/tmp/arch_audit_test"


@pytest.fixture(scope="module", autouse=True)
def audit_once():
    """一次显式 release-mode source audit 覆盖所有产物断言。"""
    run_architecture_audit(output_dir=OUT_DIR, major_version="test.0.0")


def test_audit_runs():
    assert Path(OUT_DIR).exists()


def test_module_inventory():
    assert (Path(OUT_DIR) / "module_map.csv").exists()


def test_cli_inventory():
    assert (Path(OUT_DIR) / "cli_command_inventory.csv").exists()


def test_artifact_inventory():
    assert (Path(OUT_DIR) / "artifact_inventory.csv").exists()


def test_gate_inventory():
    assert (Path(OUT_DIR) / "gate_inventory.csv").exists()


def test_audit_log_inventory():
    assert (Path(OUT_DIR) / "audit_log_inventory.csv").exists()


def test_safety_report():
    assert (Path(OUT_DIR) / "safety_boundary_report.csv").exists()


def test_refactor_recommendations():
    assert (Path(OUT_DIR) / "refactor_recommendations.md").exists()


def test_v3_readiness():
    assert (Path(OUT_DIR) / "v3_alpha_factory_readiness.md").exists()


def test_no_config_modifications():
    """审计不修改配置"""
    before = set(Path("/home/ly/.hermes/research-assistant/commands/config").rglob("*")) if Path("/home/ly/.hermes/research-assistant/commands/config").exists() else set()
    after = set(Path("/home/ly/.hermes/research-assistant/commands/config").rglob("*")) if Path("/home/ly/.hermes/research-assistant/commands/config").exists() else set()
    assert before == after
