"""Meta-Evolution Strategy Selector — 自适应进化策略选择

基于轨迹特征动态切换策略:
  - EXPLOIT:    精调当前最优（高分 + 低多样性）
  - EXPLORE:    全新方向探索（低分 + 早期 / 高散度 + 低收敛）
  - RECOMBINE:  历史高分交叉重组（平台期 / 差距过大）
  - SIMPLIFY:   降低复杂度（嵌套过深）

基于 QuantGPT meta_evolution.py (XTQuant QuantaAlpha) 移植。
"""

from enum import Enum
from factor_lab.research_loop.trajectory import TrajectoryMetrics


class EvolutionStrategy(Enum):
    EXPLOIT = "exploit"        # 定向突变精调
    EXPLORE = "explore"        # 全新方向探索
    RECOMBINE = "recombine"    # 历史高分交叉重组
    SIMPLIFY = "simplify"      # 降低复杂度


def select_strategy(
    metrics: TrajectoryMetrics,
    current_score: float,
    nesting_depth: int = 0,
) -> EvolutionStrategy:
    """基于轨迹特征选择进化策略

    决策树（按优先级）:
    1. 嵌套过深 → SIMPLIFY
    2. 高分 + 低多样性 → EXPLOIT
    3. 平台期 + 多轮 → RECOMBINE
    4. 低分 + 早期 → EXPLORE
    5. 高散度 + 低收敛 → EXPLORE
    6. 中分 + 稳定 → EXPLOIT
    7. 当前与 best 差距大 → RECOMBINE
    8. 默认 → EXPLOIT
    """
    n = metrics.num_iterations
    diversity = metrics.exploration_diversity
    convergence = metrics.convergence_rate
    stability = metrics.stability_score
    declines = metrics.consecutive_declines

    # 1. 嵌套过深 → SIMPLIFY
    if nesting_depth > 8:
        return EvolutionStrategy.SIMPLIFY

    # 2. 高分 + 低多样性 → 精调
    if current_score >= 60 and diversity < 0.3:
        return EvolutionStrategy.EXPLOIT

    # 3. 平台期 → 交叉重组
    if declines >= 2 and n >= 3:
        return EvolutionStrategy.RECOMBINE

    # 4. 低分 + 早期 → 探索新方向
    if current_score < 30 and n <= 3:
        return EvolutionStrategy.EXPLORE

    # 5. 高散度 + 低收敛 → 探索
    if diversity > 0.6 and convergence < 0.4:
        return EvolutionStrategy.EXPLORE

    # 6. 中分 + 稳定 → 精调
    if 30 <= current_score < 60 and stability > 0.6:
        return EvolutionStrategy.EXPLOIT

    # 7. 当前与 best 差距大 → 重组
    if metrics.best_score - current_score > 20 and n >= 2:
        return EvolutionStrategy.RECOMBINE

    # 默认
    return EvolutionStrategy.EXPLOIT
