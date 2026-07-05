"""因子评分系统 — V1.4 因子类型感知评分

权重:
  - IC 稳定性:     25% (可被家族覆写)
  - 分组单调性:    20%
  - 同池等权超额:  20% (动量/趋势可调到25%)
  - 回撤与风控:    15% (动量/趋势可降到10%)
  - Walk-Forward:  15%
  - 简洁/可解释:    5%

硬性降级(全局, 不被家族覆写):
  - 未跑赢同池等权 → 最高 C
  - Walk-Forward 样本外为负 → 最高 C
  - Placebo 不显著 → 最高 C
  - IC 稳定性 fail → 最高 B
  - unknown 家族 → 最高 B
  - 数据不足/失败 → 不能 A/B

家族感知的回撤评分:
  - absolute_max_drawdown vs 家族 fail 阈值
  - relative_drawdown_vs_peer vs 家族阈值
  - 动量/趋势允许更高回撤, 但要求更高超额收益
"""
import sys, os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np

CST = timezone(timedelta(hours=8))


def score_factor(
    anti_overfit: dict,
    rolling_validation: Optional[dict] = None,
    expression: str = "",
    family: str = "unknown",
    config: Optional[dict] = None,
) -> dict:
    """因子评分主入口 (V1.4 家族感知)

    参数:
        anti_overfit: anti_overfit.py 输出
        rolling_validation: rolling_validator.py 输出 (可选)
        expression: 因子表达式
        family: 因子家族 (momentum/reversal/trend/volume_price/volatility/defensive/value_quality/unknown)
        config: 覆盖配置
    """
    from factor_lab.scoring.scoring_policy import load_policy, get_family_thresholds, get_weights, evaluate_risk

    policy = load_policy()
    thresholds = get_family_thresholds(family, policy)
    weights = get_weights(family, policy)

    reject_reasons = []
    suggestions = []

    # ── 1. IC 稳定性评分 ──
    ic = anti_overfit.get("ic_stability", {})
    ic_score = _score_ic_stability(ic)
    if ic.get("verdict") == "fail":
        reject_reasons.append(f"IC 稳定性不足: {ic.get('detail', '')}")

    # ── 2. 分组单调性评分 ──
    stress = anti_overfit.get("stress_test", {})
    mono_score = _score_monotonicity(stress)
    if stress.get("verdict") == "fail":
        reject_reasons.append(f"子样本压力测试未通过: {stress.get('detail', '')}")

    # ── 3. 同池等权超额评分 ──
    peer = anti_overfit.get("peer_benchmark", {})
    peer_score = _score_peer_excess(peer, thresholds)
    if not peer.get("beats_peer", False):
        reject_reasons.append("未跑赢同池等权基准 — 硬性降级到 C")
        suggestions.append("考虑加强因子与同池的差异化, 如叠加成交量条件或质量过滤")

    # ── 4. 回撤与风险评分 (家族感知) ──
    worst_dd = _get_worst_drawdown(anti_overfit)
    peer_dd = _get_peer_max_drawdown(anti_overfit) or abs(worst_dd)
    excess_return = peer.get("excess_return_pct", 0)
    sharpe_val = peer.get("excess_sharpe", 0)
    calmar_val = _get_calmar(anti_overfit)
    beta_hs300 = anti_overfit.get("beta_vs_hs300", 0) or peer.get("beta_vs_hs300", 0)

    risk_eval = evaluate_risk(
        family=family,
        strategy_max_dd=(worst_dd or 0) / 100,
        peer_max_dd=peer_dd / 100,
        excess_return=excess_return,
        sharpe=sharpe_val,
        calmar=calmar_val,
        beta_vs_hs300=beta_hs300,
        policy=policy,
    )
    risk_score = _score_risk_from_eval(risk_eval, family)

    # 家族感知的硬性降级: 回撤
    if risk_eval.get("max_drawdown_verdict") == "fail":
        reject_reasons.append(
            f"最大回撤{abs(worst_dd):.1f}%超过{family}家族阈值{thresholds['max_drawdown_fail']*100:.0f}%"
        )
    if risk_eval.get("relative_drawdown_verdict") == "fail":
        reject_reasons.append(
            f"相对同池等权回撤{risk_eval['relative_drawdown_vs_peer']:.2f}倍超过{family}阈值{thresholds['max_relative_drawdown_vs_peer']:.2f}倍"
        )

    # ── 5. Walk-Forward 评分 ──
    wf_score = _score_walk_forward(rolling_validation)
    if rolling_validation:
        wf_verdict = rolling_validation.get("overall_verdict", "fail")
        if wf_verdict == "fail":
            reject_reasons.append("Walk-Forward 样本外验证未通过")
            suggestions.append("因子可能在样本内过拟合, 尝试简化或增加惩罚项")
        oos_pos = rolling_validation.get("oos_positive_ratio", 0)
        if oos_pos < policy.get("global", {}).get("wf_positive_ratio_threshold", 0.5):
            reject_reasons.append("Walk-Forward 样本外半数窗口为负")

    # ── 6. 简洁性评分 ──
    sim_score = _score_simplicity(expression)
    if expression and len(expression) > 100:
        suggestions.append(f"表达式过长({len(expression)}字符), 建议简化")

    # ── 综合计算 ──
    raw_score = (
        ic_score * weights["ic_stability"]
        + mono_score * weights["monotonicity"]
        + peer_score * weights["peer_excess"]
        + risk_score * weights["risk_control"]
        + wf_score * weights["walk_forward"]
        + sim_score * weights["simplicity"]
    )
    score = min(max(raw_score, 0), 100)

    # ── 硬性降级 ──
    grade, pass_gate = _apply_hard_rules(
        score, reject_reasons, anti_overfit, rolling_validation,
        policy, family, thresholds, worst_dd, risk_eval,
    )

    # ── 完善建议 ──
    if score < 60:
        suggestions.append("因子整体较弱, 建议从更简单的表达式重新开始")
    if ic_score < 50:
        suggestions.append("IC 不稳定, 尝试改变因子窗口或引入非线性变换")
    if wf_score < 50 and rolling_validation:
        suggestions.append("Walk-Forward 提示过拟合, 减少参数或使用更短的训练窗口")
    if risk_eval.get("max_drawdown_verdict") == "warn":
        suggestions.append(f"回撤接近{family}警告线, 考虑叠加止损或降低权重")

    return {
        "factor_name": anti_overfit.get("factor_name", ""),
        "factor_family": family,
        "overall_score": round(score, 1),
        "grade": grade,
        "pass_gate": pass_gate,
        "ic_stability_score": round(ic_score, 1),
        "ic_weight": weights["ic_stability"],
        "monotonicity_score": round(mono_score, 1),
        "monotonicity_weight": weights["monotonicity"],
        "peer_excess_score": round(peer_score, 1),
        "peer_excess_weight": weights["peer_excess"],
        "risk_control_score": round(risk_score, 1),
        "risk_control_weight": weights["risk_control"],
        "walk_forward_score": round(wf_score, 1),
        "walk_forward_weight": weights["walk_forward"],
        "simplicity_score": round(sim_score, 1),
        "simplicity_weight": weights["simplicity"],
        # 回撤指标
        "absolute_max_drawdown": round(abs(worst_dd), 2) if worst_dd else None,
        "peer_max_drawdown": round(peer_dd, 2),
        "relative_drawdown_vs_peer": round(risk_eval.get("relative_drawdown_vs_peer", 0), 4),
        "excess_return_vs_peer": round(excess_return, 2),
        "calmar": round(calmar_val, 4),
        "return_drawdown_efficiency": round(risk_eval.get("return_drawdown_efficiency", 0), 4),
        "beta_vs_hs300": round(beta_hs300, 4),
        # 风险判定
        "max_drawdown_verdict": risk_eval.get("max_drawdown_verdict", "unknown"),
        "relative_drawdown_verdict": risk_eval.get("relative_drawdown_verdict", "unknown"),
        "risk_verdict": risk_eval.get("risk_verdict", "unknown"),
        # 原字段
        "reject_reasons": reject_reasons,
        "improvement_suggestions": suggestions,
        "generated_at": datetime.now(CST).isoformat(),
    }


