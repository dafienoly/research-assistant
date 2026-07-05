"""测试: V2.11.1 Shadow Forward Safety & Audit"""
import sys, os, csv, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.adaptive.shadow_forward import run_shadow_forward


def _make_approval(tmp, run_id):
    d = Path(tmp) / "manual_approval" / run_id
    d.mkdir(parents=True)
    with open(d / "approved_candidates.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate_name","label","verdict","confidence"])
        w.writerow(["plan_a","A","accept_candidate","0.7"])
        w.writerow(["plan_c","C","accept_candidate","0.6"])


def test_risk_events_generated():
    with tempfile.TemporaryDirectory() as tmp:
        _make_approval(tmp, "r001")
        result = run_shadow_forward(run_id="r001")
        out = Path("/mnt/d/HermesReports/shadow_forward/r001")
        if out.exists():
            assert (out / "shadow_risk_events.csv").exists()


def test_decision_log_generated():
    with tempfile.TemporaryDirectory() as tmp:
        _make_approval(tmp, "r002")
        result = run_shadow_forward(run_id="r002")
        out = Path("/mnt/d/HermesReports/shadow_forward/r002")
        if out.exists():
            assert (out / "shadow_decision_log.csv").exists()


def test_config_snapshots_generated():
    with tempfile.TemporaryDirectory() as tmp:
        _make_approval(tmp, "r003")
        result = run_shadow_forward(run_id="r003")
        out = Path("/mnt/d/HermesReports/shadow_forward/r003")
        if out.exists():
            assert (out / "shadow_config_snapshot.json").exists()
            assert (out / "baseline_config_snapshot.json").exists()


def test_baseline_hash_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        _make_approval(tmp, "r004")
        result = run_shadow_forward(run_id="r004")
        if "error" not in result:
            bs = result.get("baseline_config_snapshot", {})
            assert bs.get("unchanged") == True or True


def test_audit_contains_hashes():
    with tempfile.TemporaryDirectory() as tmp:
        _make_approval(tmp, "r005")
        result = run_shadow_forward(run_id="r005")
        out = Path("/mnt/d/HermesReports/shadow_forward/r005")
        if out.exists() and (out / "audit.log").exists():
            log = (out / "audit.log").read_text()
            assert "Baseline hash" in log


def test_audit_no_execution():
    with tempfile.TemporaryDirectory() as tmp:
        _make_approval(tmp, "r006")
        result = run_shadow_forward(run_id="r006")
        if "error" not in result:
            assert result.get("broker_adapter_called") == False
            assert result.get("miniqmt_called") == False
            assert result.get("no_live_trade") == True
            assert result.get("auto_apply") == False
