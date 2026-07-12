"""测试: V3.0 Alpha Factory"""
import sys, os, json, tempfile, shutil
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.registry import register_alpha, list_alpha, get_alpha, retire_alpha, REGISTRY_ROOT
from factor_lab.alpha.lifecycle import AlphaLifecycle
from factor_lab.alpha.evaluation_hook import generate_evaluation_plan

REGISTRY_BACKUP = "/tmp/alpha_registry_backup"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Keep factory tests out of the durable D: drive Alpha registry."""
    import factor_lab.alpha.registry as registry

    monkeypatch.setattr(registry, "REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(registry, "REGISTRY_INDEX", tmp_path / "registry_index.json")
    monkeypatch.setattr(sys.modules[__name__], "REGISTRY_ROOT", tmp_path)


def _clean():
    if REGISTRY_ROOT.exists():
        pass  # Tests run against real registry


def _make_spec():
    return AlphaSpec(name="test_alpha", hypothesis="test", status="registered",
                     enabled=False, paper_enabled=False, live_enabled=False)


def test_register_creates_dir():
    a = register_alpha(_make_spec())
    d = REGISTRY_ROOT / a["alpha_id"]
    assert d.exists()


def test_register_writes_spec():
    a = register_alpha(_make_spec())
    assert (REGISTRY_ROOT / a["alpha_id"] / "alpha_spec.json").exists()


def test_register_writes_manifest():
    a = register_alpha(_make_spec())
    assert (REGISTRY_ROOT / a["alpha_id"] / "manifest.json").exists()


def test_register_writes_audit():
    a = register_alpha(_make_spec())
    assert (REGISTRY_ROOT / a["alpha_id"] / "audit.jsonl").exists()


def test_list_returns():
    alphas = list_alpha()
    assert isinstance(alphas, list)


def test_show_returns():
    a = register_alpha(_make_spec())
    spec = get_alpha(a["alpha_id"])
    assert spec.get("name") == "test_alpha"


def test_retire_sets_status():
    a = register_alpha(_make_spec())
    r = retire_alpha(a["alpha_id"])
    assert r.get("status") == "retired"


def test_lifecycle_transition():
    lc = AlphaLifecycle("/tmp")
    assert lc.can_transition("draft", "registered")
    assert not lc.can_transition("registered", "live_active")


def test_evaluation_plan():
    a = register_alpha(_make_spec())
    plan = generate_evaluation_plan(a["alpha_id"])
    assert "plan" in plan


def test_sample_alphas_disabled():
    from factor_lab.alpha.sample_alphas import create_sample_alphas
    samples = create_sample_alphas()
    for s in samples:
        spec = get_alpha(s["alpha_id"])
        assert spec.get("enabled") == False
        assert spec.get("paper_enabled") == False
        assert spec.get("live_enabled") == False


def test_no_broker_in_alpha():
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/registry.py").read()
    assert "broker" not in src
    assert "miniqmt" not in src
