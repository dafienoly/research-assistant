"""测试: 因子评分闸门"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.scoring.factor_score import score_factor
from factor_lab.scoring.scoring_policy import _downgrade


def test_downgrade_logic():
    """_downgrade 应返回更严格的等级"""
    assert _downgrade("A", "B") == "B", "A should be downgraded to B"
    assert _downgrade("A", "C") == "C", "A should be downgraded to C"
    assert _downgrade("B", "A") == "B", "B should stay B (A is less strict)"
    assert _downgrade("B", "B") == "B", "B should stay B"
    assert _downgrade("C", "B") == "C", "C should stay C (B is less strict)"


def test_scoring_default_no_reject():
    """无问题的因子基线评分"""
    ao = _make_pass_ao()
    fs = score_factor(ao, family="momentum")
    print(f"Score: {fs['overall_score']:.1f}, Grade: {fs['grade']}, Pass: {fs['pass_gate']}")
    assert fs["overall_score"] >= 50
    assert len(fs.get("reject_reasons", [])) == 0


def test_scoring_reject_not_beats_peer():
    """未跑赢同池等权 → 降级"""
    ao = _make_fail_peer_ao()
    fs = score_factor(ao, family="momentum")
    print(f"Score: {fs['overall_score']:.1f}, Grade: {fs['grade']}")
    assert fs["grade"] in ("C", "D")
    has_peer_reject = any("同池" in r for r in fs["reject_reasons"])
    assert has_peer_reject, "应包含同池等权的淘汰原因"


def test_scoring_max_drawdown_downgrade():
    """回撤过大 → 降级"""
    ao = _make_high_dd_ao()
    fs = score_factor(ao, config={
        "ic_weight": 0.25, "monotonicity_weight": 0.20, "peer_excess_weight": 0.20,
        "risk_control_weight": 0.15, "walk_forward_weight": 0.15, "simplicity_weight": 0.05,
        "max_drawdown_threshold": 20.0,
        "placebo_percentile_threshold": 80,
        "wf_positive_ratio_threshold": 0.5,
    }, family="momentum")
    print(f"Score: {fs['overall_score']:.1f}, Grade: {fs['grade']}")
    assert fs["grade"] != "A"


def test_scoring_placebo_fail_downgrade():
    """Placebo fail → 最高 C"""
    ao = _make_pass_ao()
    ao = _make_fail_placebo_ao()
    fs = score_factor(ao, family="momentum")
    print(f"Score: {fs['overall_score']:.1f}, Grade: {fs['grade']}")
    assert fs["grade"] in ("C", "D")


# ─── 模拟数据 ────────────────────────────────────────────────

def _make_pass_ao() -> dict:
    return {
        "factor_name": "test",
        "ic_stability": {"verdict": "pass", "ic_ir": 0.25, "positive_ic_ratio": 0.58,
                         "ic_mean": 0.03, "ic_std": 0.12},
        "stress_test": {"verdict": "pass", "stability_score": 0.6, "worst_subsample_score": 0.2,
                        "subsamples": [
                            {"label": "sub1", "sharpe": 2.0, "max_drawdown_pct": -10,
                             "cumulative_return_pct": 20, "days": 60, "ic_mean": 0.02,
                             "rank_ic_mean": 0.02, "win_rate_pct": 55},
                        ]},
        "placebo": {"verdict": "pass", "factor_score_percentile": 95, "zscore_vs_placebo": 3.0,
                    "n_trials": 100, "placebo_mean_ic": 0.0, "placebo_std_ic": 0.01,
                    "factor_ic": 0.03, "p_value_like": 0.01},
        "ic_decay": {"verdict": "pass", "half_life_days": 10, "best_horizon": 5,
                     "ic_decay_curve": {"1D": 0.03, "5D": 0.02, "10D": 0.01}},
        "peer_benchmark": {"beats_peer": True, "excess_return_pct": 15.0, "verdict": "pass",
                           "excess_sharpe": 1.5, "strategy_cumulative_pct": 80,
                           "peer_ew_cumulative_pct": 50, "detail": ""},
    }


def _make_fail_peer_ao() -> dict:
    ao = _make_pass_ao()
    ao["peer_benchmark"]["beats_peer"] = False
    ao["peer_benchmark"]["verdict"] = "fail"
    ao["peer_benchmark"]["excess_return_pct"] = -5.0
    return ao


def _make_high_dd_ao() -> dict:
    ao = _make_pass_ao()
    ao["stress_test"]["subsamples"] = [
        {"label": "sub1", "sharpe": 2.0, "max_drawdown_pct": -35,
         "cumulative_return_pct": 20, "days": 60, "ic_mean": 0.02,
         "rank_ic_mean": 0.02, "win_rate_pct": 55},
        {"label": "sub2", "sharpe": 1.5, "max_drawdown_pct": -28,
         "cumulative_return_pct": 15, "days": 50, "ic_mean": 0.01,
         "rank_ic_mean": 0.01, "win_rate_pct": 52},
    ]
    return ao


def _make_fail_placebo_ao() -> dict:
    ao = _make_pass_ao()
    ao["placebo"]["verdict"] = "fail"
    ao["placebo"]["factor_score_percentile"] = 50
    ao["placebo"]["zscore_vs_placebo"] = 0.5
    return ao
