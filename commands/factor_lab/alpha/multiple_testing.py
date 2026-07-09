"""V4.6 多重检验惩罚 — Bonferroni 校正及更通用的 FDR 控制

当同时检验 m 个因子时，传统的显著性阈值 alpha 不再适用：
  - 单次检验阈值 0.05，但 20 个因子同时检验至少有一个假阳性的概率 = 1 - (1-0.05)^20 ≈ 64%

本模块提供：
  1. Bonferroni 校正: alpha_adj = alpha / m（最保守，控制 FWER）
  2. Holm-Bonferroni 校正: 逐步拒绝，比 Bonferroni 稍宽松
  3. Benjamini-Hochberg FDR 控制: 控制错误发现率

用法:
    from factor_lab.alpha.multiple_testing import (
        bonferroni_adjust,
        holm_bonferroni_adjust,
        benjamini_hochberg_adjust,
        adjust_significance_threshold,
        MultipleTestCorrector,
    )
"""

import math
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class CorrectionResult:
    """多重检验校正结果"""
    method: str = ""
    n_tests: int = 0
    alpha_original: float = 0.05
    alpha_adjusted: float = 0.05
    p_values_adjusted: list = field(default_factory=list)
    rejected_indices: list = field(default_factory=list)
    summary: str = ""


# ═══════════════════════════════════════════════════════════════════
# 核心校正函数
# ═══════════════════════════════════════════════════════════════════


def bonferroni_adjust(
    p_values: list[float],
    alpha: float = 0.05,
) -> CorrectionResult:
    """Bonferroni 校正: alpha_adj = alpha / m

    最保守的多重检验校正。控制 Family-Wise Error Rate (FWER)。

    Args:
        p_values: 原始 p 值列表
        alpha: 原始显著性水平 (默认 0.05)

    Returns:
        CorrectionResult
    """
    m = len(p_values)
    if m == 0:
        return CorrectionResult(method="bonferroni", n_tests=0, alpha_original=alpha)

    alpha_adj = alpha / m
    adjusted = [min(p * m, 1.0) for p in p_values]
    rejected = [i for i, p in enumerate(p_values) if p <= alpha_adj]

    return CorrectionResult(
        method="bonferroni",
        n_tests=m,
        alpha_original=alpha,
        alpha_adjusted=alpha_adj,
        p_values_adjusted=adjusted,
        rejected_indices=rejected,
        summary=f"Bonferroni: alpha={alpha} / m={m} = {alpha_adj:.6f}, "
                f"拒绝 {len(rejected)}/{m} 个零假设",
    )


def holm_bonferroni_adjust(
    p_values: list[float],
    alpha: float = 0.05,
) -> CorrectionResult:
    """Holm-Bonferroni 逐步校正

    比 Bonferroni 更 powerful（更多拒绝），但仍控制 FWER。

    步骤:
      1. 对 p 值升序排列: p(1) <= p(2) <= ... <= p(m)
      2. 从 k=1 开始，找到最小的 k 满足 p(k) > alpha / (m - k + 1)
      3. 拒绝所有 p(j) < p(k)

    Args:
        p_values: 原始 p 值列表
        alpha: 原始显著性水平 (默认 0.05)

    Returns:
        CorrectionResult
    """
    m = len(p_values)
    if m == 0:
        return CorrectionResult(method="holm_bonferroni", n_tests=0, alpha_original=alpha)

    # 排序并保留原始索引
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    rejected_indices = []
    adjusted = [0.0] * m

    for k, (orig_idx, p) in enumerate(indexed, 1):
        threshold = alpha / (m - k + 1)
        adj_p = p * (m - k + 1)
        adjusted[orig_idx] = min(adj_p, 1.0)
        if p <= threshold:
            rejected_indices.append(orig_idx)
        else:
            # 一旦一个未拒绝，后续都不拒绝 (Holm 的单调性)
            for j in range(k, m + 1):
                _, p_rest = indexed[j - 1]
                adjusted[orig_idx] = min(p_rest * (m - (j - 1) + 1), 1.0)
            break

    return CorrectionResult(
        method="holm_bonferroni",
        n_tests=m,
        alpha_original=alpha,
        alpha_adjusted=alpha / m,  # 最严格的阈值（第一步）
        p_values_adjusted=adjusted,
        rejected_indices=rejected_indices,
        summary=f"Holm-Bonferroni: m={m}, alpha={alpha}, "
                f"拒绝 {len(rejected_indices)}/{m} 个零假设",
    )


def benjamini_hochberg_adjust(
    p_values: list[float],
    alpha: float = 0.05,
) -> CorrectionResult:
    """Benjamini-Hochberg FDR 控制

    控制 False Discovery Rate (FDR) 而非 FWER。
    比 Bonferroni 更宽松，适合因子筛选场景。

    步骤:
      1. p 值升序排列: p(1) <= p(2) <= ... <= p(m)
      2. 找到最大的 k 满足 p(k) <= alpha * k / m
      3. 拒绝所有 p(j) <= p(k)

    Args:
        p_values: 原始 p 值列表
        alpha: FDR 水平 (默认 0.05)

    Returns:
        CorrectionResult
    """
    m = len(p_values)
    if m == 0:
        return CorrectionResult(method="benjamini_hochberg", n_tests=0, alpha_original=alpha)

    # 排序
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    rejected_indices = []
    max_reject_k = 0
    adjusted = [0.0] * m

    for k, (orig_idx, p) in enumerate(indexed, 1):
        threshold = alpha * k / m
        adj_p = p * m / k
        adjusted[orig_idx] = min(adj_p, 1.0)
        if p <= threshold:
            max_reject_k = k
            rejected_indices.append(orig_idx)

    # BH 下，一旦一个 p > threshold，后续如果还有 p <= threshold 也应拒绝
    # 但标准 BH 的做法是找到最大的 k
    if max_reject_k < m:
        # 只拒绝 p(1)...p(max_reject_k)
        all_sorted_indices = [idx for idx, _ in indexed]
        rejected_indices = all_sorted_indices[:max_reject_k]

    return CorrectionResult(
        method="benjamini_hochberg",
        n_tests=m,
        alpha_original=alpha,
        alpha_adjusted=alpha / m,  # 最严格的阈值参考
        p_values_adjusted=adjusted,
        rejected_indices=rejected_indices,
        summary=f"Benjamini-Hochberg (FDR={alpha}): m={m}, "
                f"拒绝 {len(rejected_indices)}/{m} 个零假设",
    )


