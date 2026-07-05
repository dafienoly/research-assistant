"""测试: 评分政策配置 + 相对回撤 + 动量阈值"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest

from factor_lab.scoring.scoring_policy import (
    load_policy, get_family_thresholds, get_weights, evaluate_risk, _downgrade
)
from factor_lab.scoring.factor_score import score_factor
from factor_lab.scoring.factor_family import classify_factor


# ─── Scoring Policy Config ────────────────────────────────────

def test_policy_loads():
    policy = load_policy()
    assert "global" in policy
    assert "families" in policy
    assert "momentum" in policy["families"]
    assert "unknown" in policy["families"]


def test_policy_global_defaults():
    """YAML global 配置不为空"""
    policy = load_policy()
    gw = policy["global"]
    assert "default_weights" in gw
    assert "min_total_days" in gw
    assert "hard_fail_on_data_error" in gw


def test_family_thresholds_momentum():
    policy = load_policy()
    t = get_family_thresholds("momentum", policy)
    assert t["max_drawdown_fail"] == 0.65
    assert t["allow_high_beta"] == True
    assert t["min_calmar_for_b"] == 0.8


def test_family_thresholds_unknown():
    policy = load_policy()
    t = get_family_thresholds("non_existent_family", policy)
    assert t["max_drawdown_fail"] == 0.50
    assert t.get("max_grade") is not None


def test_weights_momentum():
    policy = load_policy()
    w = get_weights("momentum", policy)
    assert abs(sum(w.values()) - 1.0) < 0.001
    assert w["risk_control"] == pytest.approx(0.10, abs=0.02)
    assert w["peer_excess"] == pytest.approx(0.25, abs=0.02)


def test_weights_default():
    policy = load_policy()
    w = get_weights("reversal", policy)
    assert abs(sum(w.values()) - 1.0) < 0.001


# ─── Relative Drawdown ────────────────────────────────────────

def test_relative_drawdown_basic():
    policy = load_policy()
    r = evaluate_risk(
        family="momentum",
        strategy_max_dd=-0.30,
        peer_max_dd=-0.15,
        excess_return=15.0,
        sharpe=1.5,
        calmar=1.0,
        beta_vs_hs300=1.2,
        policy=policy,
    )
    assert abs(r["relative_drawdown_vs_peer"] - 2.0) < 0.2
    assert "max_drawdown_verdict" in r
    assert "risk_verdict" in r


def test_relative_drawdown_momentum_pass():
    policy = load_policy()
    r = evaluate_risk("momentum", -0.30, -0.20, 20.0, 2.0, 1.2, 1.2, policy)
    assert r["max_drawdown_verdict"] == "pass"


def test_relative_drawdown_defensive_warn():
    policy = load_policy()
    r = evaluate_risk("defensive", -0.30, -0.20, 5.0, 1.0, 0.5, 0.5, policy)
    assert r["max_drawdown_verdict"] in ("warn", "fail")


# ─── Momentum Drawdown Threshold ──────────────────────────────

def test_momentum_high_dd_allowed():
    """动量族允许 50% 回撤(阈值65%), 但45%警告线已被触发"""
    policy = load_policy()
    r = evaluate_risk("momentum", -0.50, -0.20, 30.0, 2.0, 1.5, 1.5, policy)
    assert r["max_drawdown_verdict"] in ("warn", "pass"), f"动量50%回撤应warn或pass: {r}"


def test_trend_high_dd_allowed():
    """趋势族允许 55% 回撤(阈值70%), 但50%警告线已被触发"""
    policy = load_policy()
    r = evaluate_risk("trend", -0.55, -0.25, 25.0, 1.8, 1.0, 1.3, policy)
    assert r["max_drawdown_verdict"] in ("warn", "pass")


# ─── Hard Gate Tests ──────────────────────────────────────────

def test_hard_gate_peer_underperformance():
    ao = _make_pass_ao("momentum")
    ao["peer_benchmark"]["beats_peer"] = False
    fs = score_factor(ao, family="momentum")
    assert fs["grade"] in ("C", "D")
    assert any("同池" in r for r in fs["reject_reasons"])


def test_hard_gate_placebo_fail():
    ao = _make_pass_ao("momentum")
    ao["placebo"]["verdict"] = "fail"
    ao["placebo"]["factor_score_percentile"] = 50
    fs = score_factor(ao, family="momentum")
    assert fs["grade"] in ("C", "D")


def test_hard_gate_walk_forward_fail():
    ao = _make_pass_ao("momentum")
    rv = {"oos_positive_ratio": 0.2, "overall_verdict": "fail",
          "avg_decay": 0.8, "avg_test_sharpe": 0.1, "limitation": "full"}
    fs = score_factor(ao, rolling_validation=rv, family="momentum")
    assert fs["grade"] in ("C", "D")


# ─── Beta Field ───────────────────────────────────────────────

def test_beta_field_no_ambiguity():
    ao = _make_pass_ao("momentum")
    fs = score_factor(ao, family="momentum")
    assert "beta_vs_hs300" in fs
    if "beta" in fs:
        assert fs["beta"] == fs["beta_vs_hs300"], "beta 不应是歧义字段"


# ─── Downgrade ────────────────────────────────────────────────

def test_downgrade_logic():
    assert _downgrade("A", "B") == "B"
    assert _downgrade("A", "C") == "C"
    assert _downgrade("B", "B") == "B"
    assert _downgrade("C", "A") == "C"


# ─── Helper ───────────────────────────────────────────────────

def _make_pass_ao(family: str = "momentum") -> dict:
    return {
        "factor_name": "test",
        "beta_vs_hs300": 1.2,
        "ic_stability": {"verdict": "pass", "ic_ir": 0.25, "positive_ic_ratio": 0.58,
                         "ic_mean": 0.03, "ic_std": 0.12, "rank_ic_mean": 0.03, "rank_ic_ir": 0.20,
                         "monthly_ic_series": [], "quarterly_ic_series": [], "detail": ""},
        "stress_test": {"verdict": "pass", "stability_score": 0.6, "worst_subsample_score": 0.2,
                        "subsamples": [
                            {"label": "sub1", "sharpe": 2.0, "max_drawdown_pct": -10,
                             "cumulative_return_pct": 20, "days": 60, "ic_mean": 0.02,
                             "rank_ic_mean": 0.02, "win_rate_pct": 55},
                        ], "detail": ""},
        "placebo": {"verdict": "pass", "factor_score_percentile": 95, "zscore_vs_placebo": 3.0,
                    "n_trials": 100, "placebo_mean_ic": 0.0, "placebo_std_ic": 0.01,
                    "factor_ic": 0.03, "p_value_like": 0.01, "detail": ""},
        "ic_decay": {"verdict": "pass", "half_life_days": 10, "best_horizon": 5,
                     "ic_decay_curve": {"1D": 0.03, "5D": 0.02, "10D": 0.01},
                     "signal_decay_warning": "", "detail": ""},
        "peer_benchmark": {"beats_peer": True, "excess_return_pct": 15.0, "verdict": "pass",
                           "excess_sharpe": 1.5, "strategy_cumulative_pct": 80,
                           "peer_ew_cumulative_pct": 50, "detail": "",
                           "beta_vs_hs300": 1.2},
    }
