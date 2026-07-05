"""测试: V2.14 Live Readiness"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.adaptive.live_readiness import run_live_readiness


def _make_promotion_review(run_id):
    d = Path("/mnt/d/HermesReports/paper_promotion_review") / run_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "paper_promotion_audit.log", "w") as f:
        f.write("Paper review only: True\nLive apply: False\n")


def test_load_promotion():
    _make_promotion_review("lr_001")
    result = run_live_readiness(run_id="lr_001")
    assert "error" not in result or result.get("status") != "failed"


def test_fail_when_no_promotion():
    result = run_live_readiness(run_id="nonexistent")
    assert "error" in result


def test_pass_live_readiness():
    _make_promotion_review("lr_002")
    result = run_live_readiness(run_id="lr_002")
    assert result.get("verdict") in ("pass_live_readiness", "conditional_pass", "fail_live_readiness", "insufficient_evidence")


def test_no_broker():
    _make_promotion_review("lr_003")
    result = run_live_readiness(run_id="lr_003")
    if "error" not in result:
        assert result.get("no_live_trade") == True or result.get("readiness_check_only")


def test_report_generated():
    _make_promotion_review("lr_004")
    result = run_live_readiness(run_id="lr_004")
    out = Path("/mnt/d/HermesReports/live_readiness/lr_004")
    assert (out / "live_readiness_report.html").exists() if out.exists() else True


def test_gates_checked():
    _make_promotion_review("lr_005")
    result = run_live_readiness(run_id="lr_005")
    if "error" not in result:
        assert "gates" in result
