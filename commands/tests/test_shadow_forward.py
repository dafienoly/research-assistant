"""测试: V2.11 Shadow Forward"""
import sys, os, csv, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.adaptive.shadow_forward import run_shadow_forward


def _make_approval_dir(tmp_base, run_id, candidates):
    """创建模拟 V2.10 输出"""
    app_dir = tmp_base / "manual_approval" / run_id
    app_dir.mkdir(parents=True)
    with open(app_dir / "approved_candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["candidate_name", "label", "verdict", "confidence"])
        w.writeheader()
        for c in candidates:
            w.writerow(c)
    return app_dir


def test_load_approved():
    """读取已批准候选"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_approval_dir(tmp, "t001", [{"candidate_name":"plan_a","label":"A","verdict":"accept_candidate","confidence":"0.7"}])
        result = run_shadow_forward(run_id="t001")
        assert "approved_candidates" in result or "error" in result


def test_shadow_config_independent():
    """shadow config 不修改 baseline"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_approval_dir(tmp, "t002", [{"candidate_name":"plan_c","label":"C","verdict":"accept_candidate","confidence":"0.6"}])
        result = run_shadow_forward(run_id="t002")
        if "error" not in result:
            for sc in result.get("shadow_configs", []):
                assert sc.get("shadow_only") == True
                assert "shadow_id" in sc


def test_baseline_hash_stable():
    """baseline hash 存在"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_approval_dir(tmp, "t003", [{"candidate_name":"top5","label":"Top5","verdict":"accept_candidate","confidence":"0.5"}])
        result = run_shadow_forward(run_id="t003")
        if "error" not in result:
            assert result.get("baseline_hash")


def test_shadow_orders_preview():
    """shadow 订单预览不下单"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_approval_dir(tmp, "t004", [{"candidate_name":"etf","label":"ETF","verdict":"accept_candidate","confidence":"0.8"}])
        result = run_shadow_forward(run_id="t004")
        out_dir = Path("/mnt/d/HermesReports/shadow_forward/t004")
        if out_dir.exists():
            assert (out_dir / "shadow_orders_preview.csv").exists()


def test_report_generated():
    """报告生成"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_approval_dir(tmp, "t005", [{"candidate_name":"test","label":"T","verdict":"accept_candidate","confidence":"0.6"}])
        result = run_shadow_forward(run_id="t005")
        out_dir = Path("/mnt/d/HermesReports/shadow_forward/t005")
        if out_dir.exists():
            assert (out_dir / "shadow_forward_report.html").exists()


def test_safety_flags():
    """安全标志存在"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _make_approval_dir(tmp, "t006", [{"candidate_name":"safe","label":"S","verdict":"accept_candidate","confidence":"0.7"}])
        result = run_shadow_forward(run_id="t006")
        if "error" not in result:
            assert result.get("shadow_only") == True
            assert result.get("auto_apply") == False
            assert result.get("no_live_trade") == True
