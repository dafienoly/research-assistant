"""Trajectory Analyzer — 因子迭代轨迹质量分析

从迭代历史计算轨迹级质量指标：
  - exploration_diversity: 探索多样性（分数变异系数）
  - convergence_rate: 收敛速率（分数趋势斜率）
  - stability_score: 稳定性（分数波动逆归一化）
  - consecutive_declines: 连续下降次数

基于 QuantGPT trajectory_analyzer.py (XTQuant QuantaAlpha) 移植。
"""

import numpy as np
from dataclasses import dataclass, field


@dataclass
class TrajectoryMetrics:
    """轨迹质量指标"""
    exploration_diversity: float = 0.0   # 0-1, 高=探索丰富
    convergence_rate: float = 0.0        # 0-1, 正=在改善
    stability_score: float = 0.0         # 0-1, 高=稳定
    consecutive_declines: int = 0        # 连续下降次数
    best_score: float = 0.0
    best_expression: str = ""
    num_iterations: int = 0
    recent_improvement: float = 0.0      # 最近 3 轮平均提升


def analyze_trajectory(iterations: list[dict]) -> TrajectoryMetrics:
    """从迭代历史计算轨迹质量指标

    Args:
        iterations: 按时间顺序的 {expression, score, ...} 列表

    Returns:
        TrajectoryMetrics
    """
    if not iterations:
        return TrajectoryMetrics()

    scores = []
    for it in iterations:
        s = it.get("score", 0)
        if s is None:
            s = 0
        scores.append(float(s))

    n = len(scores)
    scores_arr = np.array(scores)

    # Best
    best_idx = int(np.argmax(scores_arr))
    best_score = float(scores_arr[best_idx])
    best_expression = iterations[best_idx].get("expression", "")

    # Exploration diversity: coefficient of variation
    mean_score = float(np.mean(scores_arr))
    if n >= 2 and mean_score > 0:
        exploration_diversity = min(float(np.std(scores_arr) / mean_score), 1.0)
    else:
        exploration_diversity = 0.0

    # Convergence rate: normalized linear regression slope
    if n >= 2:
        x = np.arange(n, dtype=float)
        slope = float(np.polyfit(x, scores_arr, 1)[0])
        convergence_rate = max(0.0, min(slope / 10.0, 1.0))
    else:
        convergence_rate = 0.0

    # Stability: inverse of normalized volatility
    if n >= 2 and best_score > 0:
        volatility = float(np.std(scores_arr)) / best_score
        stability_score = max(0.0, 1.0 - volatility)
    else:
        stability_score = 1.0

    # Consecutive declines from the end
    consecutive_declines = 0
    for i in range(n - 1, 0, -1):
        if scores[i] < scores[i - 1]:
            consecutive_declines += 1
        else:
            break

    # Recent improvement (last 3 rounds)
    if n >= 4:
        recent = np.mean(scores_arr[-3:])
        older = np.mean(scores_arr[:-3])
        recent_improvement = float(recent - older) / (abs(older) + 1e-10)
    else:
        recent_improvement = 0.0

    return TrajectoryMetrics(
        exploration_diversity=round(float(exploration_diversity), 3),
        convergence_rate=round(float(convergence_rate), 3),
        stability_score=round(float(stability_score), 3),
        consecutive_declines=int(consecutive_declines),
        best_score=round(float(best_score), 2),
        best_expression=best_expression,
        num_iterations=int(n),
        recent_improvement=round(float(recent_improvement), 4),
    )