def adjust_significance_threshold(
    n_tests: int,
    alpha: float = 0.05,
    method: str = "bonferroni",
) -> float:
    """调整显著性阈值

    快捷函数，直接返回调整后的 alpha 阈值。

    Args:
        n_tests: 同时检验的因子数
        alpha: 原始显著性水平
        method: 校正方法 ("bonferroni", "holm", "bh")

    Returns:
        float: 调整后的显著性阈值

    Example:
        >>> adjust_significance_threshold(20, 0.05, "bonferroni")
        0.0025
        >>> adjust_significance_threshold(100, 0.01, "bonferroni")
        0.0001
    """
    if n_tests <= 0:
        return alpha
    if method == "bonferroni":
        return alpha / n_tests
    elif method in ("holm", "bh"):
        return alpha / n_tests  # 虽然不是精确值，但作为参考
    return alpha / n_tests


# ═══════════════════════════════════════════════════════════════════
# 基于因子 IC 的显著性判定
# ═══════════════════════════════════════════════════════════════════


def ic_significance_threshold(
    n_stocks: int,
    n_periods: int,
    n_factors: int = 1,
    alpha: float = 0.05,
    method: str = "bonferroni",
) -> dict:
    """计算 Rank IC 的显著性阈值

    基于 Spearman 秩相关的 t 分布近似:
      t = IC * sqrt((n - 2) / (1 - IC^2))
      近似正态: 标准误 ≈ 1 / sqrt(n - 1)

    考虑多重检验后:
      - 原始 IC 阈值: z(alpha/2) / sqrt(n - 1)
      - 调整后: z(alpha_adjust/2) / sqrt(n - 1)

    Args:
        n_stocks: 选股池数量
        n_periods: 时间期数
        n_factors: 同时检验的因子数
        alpha: 显著性水平
        method: 校正方法

    Returns:
        dict: 包含 raw_threshold, adjusted_threshold, alpha_adj 等
    """
    from scipy.stats import norm

    # 校正 alpha
    alpha_adj = adjust_significance_threshold(n_factors, alpha, method)

    # 标准误近似
    se = 1.0 / math.sqrt(n_periods - 1) if n_periods > 1 else 1.0

    # 原始阈值
    z_raw = float(norm.ppf(1 - alpha / 2))
    raw_threshold = z_raw * se

    # 调整后阈值
    z_adj = float(norm.ppf(1 - alpha_adj / 2))
    adj_threshold = z_adj * se

    return {
        "n_stocks": n_stocks,
        "n_periods": n_periods,
        "n_factors": n_factors,
        "alpha_original": alpha,
        "alpha_adjusted": alpha_adj,
        "method": method,
        "ic_standard_error": round(se, 6),
        "ic_threshold_raw": round(raw_threshold, 6),
        "ic_threshold_adjusted": round(adj_threshold, 6),
        "interpretation": (
            f"当同时检验 {n_factors} 个因子时，{method} 校正后 "
            f"IC 显著性阈值从 {raw_threshold:.4f} 提高到 {adj_threshold:.4f}"
        ),
    }


# ═══════════════════════════════════════════════════════════════════
# 类封装
# ═══════════════════════════════════════════════════════════════════


class MultipleTestCorrector:
    """多重检验校正器

    支持多种校正方法，自动根据检验数调整显著性。

    Example:
        corrector = MultipleTestCorrector()
        p_values = [0.01, 0.04, 0.06, 0.20, 0.50]
        result = corrector.correct(p_values, method="bonferroni")
        print(result.summary)
    """

    def __init__(self, alpha: float = 0.05):
        self.alpha = alpha

    def correct(
        self,
        p_values: List[float],
        method: str = "bonferroni",
    ) -> CorrectionResult:
        """执行多重检验校正

        Args:
            p_values: 原始 p 值列表
            method: 校正方法 ("bonferroni", "holm", "bh", "by")

        Returns:
            CorrectionResult
        """
        if method == "bonferroni":
            return bonferroni_adjust(p_values, self.alpha)
        elif method == "holm":
            return holm_bonferroni_adjust(p_values, self.alpha)
        elif method == "bh":
            return benjamini_hochberg_adjust(p_values, self.alpha)
        else:
            raise ValueError(f"未知校正方法: {method}，支持: bonferroni, holm, bh")

    def adjust_threshold(self, n_tests: int, method: str = "bonferroni") -> float:
        """获取调整后的显著性阈值"""
        return adjust_significance_threshold(n_tests, self.alpha, method)
