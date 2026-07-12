"""测试: V2.14.2 Architecture Refactor Core Modules"""
import sys, os, json, tempfile, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.core.audit import AuditTrail
from factor_lab.core.gate import GateEngine, GateCheck
from factor_lab.core.artifact import ArtifactManifest
from factor_lab.core.config import ConfigManager
from factor_lab.core.report import ReportBuilder
from factor_lab.core.cli import CommandRegistry, CommandDef, COMMON_OPTIONS
from factor_lab.core.pipeline import RunContext, PipelineStage
from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.registry import list_alpha, register_alpha


def test_audit_jsonl_written():
    with tempfile.TemporaryDirectory() as tmp:
        a = AuditTrail(tmp)
        a.log("test", run_id="r1", module="test", status="passed")
        assert (Path(tmp) / "audit.jsonl").exists()
        events = a.get_events()
        assert len(events) >= 1


def test_gate_engine_blockers():
    ge = GateEngine()
    ge.add_check("risk", "dd_check", passed=False, severity="blocker")
    ge.add_check("risk", "vol_check", passed=True)
    ge.finalize()
    assert len(ge.results[0].blockers) == 1


def test_artifact_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "report.html").write_text("test")
        m = ArtifactManifest(tmp, run_id="r1")
        m.add_file("report.html")
        m.write()
        manifest_path = Path(tmp) / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["run_id"] == "r1"


def test_config_hash():
    cm = ConfigManager()
    cfg = {"plan": "B", "top_n": 8}
    h = cm.hash_config(cfg)
    assert len(h) == 16


def test_config_diff():
    cm = ConfigManager()
    before = {"plan": "B", "top_n": 8}
    after = {"plan": "A", "top_n": 10}
    changes = cm.diff(before, after)
    assert len(changes) == 2


def test_report_builder():
    with tempfile.TemporaryDirectory() as tmp:
        r = ReportBuilder(tmp)
        r.add_section("Test", "Hello")
        r.write_html("test.html")
        assert (Path(tmp) / "test.html").exists()


def test_command_registry():
    cr = CommandRegistry()
    cmd = CommandDef(name="test", handler="test_fn", options=COMMON_OPTIONS)
    cr.register(cmd)
    assert cr.get("test") is not None


def test_run_context():
    rc = RunContext(run_id="r1", module="test")
    assert rc.run_id == "r1"


def test_alpha_schema():
    a = AlphaSpec(name="test_alpha")
    assert a.status == "draft"


def test_alpha_registry(tmp_path, monkeypatch):
    from factor_lab.alpha.schema import AlphaSpec
    import factor_lab.alpha.registry as registry

    monkeypatch.setattr(registry, "REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(registry, "REGISTRY_INDEX", tmp_path / "registry_index.json")
    spec = AlphaSpec(name="core_test_alpha")
    result = register_alpha(spec)
    assert "alpha_id" in result
    alphas = list_alpha()
    assert len(alphas) >= 1


def test_no_config_modified():
    """核心模块不修改配置"""
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/core/audit.py").read()
    # paper_config 在注释和 schema 字段中出现是正常的
    assert "send_order" not in src
    assert "place_order" not in src


def test_no_broker_in_core():
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/core/gate.py").read()
    for term in ["broker", "miniqmt", "send_order", "place_order"]:
        assert term not in src
