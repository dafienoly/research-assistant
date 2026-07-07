"""Portfolio Backtest Spec V6.4 — 组合回测数据结构

定义组合策略规格 (PortfolioSpec)、基准规格 (BenchmarkSpec)、
组合指标 (PortfolioMetrics) 和完整回测结果 (PortfolioResult)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import pandas as pd


@dataclass
class PortfolioSpec:
    """组合策略规格

    Attributes:
        name: 组合名称
        strategy_returns: 策略名称 → 日收益率 Series 的映射
        weights: 策略名称 → 初始权重 (应满足 sum(weights.values()) ≈ 1.0)
        rebalance_freq: 组合权重再平衡频率: "none" / "monthly" / "weekly" / "daily"
             "none" 表示建仓后权重随涨跌漂移, 不再调整
        rebalance_method: 再平衡方式: "fixed" (固定权重) / "equal" (等权)
    """
    name: str = "Portfolio"
    strategy_returns: dict[str, pd.Series] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    rebalance_freq: str = "monthly"
    rebalance_method: str = "fixed"

    def validate(self) -> List[str]:
        """校验配置完整性, 返回错误信息列表"""
        errors: list[str] = []

        if not self.name:
            errors.append("组合名称不能为空")

        if not self.strategy_returns:
            errors.append("策略收益率为空, 请至少提供一个策略")
        else:
            # 检查权重与策略匹配
            for name in self.strategy_returns:
                if name not in self.weights:
                    errors.append(f"策略 '{name}' 缺少权重配置")
            for name in self.weights:
                if name not in self.strategy_returns:
                    errors.append(f"策略 '{name}' 有权重但无收益率数据")

            # 检查权重和是否 ≈ 1.0
            if self.weights:
                total_w = sum(self.weights.values())
                if abs(total_w - 1.0) > 0.02:
                    errors.append(
                        f"权重和={total_w:.4f}, 应接近 1.0"
                    )

            # 检查频率
            valid_freqs = {"none", "monthly", "weekly", "daily"}
            if self.rebalance_freq not in valid_freqs:
                errors.append(
                    f"不支持的调仓频率 '{self.rebalance_freq}', "
                    f"可选: {valid_freqs}"
                )

        return errors

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "strategy_names": list(self.strategy_returns.keys()),
            "weights": self.weights,
            "rebalance_freq": self.rebalance_freq,
            "rebalance_method": self.rebalance_method,
        }


@dataclass
class BenchmarkSpec:
    """基准规格

    Attributes:
        name: 基准名称, 如 "CSI300" / "CSI500" / "CSI1000" / "CSI_ALL" / "custom"
        returns: 自定义基准收益率 (仅 name="custom" 时使用)
        description: 基准描述
    """
    name: str = "CSI300"
    returns: Optional[pd.Series] = None
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description or self.name,
        }


@dataclass
class PortfolioMetrics:
    """组合层面指标"""
    # ── 组合绝对指标 ──
    cumulative_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    annualized_volatility_pct: float = 0.0
    sharpe: float = 0.0
    max_drawdown_pct: float = 0.0
    calmar: float = 0.0
    win_rate_pct: float = 0.0
    n_trading_days: int = 0

    # ── 基准相关 ──
    benchmark_cumulative_return_pct: float = 0.0
    benchmark_annualized_return_pct: float = 0.0
    benchmark_volatility_pct: float = 0.0
    benchmark_sharpe: float = 0.0
    benchmark_max_drawdown_pct: float = 0.0
    active_return_pct: float = 0.0
    tracking_error_pct: float = 0.0
    information_ratio: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    r_squared: float = 0.0

    # ── 策略间 ──
    avg_cross_correlation: float = 0.0
    n_strategies: int = 0

    # ── 组合明细 ──
    strategy_metrics: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为可 JSON 序列化的 dict"""
        return {
            "cumulative_return_pct": self.cumulative_return_pct,
            "annualized_return_pct": self.annualized_return_pct,
            "annualized_volatility_pct": self.annualized_volatility_pct,
            "sharpe": self.sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "calmar": self.calmar,
            "win_rate_pct": self.win_rate_pct,
            "n_trading_days": self.n_trading_days,
            "benchmark_cumulative_return_pct": self.benchmark_cumulative_return_pct,
            "benchmark_annualized_return_pct": self.benchmark_annualized_return_pct,
            "benchmark_volatility_pct": self.benchmark_volatility_pct,
            "benchmark_sharpe": self.benchmark_sharpe,
            "benchmark_max_drawdown_pct": self.benchmark_max_drawdown_pct,
            "active_return_pct": self.active_return_pct,
            "tracking_error_pct": self.tracking_error_pct,
            "information_ratio": self.information_ratio,
            "alpha": self.alpha,
            "beta": self.beta,
            "r_squared": self.r_squared,
            "avg_cross_correlation": self.avg_cross_correlation,
            "n_strategies": self.n_strategies,
        }


