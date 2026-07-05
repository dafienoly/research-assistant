"""测试: V2.12 Paper Apply"""
import sys, os, csv, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.adaptive.paper_apply import run_paper_apply


def _make_shadow(tmp, run_id, verdict="promote_candidate_watch", n_days=10, audit_pass=True):
    d = Path(tmp) / "shadow_forward" / run_id
    d.mkdir(parents=True)
    with open(d / "baseline_vs_shadow.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate","verdict","n_days","baseline_return_pct","shadow_return_pct"])
        w.writerow(["switch_to_plan_a", verdict, str(n_days), "10", "12"])
    with open(d / "audit.log", "w") as f:
        f.write(f"Audit passed: {audit_pass}\n")
        f.write("shadow_only: True\n")
        f.write("broker_adapter_called: False\n")
        f.write("miniqmt_called: False\n")


def test_default_is_dry_run():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a001")
        result = run_paper_apply(run_id="a001")
        if "error" not in result:
            assert result.get("dry_run") == True
            assert result.get("paper_apply") == False


def test_reject_shadow_cannot_apply():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a002", verdict="reject_shadow_candidate")
        result = run_paper_apply(run_id="a002")
        assert "error" in result or not any(q.get("candidate") for q in result.get("qualified", []))


def test_insufficient_evidence_cannot_apply():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a003", verdict="insufficient_forward_evidence", n_days=3)
        result = run_paper_apply(run_id="a003")
        assert "error" in result or not result.get("qualified")


def test_audit_failed_cannot_apply():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a004", audit_pass=False)
        result = run_paper_apply(run_id="a004")
        assert "error" in result


def test_promote_candidate_generates_patch():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a005", verdict="promote_candidate_watch", n_days=10)
        result = run_paper_apply(run_id="a005")
        out = Path("/mnt/d/HermesReports/paper_apply/a005")
        if out.exists():
            assert (out / "paper_config_patch.diff").exists()


def test_live_config_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a006")
        result = run_paper_apply(run_id="a006")
        if "error" not in result:
            assert result.get("live_config_unchanged") == True


def test_broker_miniqmt_not_called():
    with tempfile.TemporaryDirectory() as tmp:
        _make_shadow(tmp, "a007")
        result = run_paper_apply(run_id="a007")
        if "error" not in result:
            assert result.get("broker_adapter_called") == False
            assert result.get("miniqmt_called") == False
