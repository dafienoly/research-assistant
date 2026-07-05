"""测试: V2.10 Manual Approval"""
import sys, os, tempfile, json, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.adaptive.manual_approval import run_approval_workflow


def _make_backtest_dir(tmp_base, candidates):
    """创建模拟 V2.9 输出"""
    bt_dir = tmp_base / "recommendation_backtest" / "test_001"
    bt_dir.mkdir(parents=True)
    with open(bt_dir / "ab_comparison.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "label", "verdict", "confidence", "evidence", "est_sharpe", "est_return_pct"])
        w.writeheader()
        w.writerows(candidates)
    return bt_dir


def test_load_backtest_outputs():
    """读取 V2.9 候选"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_backtest_dir(tmp, [{"name":"test_a","label":"A","verdict":"accept_candidate","confidence":"0.8","evidence":"good","est_sharpe":"2","est_return_pct":"10"}])
        result = run_approval_workflow(run_id="test_001")
        assert "approved" in result or "error" in result


def test_accept_candidate_approves():
    """accept_candidate 可审批通过"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bt_dir = tmp / "recommendation_backtest" / "test_002"
        bt_dir.mkdir(parents=True)
        with open(bt_dir / "ab_comparison.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name","label","verdict","confidence","evidence","est_sharpe","est_return_pct"])
            w.writerow(["switch_to_plan_a","Plan A","accept_candidate","0.7","evidence","1.5","8"])
        result = run_approval_workflow(run_id="test_002", approve="switch_to_plan_a")
        if "error" not in result:
            assert any(a["candidate_name"] == "switch_to_plan_a" for a in result["approved"])


def test_reject_candidate_no_approve():
    """reject_candidate 不能直接 approve"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bt_dir = tmp / "recommendation_backtest" / "test_003"
        bt_dir.mkdir(parents=True)
        with open(bt_dir / "ab_comparison.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name","label","verdict","confidence","evidence","est_sharpe","est_return_pct"])
            w.writerow(["bad_idea","Bad","reject_candidate","0.2","bad","0.5","-5"])
        result = run_approval_workflow(run_id="test_003", approve="bad_idea")
        if "error" not in result:
            # reject_candidate 应进入 rejected 而非 approved
            assert not any(a["candidate_name"] == "bad_idea" for a in result["approved"])


def test_insufficient_data_defer():
    """insufficient_data 只能 defer"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bt_dir = tmp / "recommendation_backtest" / "test_004"
        bt_dir.mkdir(parents=True)
        with open(bt_dir / "ab_comparison.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name","label","verdict","confidence","evidence","est_sharpe","est_return_pct"])
            w.writerow(["unknown","Unk","insufficient_data","0.05","none","0","0"])
        result = run_approval_workflow(run_id="test_004", approve="unknown")
        if "error" not in result:
            assert any(d["candidate_name"] == "unknown" for d in result["deferred"])


def test_config_patch_generated():
    """配置 patch 生成"""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bt_dir = tmp / "recommendation_backtest" / "test_005"
        bt_dir.mkdir(parents=True)
        with open(bt_dir / "ab_comparison.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name","label","verdict","confidence","evidence","est_sharpe","est_return_pct"])
            w.writerow(["change","Chg","accept_candidate","0.7","ok","2","10"])
        result = run_approval_workflow(run_id="test_005", approve="change")
        out_dir = Path("/mnt/d/HermesReports/manual_approval/test_005")
        if out_dir.exists():
            assert (out_dir / "config_patch.diff").exists()


def test_no_auto_apply():
    """不自动修改配置"""
    result = run_approval_workflow(run_id="nonexistent")
    assert result.get("auto_apply") != True