@dataclass
class AttributionItem:
    """归因分析项"""
    strategy_name: str = ""
    weight: float = 0.0
    contribution_pct: float = 0.0  # 对组合收益的贡献百分比
    marginal_contribution: float = 0.0  # 边际贡献 (权重×收益率)
    sharpe: float = 0.0
    standalone_return_pct: float = 0.0
    correlation_to_portfolio: float = 0.0


@dataclass
class PortfolioResult:
    """组合回测完整结果"""
    # ═══════════════════════════════════════════════════════
    # 配置
    # ═══════════════════════════════════════════════════════
    portfolio_spec: PortfolioSpec | None = None
    benchmark_spec: BenchmarkSpec | None = None
    run_id: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    # ═══════════════════════════════════════════════════════
    # 收益率 & 净值序列
    # ═══════════════════════════════════════════════════════
    portfolio_returns: Optional[pd.Series] = None
    portfolio_equity: Optional[pd.Series] = None
    benchmark_returns: Optional[pd.Series] = None
    benchmark_equity: Optional[pd.Series] = None
    active_returns: Optional[pd.Series] = None

    # 各策略收益率 & 净值
    individual_returns: dict[str, pd.Series] = field(default_factory=dict)
    individual_equities: dict[str, pd.Series] = field(default_factory=dict)

    # ═══════════════════════════════════════════════════════
    # 组合层面指标
    # ═══════════════════════════════════════════════════════
    metrics: PortfolioMetrics = field(default_factory=PortfolioMetrics)

    # ═══════════════════════════════════════════════════════
    # 权重历史 & 归因分析
    # ═══════════════════════════════════════════════════════
    weight_history: Optional[pd.DataFrame] = None
    attribution: list[AttributionItem] = field(default_factory=list)
    cross_correlation: Optional[pd.DataFrame] = None

    # ═══════════════════════════════════════════════════════
    # 验证 & 元信息
    # ═══════════════════════════════════════════════════════
    execution_log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def summary(self) -> dict:
        """返回便于打印的摘要 dict"""
        m = self.metrics
        return {
            "portfolio": self.portfolio_spec.name if self.portfolio_spec else "N/A",
            "benchmark": self.benchmark_spec.name if self.benchmark_spec else "N/A",
            "n_strategies": m.n_strategies,
            "cumulative_return_pct": m.cumulative_return_pct,
            "annualized_return_pct": m.annualized_return_pct,
            "sharpe": m.sharpe,
            "max_drawdown_pct": m.max_drawdown_pct,
            "calmar": m.calmar,
            "win_rate_pct": m.win_rate_pct,
            "benchmark_return_pct": m.benchmark_cumulative_return_pct,
            "active_return_pct": m.active_return_pct,
            "tracking_error_pct": m.tracking_error_pct,
            "information_ratio": m.information_ratio,
            "alpha": m.alpha,
            "beta": m.beta,
            "avg_cross_correlation": m.avg_cross_correlation,
            "n_trading_days": m.n_trading_days,
        }

    def to_dict(self) -> dict:
        """序列化为可 JSON 序列化的 dict (排除 Series/DataFrame)"""
        return {
            "run_id": self.run_id,
            "portfolio_spec": self.portfolio_spec.to_dict() if self.portfolio_spec else {},
            "benchmark_spec": self.benchmark_spec.to_dict() if self.benchmark_spec else {},
            "metrics": self.metrics.to_dict(),
            "attribution": [
                {
                    "strategy_name": a.strategy_name,
                    "weight": a.weight,
                    "contribution_pct": a.contribution_pct,
                    "marginal_contribution": a.marginal_contribution,
                    "sharpe": a.sharpe,
                    "standalone_return_pct": a.standalone_return_pct,
                    "correlation_to_portfolio": a.correlation_to_portfolio,
                }
                for a in self.attribution
            ],
            "execution_log": self.execution_log,
            "warnings": self.warnings,
            "generated_at": self.generated_at,
        }
