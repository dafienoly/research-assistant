"""测试: 验证报告输出完整性"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path

from factor_lab.reports.validation_report import generate_validation_report


def test_report_generates_all_files():
    """验证报告生成所有预期文件"""
    ao = _sample_ao()
    fs = _sample_fs()
    rv = _sample_rv()
    
    with tempfile.TemporaryDirectory() as tmp:
        result = generate_validation_report(ao, fs, rolling_validation=rv, output_dir=tmp)
        files = result["files"]
        for fname in ["anti_overfit.json", "factor_score.json", "validation_summary.md",
                       "audit.log", "factor_report.html", "rolling_validation.json"]:
            assert fname in files, f"缺少文件: {fname}"


def test_report_json_consistency():
    """JSON 文件内容一致"""
    ao = _sample_ao()
    fs = _sample_fs()
    
    with tempfile.TemporaryDirectory() as tmp:
        result = generate_validation_report(ao, fs, output_dir=tmp)
        out_dir = Path(result["output_dir"])
        
        ao_loaded = json.load(open(out_dir / "anti_overfit.json"))
        assert ao_loaded["factor_name"] == "test_factor"
        assert "ic_stability" in ao_loaded


def test_report_summary_contains_grade():
    """summary.md 包含评分和等级"""
    ao = _sample_ao()
    fs = _sample_fs()
    
    with tempfile.TemporaryDirectory() as tmp:
        result = generate_validation_report(ao, fs, output_dir=tmp)
        md = open(Path(result["output_dir"]) / "validation_summary.md").read()
        assert "A" in md or "B" in md or "C" in md or "D" in md
        assert "评分" in md


def test_audit_log_nonempty():
    """audit.log 非空且有实际内容"""
    ao = _sample_ao()
    fs = _sample_fs()
    
    with tempfile.TemporaryDirectory() as tmp:
        result = generate_validation_report(ao, fs, output_dir=tmp)
        log = open(Path(result["output_dir"]) / "audit.log").read()
        assert len(log) > 50
        assert "AUDIT LOG" in log


# ─── 样本数据 ────────────────────────────────────────────────

def _sample_ao() -> dict:
    return {
        "factor_name": "test_factor",
        "expression": "test expression",
        "overall_verdict": "pass",
        "ic_stability": {"verdict": "pass", "ic_ir": 0.25, "positive_ic_ratio": 0.58,
                         "ic_mean": 0.03, "ic_std": 0.12, "rank_ic_mean": 0.03, "rank_ic_ir": 0.20,
                         "monthly_ic_series": [{"year_month": "2025-01", "ic": 0.03}],
                         "quarterly_ic_series": [{"quarter": "2025Q1", "ic": 0.03}],
                         "detail": ""},
        "stress_test": {"verdict": "pass", "stability_score": 0.6, "worst_subsample_score": 0.2,
                        "subsamples": [{"label": "sub1", "sharpe": 2.0, "max_drawdown_pct": -10,
                                        "cumulative_return_pct": 20, "days": 60, "ic_mean": 0.02,
                                        "rank_ic_mean": 0.02, "win_rate_pct": 55}],
                        "detail": ""},
        "placebo": {"verdict": "pass", "factor_score_percentile": 95, "zscore_vs_placebo": 3.0,
                    "n_trials": 100, "placebo_mean_ic": 0.0, "placebo_std_ic": 0.01,
                    "factor_ic": 0.03, "p_value_like": 0.01, "detail": ""},
        "ic_decay": {"verdict": "pass", "half_life_days": 10, "best_horizon": 5,
                     "ic_decay_curve": {"1D": 0.03, "5D": 0.02, "10D": 0.01},
                     "signal_decay_warning": "", "detail": ""},
        "peer_benchmark": {"beats_peer": True, "excess_return_pct": 15.0, "verdict": "pass",
                           "excess_sharpe": 1.5, "strategy_cumulative_pct": 80,
                           "peer_ew_cumulative_pct": 50, "detail": ""},
        "generated_at": "2025-01-01",
    }


def _sample_fs() -> dict:
    return {
        "factor_name": "test_factor",
        "overall_score": 78.5,
        "grade": "B",
        "pass_gate": True,
        "ic_stability_score": 75.0,
        "monotonicity_score": 70.0,
        "peer_excess_score": 80.0,
        "risk_control_score": 65.0,
        "walk_forward_score": 85.0,
        "simplicity_score": 90.0,
        "reject_reasons": [],
        "improvement_suggestions": [],
        "generated_at": "2025-01-01",
    }


def _sample_rv() -> dict:
    return {
        "factor_name": "test_factor",
        "config": {"train_months": 6, "val_months": 3, "test_months": 3},
        "windows": [{
            "window_name": "w1", "train_sharpe": 2.0, "test_sharpe": 1.5,
            "train_cumulative_return_pct": 30, "val_cumulative_return_pct": 15,
            "test_cumulative_return_pct": 12, "decay_train_to_test": 0.25,
            "train_max_drawdown_pct": -10, "val_max_drawdown_pct": -8,
            "test_max_drawdown_pct": -6, "train_ic_mean": 0.03, "val_ic_mean": 0.02,
            "test_ic_mean": 0.02, "train_days": 120, "val_days": 60, "test_days": 60,
            "train_start": "2025-01-02", "train_end": "2025-06-30",
            "val_start": "2025-07-01", "val_end": "2025-09-30",
            "test_start": "2025-10-01", "test_end": "2025-12-31",
            "train_win_rate_pct": 58, "val_win_rate_pct": 55, "test_win_rate_pct": 52,
            "train_excess_sharpe": 1.2, "val_excess_sharpe": 0.8, "test_excess_sharpe": 0.6,
        }],
        "avg_train_sharpe": 2.0, "avg_val_sharpe": 1.2, "avg_test_sharpe": 1.5,
        "avg_decay": 0.25, "oos_positive_ratio": 1.0, "n_windows": 1,
        "limitation": "limited", "overall_verdict": "pass",
        "avg_train_cumulative_return_pct": 30, "avg_val_cumulative_return_pct": 15,
        "avg_test_cumulative_return_pct": 12,
        "generated_at": "2025-01-01",
    }
