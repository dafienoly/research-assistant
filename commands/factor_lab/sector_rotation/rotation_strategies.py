"""Rotation Strategies V6.8 — 行业轮动策略实现

提供 3 种行业轮动策略:
  1. MomentumRotation — 动量轮动: 买入近期涨幅最强的行业
  2. MeanReversionRotation — 均值回归: 买入近期超跌行业
  3. CompositeRotation — 复合轮动: 综合考虑动量+波动率+资金流

每个策略实现 ISectorRotation 接口, 可被 RotationEngine 调用。

用法:
    from factor_lab.sector_rotation.rotation_strategies import (
        MomentumRotation, MeanReversionRotation, CompositeRotation,
    )
    strategy = MomentumRotation(top_n=5)
    rankings = strategy.rank_sectors(performances)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from factor_lab.sector_rotation.spec import SectorPerformance, SectorRotationConfig


# ─── 抽象策略接口 ─────────────────────────────────────────────


class ISectorRotationStrategy(ABC):
    """行业轮动策略接口"""

    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        ...

    @abstractmethod
    def rank_sectors(
        self,
        performances: list[SectorPerformance],
    ) -> list[dict]:
        """对行业打分并排名

        Args:
            performances: 行业绩效数据列表

        Returns:
            按得分降序排列的 [{"sector": str, "score": float, ...}, ...]
        """
        ...

    @abstractmethod
    def select_sectors(
        self,
        rankings: list[dict],
        top_n: int,
    ) -> list[str]:
        """从排名中选择行业

        Args:
            rankings: rank_sectors 的输出
            top_n: 选择数量

        Returns:
            选中行业列表
        """
        ...


# ─── 策略 1: 动量轮动 ────────────────────────────────────────


class MomentumRotation(ISectorRotationStrategy):
    """动量轮动策略

    按短期和中期动量的加权综合评分排名, 选择最强行业。
    核心逻辑: 行业短中期收益越高, 评分越高。

    Score = return_short * 0.6 + return_medium * 0.3 + return_long * 0.1
    """

    def name(self) -> str:
        return "momentum"

    def rank_sectors(
        self,
        performances: list[SectorPerformance],
    ) -> list[dict]:
        rankings = []
        for perf in performances:
            # 动量轮动: 短期权重最高
            score = (
                perf.return_short * 0.6
                + perf.return_medium * 0.3
                + perf.return_long * 0.1
            )

            rankings.append({
                "sector": perf.sector_name,
                "score": round(score, 6),
                "momentum": round(perf.momentum_score, 4),
                "return_short_pct": round(perf.return_short * 100, 2),
                "return_medium_pct": round(perf.return_medium * 100, 2),
                "volatility_pct": round(perf.volatility * 100, 2),
            })

        rankings.sort(key=lambda x: x["score"], reverse=True)
        return rankings

    def select_sectors(
        self,
        rankings: list[dict],
        top_n: int,
    ) -> list[str]:
        return [r["sector"] for r in rankings[:top_n]]


# ─── 策略 2: 均值回归 ────────────────────────────────────────


class MeanReversionRotation(ISectorRotationStrategy):
    """均值回归轮动策略

    买入近期表现最差的行业 (超跌反弹逻辑)。
    核心逻辑: 行业短期表现越差, 评分反而越高。

    Score = -return_short * 0.7 + -return_medium * 0.3
    同时过滤掉波动过大的行业 (异常波动可能是趋势延续而非反转)
    """

    def __init__(self, max_volatility: float = 0.04):
        """
        Args:
            max_volatility: 最大日波动率阈值 (超过此值视为异常, 跳过)
        """
        self.max_volatility = max_volatility

    def name(self) -> str:
        return "mean_reversion"

    def rank_sectors(
        self,
        performances: list[SectorPerformance],
    ) -> list[dict]:
        rankings = []
        for perf in performances:
            # 均值回归: 短期表现越差, 评分越高
            # 过高的波动率可能是趋势延续, 降低评分
            vol_penalty = 1.0
            if perf.volatility > self.max_volatility:
                vol_penalty = self.max_volatility / (perf.volatility + 1e-10)

            score = (
                -perf.return_short * 0.7
                + -perf.return_medium * 0.3
            ) * vol_penalty

            rankings.append({
                "sector": perf.sector_name,
                "score": round(score, 6),
                "return_short_pct": round(perf.return_short * 100, 2),
                "return_medium_pct": round(perf.return_medium * 100, 2),
                "volatility_pct": round(perf.volatility * 100, 2),
                "vol_penalty": round(vol_penalty, 4),
            })

        rankings.sort(key=lambda x: x["score"], reverse=True)
        return rankings

    def select_sectors(
        self,
        rankings: list[dict],
        top_n: int,
    ) -> list[str]:
        return [r["sector"] for r in rankings[:top_n]]


# ─── 策略 3: 复合轮动 ────────────────────────────────────────


class CompositeRotation(ISectorRotationStrategy):
    """复合轮动策略

    综合考虑动量、波动率和资金流的多维度评分。

    Score = momentum_weight * momentum_normalized
          + low_vol_weight * (-volatility_normalized)
          + fund_flow_weight * fund_flow_normalized

    各维度先 Z-Score 标准化后再加权。
    """

    def __init__(
        self,
        momentum_weight: float = 0.5,
        low_vol_weight: float = 0.3,
        fund_flow_weight: float = 0.2,
    ):
        """
        Args:
            momentum_weight: 动量权重
            low_vol_weight: 低波动权重
            fund_flow_weight: 资金流权重
        """
        self.momentum_weight = momentum_weight
        self.low_vol_weight = low_vol_weight
        self.fund_flow_weight = fund_flow_weight

    def name(self) -> str:
        return "composite"

    def rank_sectors(
        self,
        performances: list[SectorPerformance],
    ) -> list[dict]:
        if not performances:
            return []

        # 收集原始值
        momentum_vals = np.array([p.momentum_score for p in performances])
        volatility_vals = np.array([p.volatility for p in performances])
        fund_flow_vals = np.array([p.fund_flow_score for p in performances])

        # Z-Score 标准化
        mom_norm = _zscore(momentum_vals)
        vol_norm = _zscore(volatility_vals)   # 正值=高波动(不好)
        flow_norm = _zscore(fund_flow_vals)

        rankings = []
        for i, perf in enumerate(performances):
            # 低波动维度取负号 (越低越好)
            score = (
                self.momentum_weight * mom_norm[i]
                - self.low_vol_weight * vol_norm[i]
                + self.fund_flow_weight * flow_norm[i]
            )

            rankings.append({
                "sector": perf.sector_name,
                "score": round(score, 6),
                "momentum": round(perf.momentum_score, 4),
                "volatility_pct": round(perf.volatility * 100, 2),
                "fund_flow": round(perf.fund_flow_score, 4),
                "mom_zscore": round(mom_norm[i], 3),
                "vol_zscore": round(vol_norm[i], 3),
                "flow_zscore": round(flow_norm[i], 3),
            })

        rankings.sort(key=lambda x: x["score"], reverse=True)
        return rankings

    def select_sectors(
        self,
        rankings: list[dict],
        top_n: int,
    ) -> list[str]:
        return [r["sector"] for r in rankings[:top_n]]


# ─── 策略工厂 ────────────────────────────────────────────────


def create_strategy(
    config: SectorRotationConfig,
) -> ISectorRotationStrategy:
    """根据配置创建轮动策略实例

    Args:
        config: 轮动策略配置

    Returns:
        策略实例

    Raises:
        ValueError: 不支持的策略类型
    """
    strategy_type = config.strategy_type
    if strategy_type.value == "momentum":
        return MomentumRotation()
    elif strategy_type.value == "mean_reversion":
        return MeanReversionRotation()
    elif strategy_type.value == "composite":
        return CompositeRotation()
    else:
        raise ValueError(
            f"不支持的策略类型 '{strategy_type}', "
            f"可选: momentum / mean_reversion / composite"
        )


# ─── 辅助函数 ────────────────────────────────────────────────


def _zscore(arr: np.ndarray) -> np.ndarray:
    """Z-Score 标准化"""
    std = arr.std()
    if std < 1e-10:
        return np.zeros_like(arr)
    return (arr - arr.mean()) / std