# ─── 各维度评分函数 ───────────────────────────────────────────

def _score_ic_stability(ic: dict) -> float:
    """IC 稳定性评分 0-100"""
    ic_ir = abs(ic.get("ic_ir", 0))
    pos_ratio = ic.get("positive_ic_ratio", 0)

    if ic_ir > 0.3:
        ir_score = 90
    elif ic_ir > 0.2:
        ir_score = 75
    elif ic_ir > 0.15:
        ir_score = 60
    elif ic_ir > 0.10:
        ir_score = 45
    elif ic_ir > 0.05:
        ir_score = 30
    else:
        ir_score = 10

    pos_bonus = min(pos_ratio * 40, 30)
    if pos_ratio < 0.5:
        pos_bonus = -20

    return max(min(ir_score + pos_bonus, 100), 0)


def _score_monotonicity(stress: dict) -> float:
    """分组单调性 0-100"""
    stability = stress.get("stability_score", 0)
    worst = stress.get("worst_subsample_score", 0)
    base = stability * 80
    worst_penalty = max(0, -worst * 30)
    return max(min(base - worst_penalty, 100), 10)


def _score_peer_excess(peer: dict, thresholds: dict) -> float:
    """同池等权超额评分 0-100 (家族感知)"""
    if not peer.get("beats_peer", False):
        return 20
    excess = peer.get("excess_return_pct", 0)
    min_for_b = thresholds.get("min_excess_return_vs_peer_for_b", 0.03) * 100

    if excess > 20:
        return 90
    elif excess > max(10, min_for_b * 2):
        return 75
    elif excess > max(5, min_for_b):
        return 65
    elif excess > 0:
        return 55
    return 20


