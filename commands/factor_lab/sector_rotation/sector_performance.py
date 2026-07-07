"""Sector Performance V6.8 — 行业绩效与评分计算

核心功能:
  1. 使用 IndustryMapper 获取股票→行业映射
  2. 计算行业层面收益率 (等权聚合)
  3. 计算行业动量、波动率、资金流评分
  4. 输出行业绩效快照与历史序列

设计理念:
  - 基于已存在的 IndustryMapper, 不重复造轮子
  - 等权聚合行业收益 (无需市值数据, 适用于全 A 股)
  - 支持多种评分维度: 动量/波动率/资金流
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.sector_rotation.spec import SectorPerformance

CST = timezone(timedelta(hours=8))


def get_sector_mapping() -> dict[str, str]:
    """获取股票→行业映射

    Returns:
        {symbol: sector_name, ...} 如 {"000001": "银行", ...}
    """
    try:
        from factor_lab.alpha.industry_mapper import IndustryMapper
        mapper = IndustryMapper()
        return mapper.get_industry_map()
    except Exception:
        # 兜底: 返回空映射
        return {}


def get_stocks_by_sector() -> dict[str, list[str]]:
    """获取行业→股票列表

    Returns:
        {sector_name: [symbol, ...], ...}
    """
    try:
        from factor_lab.alpha.industry_mapper import IndustryMapper
        mapper = IndustryMapper()
        return mapper.get_stocks_by_industry()
    except Exception:
        return {}


def get_sector_list() -> list[str]:
    """获取所有行业列表

    Returns:
        [sector_name, ...]
    """
    try:
        from factor_lab.alpha.industry_mapper import IndustryMapper
        mapper = IndustryMapper()
        return mapper.get_industry_list()
    except Exception:
        return []


def get_sector_stock_count() -> dict[str, int]:
    """获取各行业股票数量

    Returns:
        {sector_name: count, ...}
    """
    try:
        from factor_lab.alpha.industry_mapper import IndustryMapper
        mapper = IndustryMapper()
        return mapper.get_industry_count()
    except Exception:
        return {}


def compute_sector_returns(
    stock_returns: pd.DataFrame,
    sector_mapping: dict[str, str],
    method: str = "equal_weight",
) -> dict[str, pd.Series]:
    """计算行业层面收益率序列

    将个股收益率按行业聚合为行业收益率。

    Args:
        stock_returns: DataFrame, index=date, columns=symbol, values=日收益率
        sector_mapping: {symbol: sector_name} 行业映射
        method: "equal_weight" (等权) / "mean" (均值)

    Returns:
        {sector_name: pd.Series(returns, index=date), ...}
    """
    if stock_returns is None or stock_returns.empty:
        return {}

    # 构建行业→股票倒排索引
    sector_stocks: dict[str, list[str]] = {}
    for symbol, sector in sector_mapping.items():
        if symbol in stock_returns.columns:
            sector_stocks.setdefault(sector, []).append(symbol)

    # 计算行业收益率
    sector_returns: dict[str, pd.Series] = {}
    for sector, symbols in sector_stocks.items():
        available = [s for s in symbols if s in stock_returns.columns]
        if len(available) < 1:
            continue

        sector_data = stock_returns[available]

        if method == "equal_weight":
            sector_ret = sector_data.mean(axis=1, skipna=True)
        else:
            sector_ret = sector_data.mean(axis=1, skipna=True)

        sector_ret.name = sector
        sector_returns[sector] = sector_ret

    return sector_returns


def compute_sector_performance_snapshot(
    sector_returns: dict[str, pd.Series],
    as_of_date: Optional[str] = None,
    lookback_short: int = 20,
    lookback_medium: int = 60,
    lookback_long: int = 120,
) -> list[SectorPerformance]:
    """计算当前行业绩效快照

    在 as_of_date 时刻, 计算各行业的多维度评分。

    Args:
        sector_returns: {sector: return_series}
        as_of_date: 截断日期 (默认最新)
        lookback_short: 短期窗口
        lookback_medium: 中期窗口
        lookback_long: 长期窗口

    Returns:
        按 composite_score 降序排列的 SectorPerformance 列表
    """
    performances: list[SectorPerformance] = []

    for sector, ret_series in sector_returns.items():
        if ret_series is None or len(ret_series) < max(lookback_short, 20):
            continue

        # 截取到 as_of_date
        if as_of_date is not None:
            ret_series = ret_series.loc[:as_of_date]

        prices = (1 + ret_series).cumprod()
        total_ret = prices.iloc[-1] / prices.iloc[0] - 1 if len(prices) > 1 else 0.0

        # 各窗口收益
        r_short = _window_return(ret_series, lookback_short)
        r_medium = _window_return(ret_series, lookback_medium)
        r_long = _window_return(ret_series, lookback_long)

        # 波动率 (日化)
        vol = ret_series.std() if len(ret_series) > 5 else 0.0

        # 夏普比 (年化)
        daily_mean = ret_series.mean()
        sharpe = (daily_mean / vol * np.sqrt(252)) if vol > 1e-10 else 0.0

        # 动量评分: 短期×0.5 + 中期×0.3 + 长期×0.2
        momentum = r_short * 0.5 + r_medium * 0.3 + r_long * 0.2

        perf = SectorPerformance(
            sector_name=sector,
            stock_count=_get_stock_count_for_sector(sector),
            return_short=r_short,
            return_medium=r_medium,
            return_long=r_long,
            momentum_score=momentum,
            volatility=vol,
            sharpe_ratio=sharpe,
            fund_flow_score=0.0,  # 资金流维度需外部数据
            composite_score=momentum,  # 默认 composite = momentum
        )
        performances.append(perf)

    # 按 composite_score 降序
    performances.sort(key=lambda x: x.composite_score, reverse=True)
    return performances


def _window_return(ret_series: pd.Series, window: int) -> float:
    """计算最近 window 个交易日的累计收益"""
    n = min(window, len(ret_series))
    if n < 5:
        return 0.0
    recent = ret_series.iloc[-n:]
    return float((1 + recent).prod() - 1)


def _get_stock_count_for_sector(sector_name: str) -> int:
    """获取行业股票数量"""
    try:
        counts = get_sector_stock_count()
        return counts.get(sector_name, 0)
    except Exception:
        return 0


def compute_sector_rankings(
    performances: list[SectorPerformance],
    top_n: int = 5,
) -> list[dict]:
    """生成行业排名列表 (用于 RotationSignal)

    Args:
        performances: SectorPerformance 列表
        top_n: 返回 Top-N

    Returns:
        [{"sector": str, "composite_score": float, "momentum": float, ...}, ...]
    """
    rankings = []
    for perf in performances:
        rankings.append({
            "sector": perf.sector_name,
            "composite_score": round(perf.composite_score, 4),
            "momentum": round(perf.momentum_score, 4),
            "return_short_pct": round(perf.return_short * 100, 2),
            "return_medium_pct": round(perf.return_medium * 100, 2),
            "return_long_pct": round(perf.return_long * 100, 2),
            "sharpe": round(perf.sharpe_ratio, 2),
            "volatility_pct": round(perf.volatility * 100, 2),
            "stock_count": perf.stock_count,
        })

    rankings.sort(key=lambda x: x["composite_score"], reverse=True)
    return rankings[:top_n]


def build_sector_performance_history(
    sector_returns: dict[str, pd.Series],
    window: int = 60,
) -> pd.DataFrame:
    """构建行业绩效历史 DataFrame

    计算 rolling window 内的行业累计收益序列。

    Args:
        sector_returns: {sector: return_series}
        window: 滚动窗口

    Returns:
        DataFrame, index=date, columns=sector, values=窗口累计收益
    """
    if not sector_returns:
        return pd.DataFrame()

    df = pd.DataFrame(sector_returns)
    if df.empty:
        return df

    # 计算滚动窗口累计收益
    rolling_ret = df.rolling(window=min(window, len(df)), min_periods=20).apply(
        lambda x: float((1 + x).prod() - 1), raw=True
    )
    return rolling_ret
