"""测试: V2.14.1 Architecture Audit"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.architecture.architecture_audit import run_architecture_audit

OUT_DIR = "/tmp/arch_audit_test"


def test_audit_runs():
    result = run_architecture_audit(output_dir=OUT_DIR)
    assert Path(OUT_DIR).exists()


def test_module_inventory():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "module_map.csv").exists()


def test_cli_inventory():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "cli_command_inventory.csv").exists()


def test_artifact_inventory():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "artifact_inventory.csv").exists()


def test_gate_inventory():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "gate_inventory.csv").exists()


def test_audit_log_inventory():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "audit_log_inventory.csv").exists()


def test_safety_report():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "safety_boundary_report.csv").exists()


def test_refactor_recommendations():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "refactor_recommendations.md").exists()


def test_v3_readiness():
    run_architecture_audit(output_dir=OUT_DIR)
    assert (Path(OUT_DIR) / "v3_alpha_factory_readiness.md").exists()


def test_no_config_modifications():
    """审计不修改配置"""
    before = set(Path("/home/ly/.hermes/research-assistant/commands/config").rglob("*")) if Path("/home/ly/.hermes/research-assistant/commands/config").exists() else set()
    run_architecture_audit(output_dir=OUT_DIR)
    after = set(Path("/home/ly/.hermes/research-assistant/commands/config").rglob("*")) if Path("/home/ly/.hermes/research-assistant/commands/config").exists() else set()
    assert before == after
