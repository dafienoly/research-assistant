"""Sector Rotation Spec V6.8 — 行业轮动数据结构

定义行业轮动策略的配置、性能指标、信号和回测结果数据模型。

设计理念:
  - 复用 V6.4 PortfolioSpec/PortfolioResult 进行组合层回测
  - SectorRotationConfig 定义轮动策略参数
  - RotationSignal 记录每次调仓信号
  - RotationResult 封装完整的轮动回测结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


class RotationStrategyType(str, Enum):
    """轮动策略类型"""
    MOMENTUM = "momentum"           # 动量轮动: 买入强势行业
    MEAN_REVERSION = "mean_reversion"  # 均值回归: 买入超跌行业
    COMPOSITE = "composite"         # 复合轮动: 动量+资金+估值综合评分

    def __str__(self) -> str:
        return self.value


@dataclass
class SectorRotationConfig:
    """行业轮动策略配置

    Attributes:
        name: 策略名称
        strategy_type: 轮动策略类型
        sectors: 参与轮动的行业列表 (None = 使用所有行业)
        universe: 股票池筛选 (None = 使用所有 A 股)
        top_n: 持有行业数量 (取评分最高的 N 个行业)
        lookback_short: 短期动量窗口 (交易日, 默认 20)
        lookback_medium: 中期动量窗口 (交易日, 默认 60)
        lookback_long: 长期动量窗口 (交易日, 默认 120)
        rebalance_freq: 调仓频率: "weekly" / "monthly" / "quarterly"
        equal_weight: 是否等权持有选中的行业 (True=等权, False=按评分加权)
        min_sectors: 最少持有行业数 (避免过度集中)
        max_sectors: 最多持有行业数 (避免过度分散)
        benchmark_name: 基准指数名称
    """
    name: str = "SectorRotation"
    strategy_type: RotationStrategyType = RotationStrategyType.MOMENTUM
    sectors: Optional[list[str]] = None
    universe: Optional[list[str]] = None
    top_n: int = 5
    lookback_short: int = 20
    lookback_medium: int = 60
    lookback_long: int = 120
    rebalance_freq: str = "monthly"
    equal_weight: bool = True
    min_sectors: int = 3
    max_sectors: int = 10
    benchmark_name: str = "CSI300"

    def validate(self) -> list[str]:
        """校验配置参数, 返回错误信息列表"""
        errors: list[str] = []

        if not self.name:
            errors.append("策略名称不能为空")

        if self.top_n < 1:
            errors.append(f"top_n={self.top_n} 必须 >= 1")

        if self.min_sectors > self.max_sectors:
            errors.append(
                f"min_sectors={self.min_sectors} > max_sectors={self.max_sectors}"
            )

        if self.top_n > self.max_sectors:
            errors.append(
                f"top_n={self.top_n} > max_sectors={self.max_sectors}"
            )

        valid_freqs = {"weekly", "monthly", "quarterly"}
        if self.rebalance_freq not in valid_freqs:
            errors.append(
                f"不支持的调仓频率 '{self.rebalance_freq}', "
                f"可选: {valid_freqs}"
            )

        if self.lookback_short < 5:
            errors.append(f"短期窗口 lookback_short={self.lookback_short} 过短")

        return errors

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "strategy_type": self.strategy_type.value,
            "sectors": self.sectors,
            "top_n": self.top_n,
            "lookback_short": self.lookback_short,
            "lookback_medium": self.lookback_medium,
            "lookback_long": self.lookback_long,
            "rebalance_freq": self.rebalance_freq,
            "equal_weight": self.equal_weight,
            "min_sectors": self.min_sectors,
            "max_sectors": self.max_sectors,
            "benchmark_name": self.benchmark_name,
        }


@dataclass
class SectorPerformance:
    """行业绩效数据

    记录行业在某一时段的收益率、动量、资金流、波动率等指标。
    """
    sector_name: str = ""
    stock_count: int = 0

    # ── 收益率 ──
    return_short: float = 0.0      # 短期收益率
    return_medium: float = 0.0     # 中期收益率
    return_long: float = 0.0       # 长期收益率

    # ── 动量 ──
    momentum_score: float = 0.0     # 动量评分 (正=强势)

    # ── 波动率 ──
    volatility: float = 0.0        # 行业波动率 (日化)
    sharpe_ratio: float = 0.0      # 行业夏普比

    # ── 资金流 ──
    fund_flow_score: float = 0.0   # 资金流评分

    # ── 综合 ──
    composite_score: float = 0.0   # 综合评分

    def to_dict(self) -> dict:
        return {
            "sector_name": self.sector_name,
            "stock_count": self.stock_count,
            "return_short": round(self.return_short * 100, 2),
            "return_medium": round(self.return_medium * 100, 2),
            "return_long": round(self.return_long * 100, 2),
            "momentum_score": round(self.momentum_score, 4),
            "volatility": round(self.volatility * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "fund_flow_score": round(self.fund_flow_score, 4),
            "composite_score": round(self.composite_score, 4),
        }


@dataclass
class RotationSignal:
    """轮动调仓信号"""
    date: str = ""                 # 信号日期 YYYY-MM-DD
    strategy_type: str = ""        # 策略类型
    rankings: list[dict] = field(default_factory=list)  # [(sector, score), ...]
    selected_sectors: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)  # sector → weight
    n_available: int = 0           # 可选行业数
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "strategy_type": self.strategy_type,
            "rankings": self.rankings[:10],  # 只展示 Top-10
            "selected_sectors": self.selected_sectors,
            "weights": self.weights,
            "n_available": self.n_available,
            "n_selected": len(self.selected_sectors),
        }


@dataclass
class RotationResult:
    """行业轮动回测结果

    Attributes:
        config: 轮动策略配置
        portfolio_result: V6.4 组合回测结果 (由 PortfolioBacktestEngine 生成)
        signals: 历史调仓信号列表
        sector_performance_history: 各行业历史绩效 DataFrame
        sector_returns: 行业收益率 DataFrame {sector: return_series}
        rotation_log: 轮动执行日志
        warnings: 警告信息
    """
    config: Optional[SectorRotationConfig] = None
    portfolio_result: Optional[object] = None  # PortfolioResult from V6.4
    signals: list[RotationSignal] = field(default_factory=list)
    sector_performance_history: Optional[pd.DataFrame] = None
    sector_returns: dict[str, pd.Series] = field(default_factory=dict)
    rotation_log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # 派生指标
    n_signals: int = 0
    avg_sectors_per_signal: float = 0.0
    sector_turnover: float = 0.0     # 行业换手率

    def summary(self) -> dict:
        """返回便于打印的摘要"""
        base = {}
        if self.portfolio_result is not None:
            try:
                base = self.portfolio_result.summary()
            except Exception:
                base = {"note": "portfolio_result available"}

        return {
            "config": self.config.to_dict() if self.config else {},
            "portfolio": base,
            "n_signals": self.n_signals,
            "avg_sectors_per_signal": round(self.avg_sectors_per_signal, 1),
            "sector_turnover": round(self.sector_turnover, 4),
            "n_sectors_in_result": len(self.sector_returns),
            "n_signals_in_log": len(self.signals),
            "n_warnings": len(self.warnings),
        }

    def to_dict(self) -> dict:
        d = self.summary()
        d["signals"] = [s.to_dict() for s in self.signals[:5]]
        if self.warnings:
            d["warnings"] = self.warnings
        return d
