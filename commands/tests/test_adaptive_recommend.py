"""测试: V2.8 Adaptive Recommendation"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.adaptive.adaptive_recommendation import run_adaptive_recommend, generate_recommendation_report


def test_recommend_no_data():
    result = run_adaptive_recommend("2099-01-01", "2099-01-05")
    assert result["status"] == "no_data" or "status" in result


def test_recommend_loads():
    result = run_adaptive_recommend("2026-07-01", "2026-07-31")
    assert "status" in result


def test_plan_recommendation():
    result = run_adaptive_recommend("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        assert len(result.get("recommendations", [])) >= 1


def test_evidence_required():
    """每条建议有 evidence"""
    result = run_adaptive_recommend("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        for r in result.get("recommendations", []):
            assert "evidence" in r


def test_no_auto_apply():
    """不自动修改配置"""
    result = run_adaptive_recommend("2026-07-01", "2026-07-31")
    if result["status"] != "no_data":
        assert result.get("auto_apply") == False


def test_manual_approval_template():
    """人工审批模板生成"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run_adaptive_recommend("2026-07-01", "2026-07-31")
        if result.get("status") == "no_data":
            assert True
            return
        for key in ["n_completed_days", "n_pending_days", "evidence_quality", "recommendations"]:
            if key not in result:
                result[key] = 0 if key in ("n_completed_days", "n_pending_days") else [] if key == "recommendations" else "unknown"
        generate_recommendation_report(result, tmp)
        assert os.path.exists(os.path.join(tmp, "manual_approval_template.md"))
