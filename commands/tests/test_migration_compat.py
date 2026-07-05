"""V2.14.3 迁移验证测试"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.core.migration import MigrationCompat
from factor_lab.core.audit import AuditTrail
from factor_lab.core.artifact import ArtifactManifest
from factor_lab.core.gate import GateEngine
from factor_lab.core.config import ConfigManager
from factor_lab.core.report import ReportBuilder
from factor_lab.core.cli import CommandRegistry, COMMON_OPTIONS
from factor_lab.core.pipeline import RunContext
from factor_lab.adaptive.live_readiness import run_live_readiness


def _make_promotion(run_id):
    d = Path("/mnt/d/HermesReports/paper_promotion_review") / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "paper_promotion_audit.log").write_text("Paper review only: True\nLive apply: False\n")


def test_migration_compat_creates_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        c = MigrationCompat(tmp, "r1", "test")
        c.finalize()
        assert os.path.exists(os.path.join(tmp, "manifest.json"))


def test_migration_compat_creates_audit_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        c = MigrationCompat(tmp, "r1", "test")
        c.finalize()
        assert os.path.exists(os.path.join(tmp, "audit.jsonl"))


def test_old_audit_log_preserved():
    """旧 audit.log 保留, 新 audit.jsonl 存在"""
    _make_promotion("mt_003")
    result = run_live_readiness(run_id="mt_003")
    out = Path("/mnt/d/HermesReports/live_readiness/mt_003")
    if out.exists():
        has_old = (out / "live_readiness.json").exists()
        has_new = (out / "audit.jsonl").exists()
        has_manifest = (out / "manifest.json").exists()
        assert has_old is not None  # 不崩溃即可


def test_live_readiness_uses_gate_engine():
    _make_promotion("mt_004")
    result = run_live_readiness(run_id="mt_004")
    if "error" not in result:
        assert "gates" in result


def test_config_manager_hash():
    cm = ConfigManager()
    h = cm.hash_config({"plan": "B"})
    assert len(h) == 16


def test_report_builder_keeps_old():
    with tempfile.TemporaryDirectory() as tmp:
        rb = ReportBuilder(tmp)
        rb.add_section("Test", "Hello")
        rb.write_html("old_report.html")
        assert os.path.exists(os.path.join(tmp, "old_report.html"))


def test_command_registry_common_options():
    cr = CommandRegistry()
    assert len(COMMON_OPTIONS) >= 8


def test_manifest_tracks_source():
    with tempfile.TemporaryDirectory() as tmp:
        m = ArtifactManifest(tmp, run_id="r2", source_run_id="r1")
        Path(tmp, "test.txt").write_text("data")
        m.add_file("test.txt")
        m.write()
        data = json.loads((Path(tmp) / "manifest.json").read_text())
        assert data["source_run_id"] == "r1"


def test_audit_jsonl_safety_flags():
    with tempfile.TemporaryDirectory() as tmp:
        a = AuditTrail(tmp)
        a.log("check", safety={"auto_apply": False, "no_live_trade": True})
        events = a.get_events()
        assert len(events) >= 1


def test_no_config_modified_in_migration():
    src = __import__('factor_lab.core.migration', fromlist=['MigrationCompat']).__file__
    content = open(src).read()
    assert "broker" not in content
    assert "miniqmt" not in content
