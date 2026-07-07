"""Portfolio Backtest Engine V6.4 — 组合回测引擎

核心功能:
  1. 接收多个策略的收益率序列和权重配置 (PortfolioSpec)
  2. 按调仓频率进行组合权重再平衡
  3. 计算组合层面的日收益率和净值曲线
  4. 与基准指数对比 (BenchmarkSpec)
  5. 输出完整 PortfolioResult 包含指标、归因、相关性

设计理念:
  - 聚焦组合层, 不代替各策略的回测 (由 AShareBacktester 等完成)
  - 输入: 各策略已算好的收益率序列
  - 输出: 组合层的收益率/指标/归因

使用方式:
    from factor_lab.portfolio import PortfolioSpec, BenchmarkSpec
    from factor_lab.portfolio.portfolio_backtest import PortfolioBacktestEngine

    spec = PortfolioSpec(
        name="My Portfolio",
        strategy_returns={"mom": mom_ret, "value": val_ret},
        weights={"mom": 0.5, "value": 0.5},
        rebalance_freq="monthly",
    )
    engine = PortfolioBacktestEngine(spec)
    result = engine.run()

    result = engine.run_with_benchmark(
        benchmark_spec=BenchmarkSpec(name="CSI300")
    )
"""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.portfolio.spec import (
    PortfolioSpec,
    BenchmarkSpec,
    PortfolioMetrics,
    PortfolioResult,
    AttributionItem,
)
from factor_lab.portfolio.metrics import (
    compute_portfolio_absolute_metrics,
    compute_benchmark_relative_metrics,
    compute_cross_correlation,
    compute_avg_correlation,
    compute_attribution,
)
from factor_lab.portfolio.benchmark import get_benchmark_returns, make_benchmark_spec
from factor_lab.metrics import calc_sharpe