def _score_risk_from_eval(risk_eval: dict, family: str) -> float:
    """从 risk_eval 计算风险评分 0-100"""
    dd_verdict = risk_eval.get("max_drawdown_verdict", "warn")
    rel_verdict = risk_eval.get("relative_drawdown_verdict", "warn")
    efficiency = risk_eval.get("return_drawdown_efficiency", 0)

    base = 50
    if dd_verdict == "pass":
        base += 20
    elif dd_verdict == "fail":
        base -= 25

    if rel_verdict == "pass":
        base += 15
    elif rel_verdict == "fail":
        base -= 20

    # 收益/回撤效率加分
    base += min(efficiency * 50, 20)

    return max(min(base, 100), 0)


def _get_peer_max_drawdown(anti_overfit: dict) -> Optional[float]:
    """获取同池等权的最大回撤（从 subsample 推算）"""
    stress = anti_overfit.get("stress_test", {})
    # 尝试从 peer benchmark 直接获取
    peer = anti_overfit.get("peer_benchmark", {})
    # 用 "peer_ew_cumulative_pct" 推算
    ew_cum = peer.get("peer_ew_cumulative_pct", 0)
    if ew_cum and ew_cum > 0:
        # 保守估算: 假设等权回撤约为收益的 30-50%
        return abs(ew_cum) * 0.4
    return None


def _get_calmar(anti_overfit: dict) -> float:
    """获取 Calmar Ratio (年化/最大回撤)"""
    peer = anti_overfit.get("peer_benchmark", {})
    cum = peer.get("strategy_cumulative_pct", 0)
    worst_dd = _get_worst_drawdown(anti_overfit)
    if worst_dd and abs(worst_dd) > 0 and cum > 0:
        years = 1.5  # 约 18 个月
        cagr = (1 + cum / 100) ** (1 / years) - 1
        return cagr / (abs(worst_dd) / 100)
    return 0.0


def _score_walk_forward(wf: Optional[dict]) -> float:
    """Walk-Forward 评分 0-100"""
    if wf is None:
        return 40
    oos_pos = wf.get("oos_positive_ratio", 0)
    avg_decay = wf.get("avg_decay", 0)
    avg_test_sharpe = wf.get("avg_test_sharpe", 0)
    base = oos_pos * 50
    decay_score = max(0, (1 - avg_decay) * 30)
    sharpe_score = min(max(avg_test_sharpe * 10, 0), 20)
    return min(base + decay_score + sharpe_score, 100)


