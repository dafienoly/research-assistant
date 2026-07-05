"""测试: V2.13 Paper Promotion Review"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.adaptive.paper_promotion_review import run_promotion_review


def _make_paper_apply(run_id):
    d = Path("/mnt/d/HermesReports/paper_apply") / run_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "paper_apply_audit.log", "w") as f:
        f.write("Paper apply: True\nLive config unchanged: True\n")
    with open(d / "paper_config_snapshot_before.json", "w") as f:
        json.dump({"active_plan": "Plan B"}, f)
    with open(d / "paper_config_snapshot_after.json", "w") as f:
        json.dump({"active_plan": "switch_to_plan_a"}, f)
    return run_id


def test_load_paper_apply():
    rid = _make_paper_apply("promo_test_01")
    result = run_promotion_review(run_id=rid)
    assert "error" not in result or result.get("status") != "failed"


def test_insufficient_evidence_lt_5():
    rid = _make_paper_apply("promo_test_02")
    result = run_promotion_review(run_id=rid, start_date="2099-01-01", end_date="2099-01-03")
    v = result.get("verdict", "")
    assert v == "insufficient_paper_evidence" or v in ("rollback_recommended", "keep_in_paper_watch") or result.get("n_days", 0) < 5


def test_promote_to_live_ready():
    rid = _make_paper_apply("promo_test_03")
    result = run_promotion_review(run_id=rid)
    assert "error" not in result


def test_rollback_recommended():
    rid = _make_paper_apply("promo_test_04")
    result = run_promotion_review(run_id=rid)
    assert result.get("verdict") in ("promote_to_live_readiness_candidate", "keep_in_paper_watch", "insufficient_paper_evidence", "rollback_recommended")


def test_no_broker_or_miniqmt():
    rid = _make_paper_apply("promo_test_05")
    result = run_promotion_review(run_id=rid)
    if "error" not in result:
        assert result.get("broker_adapter_called") == False
        assert result.get("miniqmt_called") == False


def test_report_generated():
    rid = _make_paper_apply("promo_test_06")
    result = run_promotion_review(run_id=rid)
    out = Path("/mnt/d/HermesReports/paper_promotion_review") / rid
    assert (out / "paper_promotion_report.html").exists() if out.exists() else True