class PortfolioBacktestEngine:
    """组合回测引擎

    将多个策略的收益率按权重组合为投资组合, 定期再平衡,
    并与基准指数对比。

    Parameters
    ----------
    portfolio_spec: PortfolioSpec
        组合配置规格 (包含策略收益率和权重)
    """

    def __init__(self, portfolio_spec: PortfolioSpec):
        # 校验
        errors = portfolio_spec.validate()
        if errors:
            raise ValueError(
                f"组合配置校验失败:\n  " + "\n  ".join(errors)
            )

        self.spec = portfolio_spec
        self.execution_log: list[str] = []
        self.warnings: list[str] = []

    # ──────────────────────────────────────────────────────────
    # 主运行接口
    # ──────────────────────────────────────────────────────────

    def run(
        self,
        benchmark_spec: Optional[BenchmarkSpec] = None,
        synthetic_benchmark: bool = True,
    ) -> PortfolioResult:
        """执行组合回测

        步骤:
          1. 对齐各策略收益率至公共日期
          2. 按调仓频率构建权重序列
          3. 计算组合日收益率
          4. 计算组合净值曲线
          5. 如有基准, 加载基准收益率并对比
          6. 计算指标、归因、相关性

        Args:
            benchmark_spec: 基准规格 (None = 不对比基准)
            synthetic_benchmark: 是否使用 synthetic 基准 (无真实数据时)

        Returns:
            PortfolioResult 包含完整回测结果
        """
        self.execution_log = []
        self.warnings = []

        # ── Step 1: 对齐所有策略日期 ──
        self.execution_log.append(
            "step: 对齐策略收益率日期"
        )
        aligned = self._align_strategy_returns()

        if aligned.empty:
            self.warnings.append("所有策略收益率日期无重叠")
            return self._empty_result()

        # ── Step 2: 构建权重序列 ──
        self.execution_log.append(
            f"step: 构建权重序列 (再平衡={self.spec.rebalance_freq})"
        )
        weight_df = self._build_weight_schedule(aligned.index)

        # ── Step 3: 计算组合日收益率 ──
        self.execution_log.append("step: 计算组合日收益率")
        portfolio_ret, weight_history = self._compute_portfolio_returns(
            aligned, weight_df
        )

        if portfolio_ret.empty or portfolio_ret.std() < 1e-10:
            self.warnings.append("组合收益率为常数或空")
            return self._empty_result()

        # ── Step 4: 净值曲线 ──
        portfolio_equity = (1 + portfolio_ret).cumprod()

        # ── Step 5: 基准对比 ──
        benchmark_ret = None
        benchmark_equity = None
        active_ret = None

        if benchmark_spec is not None:
            try:
                self.execution_log.append(
                    f"step: 加载基准 {benchmark_spec.name}"
                )
                benchmark_ret = get_benchmark_returns(
                    benchmark_spec,
                    index_dates=portfolio_ret.index,
                    method="synthetic" if synthetic_benchmark else "etf_proxy",
                )
                # 对齐日期
                common = portfolio_ret.index.intersection(benchmark_ret.index)
                if len(common) < 5:
                    self.warnings.append(
                        f"基准 {benchmark_spec.name} 与组合日期重叠不足 5 天"
                    )
                    benchmark_ret = None
                else:
                    benchmark_ret = benchmark_ret.loc[common].sort_index()
                    portfolio_for_bm = portfolio_ret.loc[common].sort_index()

                    benchmark_equity = (1 + benchmark_ret).cumprod()
                    active_ret = portfolio_for_bm - benchmark_ret

            except Exception as e:
                self.warnings.append(
                    f"基准加载失败: {e}"
                )

        # ── Step 6: 计算指标 ──
        self.execution_log.append("step: 计算组合指标")
        metrics_dict = self._compute_all_metrics(
            portfolio_ret, benchmark_ret
        )

        # ── Step 7: 归因分析 ──
        self.execution_log.append("step: 归因分析")
        attribution = compute_attribution(
            self.spec.strategy_returns,
            self.spec.weights,
            portfolio_ret,
        )

        # ── Step 8: 交叉相关性 ──
        corr_matrix = compute_cross_correlation(self.spec.strategy_returns)
        avg_corr = compute_avg_correlation(corr_matrix)

        # ── 各策略收益率/净值 ──
        individual_returns = {}
        individual_equities = {}
        for sname, s_ret in self.spec.strategy_returns.items():
            date_range = portfolio_ret.index
            aligned_s = s_ret.reindex(date_range).fillna(0)
            individual_returns[sname] = aligned_s
            individual_equities[sname] = (1 + aligned_s).cumprod()

        # ── 构建 PortfolioMetrics ──
        metrics = PortfolioMetrics(
            cumulative_return_pct=metrics_dict.get(
                "cumulative_return_pct", 0.0
            ),
            annualized_return_pct=metrics_dict.get(
                "annualized_return_pct", 0.0
            ),
            annualized_volatility_pct=metrics_dict.get(
                "annualized_volatility_pct", 0.0
            ),
            sharpe=metrics_dict.get("sharpe", 0.0),
            max_drawdown_pct=metrics_dict.get(
                "max_drawdown_pct", 0.0
            ),
            calmar=metrics_dict.get("calmar", 0.0),
            win_rate_pct=metrics_dict.get("win_rate_pct", 0.0),
            n_trading_days=metrics_dict.get("n_trading_days", 0),
            benchmark_cumulative_return_pct=metrics_dict.get(
                "benchmark_cumulative_return_pct", 0.0
            ),
            benchmark_annualized_return_pct=metrics_dict.get(
                "benchmark_annualized_return_pct", 0.0
            ),
            benchmark_volatility_pct=metrics_dict.get(
                "benchmark_volatility_pct", 0.0
            ),
            benchmark_sharpe=metrics_dict.get(
                "benchmark_sharpe", 0.0
            ),
            benchmark_max_drawdown_pct=metrics_dict.get(
                "benchmark_max_drawdown_pct", 0.0
            ),
            active_return_pct=metrics_dict.get(
                "active_return_pct", 0.0
            ),
            tracking_error_pct=metrics_dict.get(
                "tracking_error_pct", 0.0
            ),
            information_ratio=metrics_dict.get(
                "information_ratio", 0.0
            ),
            alpha=metrics_dict.get("alpha", 0.0),
            beta=metrics_dict.get("beta", 0.0),
            r_squared=metrics_dict.get("r_squared", 0.0),
            avg_cross_correlation=avg_corr,
            n_strategies=len(self.spec.strategy_returns),
            strategy_metrics=metrics_dict.get(
                "strategy_metrics", {}
            ),
        )

        # ── Attribution items ──
        attr_items = [
            AttributionItem(
                strategy_name=a["strategy_name"],
                weight=a["weight"],
                contribution_pct=a["contribution_pct"],
                marginal_contribution=a["marginal_contribution"],
                sharpe=a["sharpe"],
                standalone_return_pct=a["standalone_return_pct"],
                correlation_to_portfolio=a["correlation_to_portfolio"],
            )
            for a in attribution
        ]

        result = PortfolioResult(
            portfolio_spec=self.spec,
            benchmark_spec=benchmark_spec,
            portfolio_returns=portfolio_ret,
            portfolio_equity=portfolio_equity,
            benchmark_returns=benchmark_ret,
            benchmark_equity=benchmark_equity,
            active_returns=active_ret,
            individual_returns=individual_returns,
            individual_equities=individual_equities,
            metrics=metrics,
            weight_history=weight_history,
            attribution=attr_items,
            cross_correlation=corr_matrix,
            execution_log=self.execution_log,
            warnings=self.warnings,
        )

        return result

    def run_with_benchmark(
        self,
        benchmark_name: str = "CSI300",
        synthetic: bool = True,
    ) -> PortfolioResult:
        """便捷方法: 带基准对比的回测

        Args:
            benchmark_name: 基准名称
            synthetic: 是否使用 synthetic 数据

        Returns:
            PortfolioResult
        """
        benchmark_spec = make_benchmark_spec(benchmark_name)
        return self.run(
            benchmark_spec=benchmark_spec,
            synthetic_benchmark=synthetic,
        )

    # ──────────────────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────────────────

    def _align_strategy_returns(self) -> pd.DataFrame:
        """对齐各策略收益率到公共日期

        Returns:
            DataFrame, index=公共日期, columns=策略名称
        """
        if not self.spec.strategy_returns:
            return pd.DataFrame()

        dfs = []
        for sname, s_ret in self.spec.strategy_returns.items():
            if s_ret is not None and len(s_ret) > 0:
                s = s_ret.copy()
                s.name = sname
                dfs.append(s)

        if not dfs:
            return pd.DataFrame()

        combined = pd.concat(dfs, axis=1).fillna(0)
        combined = combined.sort_index()

        return combined

    def _build_weight_schedule(
        self,
        dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """构建权重计划表

        根据 rebalance_freq 生成每个交易日的策略权重:

        Args:
            dates: 所有交易日期

        Returns:
            DataFrame, index=dates, columns=策略名称, values=权重
        """
        weights = self.spec.weights
        strategy_names = list(weights.keys())
        n = len(dates)

        # 基础权重向量
        w = np.array([weights.get(s, 0.0) for s in strategy_names])

        # 确定再平衡日
        if self.spec.rebalance_freq == "none":
            # 仅首日建仓, 权重永不调整
            reb_dates = [dates[0]]
        elif self.spec.rebalance_freq == "monthly":
            # 每月第一个交易日
            seen: set[tuple[int, int]] = set()
            reb_dates = []
            for d in dates:
                ym = (d.year, d.month)
                if ym not in seen:
                    seen.add(ym)
                    reb_dates.append(d)
        elif self.spec.rebalance_freq == "weekly":
            reb_dates = [d for d in dates if d.dayofweek == 0]
        elif self.spec.rebalance_freq == "daily":
            reb_dates = list(dates)
        else:
            reb_dates = [dates[0]]

        reb_set = set(reb_dates)
        if not reb_dates:
            reb_dates = [dates[0]]
            reb_set = {dates[0]}

        # 构建权重矩阵
        weight_list = []
        current_w = w.copy()

        for d in dates:
            if d in reb_set:
                # 重置为固定权重
                current_w = w.copy()
                if self.spec.rebalance_method == "equal":
                    current_w = np.ones(len(w)) / len(w)

            weight_list.append(current_w.copy())

        weight_df = pd.DataFrame(
            weight_list,
            index=dates,
            columns=strategy_names,
        )
        return weight_df

    def _compute_portfolio_returns(
        self,
        aligned_returns: pd.DataFrame,
        weight_df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.DataFrame]:
        """计算组合日收益率

        组合收益率 = sum(策略收益率_i * 当日权重_i)

        权重历史记录包含每次调仓的权重变化。

        Returns:
            (portfolio_returns, weight_history)
        """
        dates = aligned_returns.index

        # 确保权重与收益率日期对齐
        w = weight_df.reindex(dates).ffill().fillna(0)

        # 组合收益率 = dot(权重, 收益率)
        portfolio_ret = (aligned_returns * w.values).sum(axis=1)
        portfolio_ret.name = self.spec.name

        # 权重历史
        weight_history = w.copy()
        weight_history["date"] = dates
        weight_history = weight_history.set_index("date")

        return portfolio_ret, weight_history

    def _compute_all_metrics(
        self,
        portfolio_returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None,
    ) -> dict:
        """一站式指标计算"""
        result = compute_portfolio_absolute_metrics(portfolio_returns)

        if benchmark_returns is not None and len(benchmark_returns) > 0:
            bm_metrics = compute_benchmark_relative_metrics(
                portfolio_returns, benchmark_returns
            )
            result.update(bm_metrics)

        # 策略明细
        strategy_metrics = {}
        for sname, s_ret in self.spec.strategy_returns.items():
            aligned = s_ret.reindex(portfolio_returns.index).fillna(0)
            strategy_metrics[sname] = compute_portfolio_absolute_metrics(aligned)

        result["strategy_metrics"] = strategy_metrics
        result["n_strategies"] = len(self.spec.strategy_returns)

        return result

    def _empty_result(self) -> PortfolioResult:
        """返回空白结果 (当数据不足时)"""
        return PortfolioResult(
            portfolio_spec=self.spec,
            execution_log=self.execution_log,
            warnings=self.warnings,
        )