def _score_simplicity(expression: str) -> float:
    """简洁性评分 0-100"""
    if not expression or expression == "":
        return 50
    n = len(expression)
    if n < 30:
        return 95
    elif n < 60:
        return 80
    elif n < 100:
        return 60
    elif n < 150:
        return 40
    else:
        return 20


def _get_worst_drawdown(anti_overfit: dict) -> Optional[float]:
    """获取所有子样本中的最大回撤"""
    stress = anti_overfit.get("stress_test", {})
    subs = stress.get("subsamples", [])
    dds = [s.get("max_drawdown_pct", 0) for s in subs if s.get("max_drawdown_pct", 0) < 0]
    return min(dds) if dds else None


def _apply_hard_rules(
    score: float,
    reject_reasons: list,
    anti_overfit: dict,
    rolling_validation: Optional[dict],
    policy: dict,
    family: str,
    thresholds: dict,
    worst_dd: Optional[float],
    risk_eval: dict,
) -> (str, bool):
    """硬性降级规则 (全局, 不被家族覆写)"""
    from factor_lab.scoring.scoring_policy import _downgrade

    max_grade = "A"

    # 规则1: 未跑赢同池等权 → 最高 C
    peer = anti_overfit.get("peer_benchmark", {})
    if not peer.get("beats_peer", False):
        max_grade = _downgrade(max_grade, "C")

    # 规则2: Walk-Forward 样本外为负 → 最高 C
    if rolling_validation:
        oos_pos = rolling_validation.get("oos_positive_ratio", 0)
        wf_threshold = policy.get("global", {}).get("wf_positive_ratio_threshold", 0.5)
        if oos_pos < wf_threshold:
            max_grade = _downgrade(max_grade, "C")
        if rolling_validation.get("limitation") == "insufficient_data":
            max_grade = _downgrade(max_grade, "B")

    # 规则3: Placebo 不显著 → 最高 C
    placebo = anti_overfit.get("placebo", {})
    if placebo.get("verdict") == "fail":
        max_grade = _downgrade(max_grade, "C")
    perc_threshold = policy.get("global", {}).get("placebo_percentile_threshold", 80)
    if placebo.get("factor_score_percentile", 0) < perc_threshold:
        max_grade = _downgrade(max_grade, "C")

    # 规则4: 最大回撤超过家族 fail 阈值 → 最高 B
    dd_fail = thresholds.get("max_drawdown_fail", 0.50)
    if worst_dd is not None and abs(worst_dd) / 100 > dd_fail:
        max_grade = _downgrade(max_grade, "B")

    # 规则5: 相对回撤超过家族阈值 → 最高 B
    rel_threshold = thresholds.get("max_relative_drawdown_vs_peer", 1.20)
    rel_dd = risk_eval.get("relative_drawdown_vs_peer", 0)
    if rel_dd > rel_threshold:
        max_grade = _downgrade(max_grade, "B")

    # 规则6: IC 稳定性 fail → 最高 B
    ic = anti_overfit.get("ic_stability", {})
    if ic.get("verdict") == "fail":
        max_grade = _downgrade(max_grade, "B")

    # 规则7: unknown 家族 → 最高 B
    if family == "unknown":
        max_grade = _downgrade(max_grade, "B")

    # 规则8: unknown 家族的 max_grade
    fam_max = thresholds.get("max_grade", "")
    if fam_max in ("A", "B", "C", "D"):
        max_grade = _downgrade(max_grade, fam_max)

    # 确定最终等级
    if score >= 80:
        final_grade = "A"
    elif score >= 60:
        final_grade = "B"
    elif score >= 40:
        final_grade = "C"
    else:
        final_grade = "D"

    final_grade = _downgrade(final_grade, max_grade)
    pass_gate = final_grade in ("A", "B")
    return final_grade, pass_gate
