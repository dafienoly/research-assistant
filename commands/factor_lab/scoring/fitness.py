"""Fitness Scoring — WQ BRAIN 兼容的 fitness 公式 + Cloud Alignment

增强现有 factor_score.py，补充:
1. WQ BRAIN Fitness: Sharpe × √(|Returns| / max(Turnover, 0.125))
2. Cloud Alignment Score: IC Mean + IC IR + Turnover + Data Sufficiency → 预测能否通过 Cloud 验证
3. 综合评分（合并现有 score_factor + adversarial + fitness）

用法:
  from factor_lab.scoring.fitness import compute_fitness, compute_cloud_alignment, enhanced_score
  fitness = compute_fitness(sharpe=1.2, returns=0.08, turnover=0.15)
  cloud = compute_cloud_alignment(ic_mean=0.03, ic_ir=0.3, turnover=0.15)
"""

import math


def compute_fitness(
    sharpe: float = 0.0,
    returns: float = 0.0,       # 年化收益率（小数）
    turnover: float = 0.0,      # 换手率（小数）
    min_turnover: float = 0.125,
) -> float:
    """WQ BRAIN 兼容的 Fitness 公式

    Fitness = Sharpe × √(|Returns| / max(Turnover, min_turnover))

    WQ BRAIN A-Rating 阈值 (CN D1 Quintile):
      - Sharpe ≥ 1.625
      - |Returns| ≥ 6.3%
      - Fitness ≥ 1.0
      - Turnover 1% – 70%
      - Sub-Universe Sharpe: Both halves ≥ 1.19
    """
    adj_turnover = max(turnover, min_turnover)
    if adj_turnover <= 0:
        return 0.0
    return sharpe * math.sqrt(abs(returns) / adj_turnover)


def compute_cloud_alignment(
    ic_mean: float = 0.0,
    ic_ir: float = 0.0,
    turnover: float = 0.0,
    data_days: int = 120,
) -> dict:
    """Cloud Alignment 评分 — 预测因子能否通过 Cloud 独立验证

    6 分量评分:
      - IC Mean 15%
      - IC IR 15%
      - Stability (IC win rate + LS Sharpe) 15%
      - Anti-Overfit 15%
      - Group Backtest 15%
      - Cloud Alignment 25% (IC Mean + IC IR + Turnover + Data Days)

    Returns:
        {score, grade, cloud_predicted_pass, component_scores, fitness}
    """
    # IC Mean score
    ic_mean_abs = abs(ic_mean)
    ic_mean_score = min(ic_mean_abs / 0.05, 1.0) * 100

    # IC IR score
    ic_ir_abs = abs(ic_ir)
    ic_ir_score = min(ic_ir_abs / 1.0, 1.0) * 100

    # Turnover score (WQ optimal: 1%-35%)
    if 0.01 <= turnover <= 0.35:
        turnover_score = 100.0
    elif turnover > 0.35:
        turnover_score = max(0.0, 100.0 - (turnover - 0.35) / 0.35 * 100)
    else:
        turnover_score = 0.0

    # Data sufficiency score
    data_score = min(data_days / 120, 1.0) * 100

    # Cloud alignment composite (weights: IC Mean 30%, IC IR 30%, Turnover 20%, Data 20%)
    cloud_score = (
        ic_mean_score * 0.30 + ic_ir_score * 0.30
        + turnover_score * 0.20 + data_score * 0.20
    )

    # Cloud pass prediction
    cloud_predicted_pass = (
        ic_mean_abs >= 0.015
        and ic_ir_abs >= 0.15
        and turnover <= 0.35
        and data_days >= 120
    )

    # WQ A-Rating thresholds check
    wq_a_rating_possible = (
        ic_mean_abs >= 0.015       # proxies for Sharpe ≥ 1.625
        and ic_ir_abs >= 0.3       # high IR
        and 0.01 <= turnover <= 0.70
    )

    return {
        "cloud_alignment_score": round(cloud_score, 1),
        "cloud_predicted_pass": cloud_predicted_pass,
        "wq_a_rating_possible": wq_a_rating_possible,
        "component_scores": {
            "ic_mean": round(ic_mean_score, 1),
            "ic_ir": round(ic_ir_score, 1),
            "turnover": round(turnover_score, 1),
            "data_sufficiency": round(data_score, 1),
        },
    }


def enhanced_score(
    existing_score_result: dict = None,
    adversarial_result: dict = None,
    sharpe: float = 0.0,
    returns: float = 0.0,
    turnover: float = 0.0,
    ic_mean: float = 0.0,
    ic_ir: float = 0.0,
    data_days: int = 120,
) -> dict:
    """综合评分：合并现有 score_factor + adversarial + fitness + cloud

    返回包含完整评分信息的 dict。
    """
    result = dict(existing_score_result or {})

    # WQ BRAIN Fitness
    fitness = compute_fitness(sharpe=sharpe, returns=returns, turnover=turnover)
    result["wq_fitness"] = round(fitness, 4)

    # Cloud Alignment
    cloud = compute_cloud_alignment(
        ic_mean=ic_mean, ic_ir=ic_ir,
        turnover=turnover, data_days=data_days,
    )
    result.update(cloud)

    # Adversarial validation
    if adversarial_result:
        result["adversarial_score"] = adversarial_result.get("score", 0)
        result["adversarial_recommendation"] = adversarial_result.get("recommendation", "")
        result["adversarial_passed"] = adversarial_result.get("passed_count", 0)
        result["adversarial_total"] = adversarial_result.get("total_count", 4)
        result["adversarial_tests"] = adversarial_result.get("tests", [])

    # Enhanced WQ-grade (override existing grade if fitness suggests A)
    existing_grade = result.get("grade", "D")
    if fitness >= 1.0 and cloud.get("cloud_predicted_pass"):
        result["wq_grade"] = "A"
    elif fitness >= 0.5:
        result["wq_grade"] = "B"
    else:
        result["wq_grade"] = existing_grade

    return result
