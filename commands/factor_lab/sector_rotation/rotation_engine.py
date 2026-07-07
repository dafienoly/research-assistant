"""Rotation Engine V6.8 — 行业轮动回测引擎

核心功能:
  1. 接收 SectorRotationConfig 和个股收益率数据
  2. 按调仓频率循环: 计算行业评分 → 选行业 → 定权重
  3. 生成 RotationSignal 信号流
  4. 构建行业策略收益率 → 使用 PortfolioBacktestEngine 回测
  5. 输出 RotationResult

设计理念:
  - 信号生成与组合回测分离 (策略模式)
  - 行业策略收益率序列 = 调仓周期内选中行业等权持有
  - 复用 V6.4 PortfolioBacktestEngine 计算最终指标
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.sector_rotation.spec import (
    SectorRotationConfig,
    SectorPerformance,
    RotationSignal,
    RotationResult,
    RotationStrategyType,
)
from factor_lab.sector_rotation.sector_performance import (
    compute_sector_returns,
    compute_sector_performance_snapshot,
    compute_sector_rankings,
    get_sector_mapping,
    get_sector_list,
)
from factor_lab.sector_rotation.rotation_strategies import (
    ISectorRotationStrategy,
    create_strategy,
)

CST = timezone(timedelta(hours=8))


class SectorRotationEngine:
    """行业轮动回测引擎

    驱动行业轮动的完整回测流程:
    1. 加载行业映射和个股收益率
    2. 按调仓频率生成轮动信号
    3. 构建行业策略收益率
    4. 使用 V6.4 PortfolioBacktestEngine 计算组合指标

    Parameters
    ----------
    config: SectorRotationConfig
        轮动策略配置
    strategy: ISectorRotationStrategy, optional
        策略实例 (None 则从 config 自动创建)
    """

    def __init__(
        self,
        config: SectorRotationConfig,
        strategy: Optional[ISectorRotationStrategy] = None,
    ):
        errors = config.validate()
        if errors:
            raise ValueError(
                f"轮动配置校验失败:\n  " + "\n  ".join(errors)
            )

        self.config = config
        self.strategy = strategy or create_strategy(config)
        self.rotation_log: list[str] = []
        self.warnings: list[str] = []

    # ── 主运行接口 ──────────────────────────────────────────

    def run(
        self,
        stock_returns: pd.DataFrame,
        sector_mapping: Optional[dict[str, str]] = None,
    ) -> RotationResult:
        """执行行业轮动回测

        流程:
          1. 计算行业收益率
          2. 确定调仓日期
          3. 在每个调仓日生成轮动信号
          4. 构建策略收益率 (选中行业等权持有)
          5. 使用 PortfolioBacktestEngine 回测

        Args:
            stock_returns: DataFrame(index=date, columns=symbol, values=日收益率)
            sector_mapping: {symbol: sector} (None=自动从 IndustryMapper 加载)

        Returns:
            RotationResult
        """
        self.rotation_log = []
        self.warnings = []

        self.rotation_log.append("step: 加载行业映射")
        mapping = sector_mapping or get_sector_mapping()
        if not mapping:
            self.warnings.append("行业映射为空, 无法运行轮动")
            return RotationResult(config=self.config, warnings=self.warnings)

        self.rotation_log.append("step: 计算行业收益率")
        sector_returns = compute_sector_returns(stock_returns, mapping)
        if not sector_returns:
            self.warnings.append("行业收益率为空")
            return RotationResult(config=self.config, warnings=self.warnings)

        # 过滤配置中指定的行业
        if self.config.sectors:
            sector_returns = {
                s: r for s, r in sector_returns.items()
                if s in self.config.sectors
            }

        if len(sector_returns) < self.config.min_sectors:
            self.warnings.append(
                f"可轮动行业数 {len(sector_returns)} < min_sectors {self.config.min_sectors}"
            )
            return RotationResult(
                config=self.config,
                sector_returns=sector_returns,
                warnings=self.warnings,
            )

        self.rotation_log.append(
            f"step: 确定调仓日期 (频率={self.config.rebalance_freq})"
        )

        # 确定所有行业收益率共有日期
        all_dates = sorted(set.intersection(
            *[set(r.index) for r in sector_returns.values()]
        ))
        if len(all_dates) < 20:
            self.warnings.append(f"共有交易日仅 {len(all_dates)} 天, 数据不足")
            return RotationResult(
                config=self.config,
                sector_returns=sector_returns,
                warnings=self.warnings,
            )

        date_index = pd.DatetimeIndex(all_dates)

        # 调仓日期
        rebalance_dates = self._get_rebalance_dates(date_index)

        self.rotation_log.append(
            f"step: 生成轮动信号 ({len(rebalance_dates)} 个调仓日)"
        )
        signals = self._generate_signals(
            rebalance_dates, sector_returns
        )

        if not signals:
            self.warnings.append("未生成有效调仓信号")
            return RotationResult(
                config=self.config,
                sector_returns=sector_returns,
                warnings=self.warnings,
            )

        self.rotation_log.append("step: 构建行业策略收益率")
        rotation_strategy_returns = self._build_rotation_strategy_returns(
            signals, sector_returns, date_index
        )

        self.rotation_log.append("step: 运行组合回测")
        portfolio_result = self._run_portfolio_backtest(
            rotation_strategy_returns, signals
        )

        # 行业绩效历史
        self.rotation_log.append("step: 计算行业绩效历史")
        perf_history = self._build_sector_perf_history(
            sector_returns, all_dates
        )

        # 统计
        n_signals = len(signals)
        avg_sectors = np.mean([len(s.selected_sectors) for s in signals]) if signals else 0
        turnover = self._calc_turnover(signals)

        result = RotationResult(
            config=self.config,
            portfolio_result=portfolio_result,
            signals=signals,
            sector_performance_history=perf_history,
            sector_returns=sector_returns,
            rotation_log=self.rotation_log,
            warnings=self.warnings,
            n_signals=n_signals,
            avg_sectors_per_signal=avg_sectors,
            sector_turnover=turnover,
        )

        return result

    # ── 生成轮动信号 ────────────────────────────────────────

    def _get_rebalance_dates(self, dates: pd.DatetimeIndex) -> list:
        """确定调仓日期列表

        Args:
            dates: 全量交易日

        Returns:
            调仓日期列表
        """
        freq = self.config.rebalance_freq
        if freq == "weekly":
            # 每周第一个交易日
            reb_dates = [d for d in dates if d.dayofweek == 0]
        elif freq == "monthly":
            # 每月第一个交易日
            seen: set = set()
            reb_dates = []
            for d in dates:
                ym = (d.year, d.month)
                if ym not in seen:
                    seen.add(ym)
                    reb_dates.append(d)
        elif freq == "quarterly":
            # 每季度第一个交易日
            seen: set = set()
            reb_dates = []
            for d in dates:
                yq = (d.year, (d.month - 1) // 3)
                if yq not in seen:
                    seen.add(yq)
                    reb_dates.append(d)
        else:
            reb_dates = [dates[0]]

        return reb_dates

    def _generate_signals(
        self,
        rebalance_dates: list,
        sector_returns: dict[str, pd.Series],
    ) -> list[RotationSignal]:
        """在每个调仓日生成轮动信号

        流程:
          1. 在调仓日 t, 使用截至 t 的数据计算行业绩效
          2. 策略评分 → 排名 → 选 Top-N → 定权重
          3. 记录 RotationSignal

        Args:
            rebalance_dates: 调仓日期列表
            sector_returns: {sector: return_series}

        Returns:
            RotationSignal 列表
        """
        signals = []
        lookback = self.config.lookback_short

        for reb_date in rebalance_dates:
            # 使用截至调仓日的数据
            as_of = reb_date.strftime("%Y-%m-%d") if hasattr(reb_date, "strftime") else str(reb_date)

            # 计算行业绩效快照
            performances = compute_sector_performance_snapshot(
                sector_returns,
                as_of_date=as_of,
                lookback_short=self.config.lookback_short,
                lookback_medium=self.config.lookback_medium,
                lookback_long=self.config.lookback_long,
            )

            if not performances:
                continue

            # 策略评分
            rankings = self.strategy.rank_sectors(performances)

            # 选择行业
            top_n = min(self.config.top_n, len(performances))
            selected = self.strategy.select_sectors(rankings, top_n)

            if len(selected) < self.config.min_sectors:
                continue

            # 定权重
            if self.config.equal_weight:
                w = 1.0 / len(selected)
                weights = {s: w for s in selected}
            else:
                # 按评分加权
                scores = {r["sector"]: r["score"] for r in rankings if r["sector"] in selected}
                total_score = sum(abs(v) for v in scores.values()) or 1.0
                weights = {s: abs(scores[s]) / total_score for s in selected}

            signal = RotationSignal(
                date=as_of,
                strategy_type=self.strategy.name(),
                rankings=rankings[:top_n],
                selected_sectors=selected,
                weights=weights,
                n_available=len(performances),
            )
            signals.append(signal)

        return signals

    # ── 构建收益序列 ────────────────────────────────────────

    def _build_rotation_strategy_returns(
        self,
        signals: list[RotationSignal],
        sector_returns: dict[str, pd.Series],
        all_dates: pd.DatetimeIndex,
    ) -> pd.Series:
        """构建轮动策略日收益率

        在每个调仓周期内, 持有选中行业等权组合, 计算日收益率。

        Args:
            signals: 调仓信号列表
            sector_returns: {sector: return_series}
            all_dates: 全量交易日

        Returns:
            策略日收益率 Series, index=all_dates
        """
        if not signals:
            return pd.Series(index=all_dates, dtype=float).fillna(0.0)

        daily_returns = pd.Series(0.0, index=all_dates)

        for i, signal in enumerate(signals):
            # 当前调仓周期: 从 signal.date 到 next_signal.date
            start_date = pd.Timestamp(signal.date)
            if i + 1 < len(signals):
                end_date = pd.Timestamp(signals[i + 1].date)
            else:
                end_date = all_dates[-1] + pd.Timedelta(days=1)

            # 周期内的交易日
            period_dates = all_dates[(all_dates >= start_date) & (all_dates < end_date)]

            if period_dates.empty:
                continue

            # 持有行业的等权日收益率
            selected = signal.selected_sectors
            period_returns = []

            for d in period_dates:
                d_returns = [
                    sector_returns[s].loc[d]
                    for s in selected
                    if s in sector_returns and d in sector_returns[s].index
                ]
                if d_returns:
                    period_returns.append(np.mean(d_returns))
                else:
                    period_returns.append(0.0)

            daily_returns.loc[period_dates] = period_returns

        return daily_returns

    # ── 组合回测 ────────────────────────────────────────────

    def _run_portfolio_backtest(
        self,
        strategy_returns: pd.Series,
        signals: list[RotationSignal],
    ) -> Optional[object]:
        """使用 V6.4 PortfolioBacktestEngine 进行组合回测

        Args:
            strategy_returns: 轮动策略日收益率
            signals: 调仓信号列表

        Returns:
            PortfolioResult
        """
        try:
            from factor_lab.portfolio import (
                PortfolioSpec,
                BenchmarkSpec,
                PortfolioBacktestEngine,
            )
        except ImportError:
            self.warnings.append("V6.4 PortfolioBacktestEngine 不可用")
            return None

        spec = PortfolioSpec(
            name=self.config.name,
            strategy_returns={self.config.name: strategy_returns},
            weights={self.config.name: 1.0},
            rebalance_freq="none",  # 轮动策略内部已处理再平衡
        )

        engine = PortfolioBacktestEngine(spec)

        benchmark_name = self.config.benchmark_name
        try:
            result = engine.run_with_benchmark(benchmark_name)
            return result
        except Exception as e:
            self.warnings.append(f"组合回测失败: {e}")
            try:
                result = engine.run(benchmark_spec=None)
                return result
            except Exception as e2:
                self.warnings.append(f"无基准回测也失败: {e2}")
                return None

    # ── 辅助 ────────────────────────────────────────────────

    def _build_sector_perf_history(
        self,
        sector_returns: dict[str, pd.Series],
        all_dates: list,
    ) -> pd.DataFrame:
        """构建行业滚动绩效历史"""
        from factor_lab.sector_rotation.sector_performance import (
            build_sector_performance_history,
        )
        return build_sector_performance_history(
            sector_returns, window=self.config.lookback_medium
        )

    def _calc_turnover(self, signals: list[RotationSignal]) -> float:
        """计算行业换手率

        行业换手率 = 每次调仓时变化行业数量 / 持有行业数量 的平均值
        """
        if len(signals) < 2:
            return 0.0

        turnovers = []
        prev_sectors = set(signals[0].selected_sectors)

        for signal in signals[1:]:
            curr_sectors = set(signal.selected_sectors)
            changed = len(prev_sectors.symmetric_difference(curr_sectors))
            total = max(len(prev_sectors), len(curr_sectors), 1)
            turnovers.append(changed / total)
            prev_sectors = curr_sectors

        return float(np.mean(turnovers)) if turnovers else 0.0
