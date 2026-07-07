"""Strategy Report Metrics V6.5 — 策略报告专用指标计算

提供策略报告所需的额外分析指标：
  - 月度/年度收益表
  - 回撤分析 (最大回撤、持续时间、水下时间)
  - 盈亏分析 (胜率、连续盈亏、盈亏比)
  - 滚动指标 (滚动 Sharpe、波动率)
  - 风险指标 (VaR, CVaR, 偏度, 峰度, Sortino)
  - 收益分布分析

这些指标补充 V6.4 portfolio/metrics.py，面向单策略的深入分析报告。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.strategy_report.spec import (
    MonthlyReturnsTable,
    DrawdownAnalysis,
    WinLossAnalysis,
    RiskMetrics,
)


# ═══════════════════════════════════════════════════════════════════
# 月度 / 年度收益分析
# ═══════════════════════════════════════════════════════════════════


def compute_monthly_returns(
    returns: pd.Series,
    show_all_months: bool = False,
) -> list[MonthlyReturnsTable]:
    """计算月度收益表

    将日收益率序列按月聚合为月度收益，并按年分组。

    Args:
        returns: 日收益率 Series (DatetimeIndex)
        show_all_months: 是否显示所有月份 (包括空月份)

    Returns:
        按年排序的 MonthlyReturnsTable 列表
    """
    if returns.empty:
        return []

    # 确保日期索引
    if not isinstance(returns.index, pd.DatetimeIndex):
        return []

    returns = returns.fillna(0)
    monthly = returns.groupby([returns.index.year, returns.index.month]).apply(
        lambda x: float((1 + x).prod() - 1)
    )

    if monthly.empty:
        return []

    results: dict[int, MonthlyReturnsTable] = {}
    all_months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    for (year, month), ret in monthly.items():
        if year not in results:
            results[year] = MonthlyReturnsTable(year=year)
        month_label = all_months[month - 1]
        results[year].data[month_label] = round(ret * 100, 2)

    # 计算年收益
    for year, table in results.items():
        annual_ret = float(
            (1 + returns[returns.index.year == year]).prod() - 1
        )
        table.annual_return_pct = round(annual_ret * 100, 2)

    # 按年份排序
    result_list = [results[y] for y in sorted(results.keys())]

    # 填充空月份
    if show_all_months:
        for table in result_list:
            for m in all_months:
                if m not in table.data:
                    table.data[m] = 0.0

    return result_list


def compute_annual_returns(returns: pd.Series) -> dict[int, float]:
    """计算年度收益

    Args:
        returns: 日收益率 Series

    Returns:
        年份 → 年收益率 (百分比)
    """
    if returns.empty:
        return {}

    if not isinstance(returns.index, pd.DatetimeIndex):
        return {}

    returns = returns.fillna(0)
    annual = returns.groupby(returns.index.year).apply(
        lambda x: round(float((1 + x).prod() - 1) * 100, 2)
    )
    return annual.to_dict()


# ═══════════════════════════════════════════════════════════════════
# 回撤分析
# ═══════════════════════════════════════════════════════════════════


def compute_drawdown_analysis(
    equity: pd.Series,
    top_n: int = 5,
) -> DrawdownAnalysis:
    """回撤深度分析

    分析回撤的深度、持续时间、水下时间百分比等。
    基于净值曲线 (equity) 而非收益率。

    Args:
        equity: 净值曲线 Series
        top_n: 返回前 N 大回撤期

    Returns:
        DrawdownAnalysis 对象
    """
    if equity.empty or len(equity) < 2:
        return DrawdownAnalysis()

    # 计算回撤序列
    rolling_max = equity.expanding().max()
    drawdown = (equity - rolling_max) / rolling_max
    dd_pct = drawdown * 100

    # 基础统计
    max_dd = float(drawdown.min())
    avg_dd = float(drawdown[drawdown < 0].mean()) if (drawdown < 0).any() else 0.0
    under_water_pct = float((drawdown < 0).mean())

    # 当前回撤
    current_dd = float(drawdown.iloc[-1])

    # 计算回撤期
    drawdown_periods = _find_drawdown_periods(drawdown, min_duration=2)
    drawdown_periods = sorted(
        drawdown_periods, key=lambda x: x["max_drawdown_pct"], reverse=True
    )

    # 最大回撤持续天数
    max_duration = 0
    for dp in drawdown_periods:
        duration = (dp["end_idx"] - dp["start_idx"]) + 1
        dp["duration_days"] = duration
        if dp["max_drawdown_pct"] <= max_dd * 0.95:  # 接近最大回撤
            max_duration = max(max_duration, duration)

    # 平均回撤持续天数
    durations = [dp["duration_days"] for dp in drawdown_periods]
    avg_duration = float(np.mean(durations)) if durations else 0.0

    # 恢复天数 (从最低点恢复到前高)
    recovery_days = _compute_recovery_days(drawdown)

    # 格式化回撤期为百分比
    for dp in drawdown_periods:
        dp["max_drawdown_pct"] = round(dp["max_drawdown_pct"] * 100, 2)
        dp.pop("end_idx", None)
        dp.pop("start_idx", None)

    return DrawdownAnalysis(
        max_drawdown_pct=round(max_dd * 100, 2),
        max_drawdown_duration_days=max_duration,
        avg_drawdown_pct=round(avg_dd * 100, 2),
        avg_drawdown_duration_days=round(avg_duration, 1),
        recovery_days=recovery_days,
        underwater_days_pct=round(under_water_pct * 100, 2),
        current_drawdown_pct=round(current_dd * 100, 2),
        drawdown_periods=drawdown_periods[:top_n],
    )


def _find_drawdown_periods(
    drawdown: pd.Series,
    min_duration: int = 2,
) -> list[dict]:
    """识别回撤期

    Args:
        drawdown: 回撤序列 (<=0)
        min_duration: 最小持续期 (避免噪声回撤)

    Returns:
        [{"peak_date", "trough_date", "max_drawdown_pct", "start_idx", "end_idx"}, ...]
    """
    periods = []
    in_dd = False
    start_idx = 0
    current_min = 0.0

    for i, (idx, val) in enumerate(drawdown.items()):
        if not in_dd and val < 0:
            in_dd = True
            start_idx = i
            current_min = val
        elif in_dd and val < current_min:
            current_min = val
        elif in_dd and val == 0:
            # 恢复
            duration = i - start_idx
            if duration >= min_duration:
                periods.append({
                    "peak_date": str(drawdown.index[start_idx]),
                    "trough_date": str(drawdown.index[i]),
                    "max_drawdown_pct": current_min,
                    "start_idx": start_idx,
                    "end_idx": i,
                })
            in_dd = False

    # 如果最后仍在回撤中
    if in_dd:
        duration = len(drawdown) - start_idx
        if duration >= min_duration:
            periods.append({
                "peak_date": str(drawdown.index[start_idx]),
                "trough_date": str(drawdown.index[-1]),
                "max_drawdown_pct": current_min,
                "start_idx": start_idx,
                "end_idx": len(drawdown) - 1,
            })

    return periods


def _compute_recovery_days(drawdown: pd.Series) -> int:
    """计算从最大回撤恢复所需天数

    0 表示尚未恢复。

    Args:
        drawdown: 回撤序列

    Returns:
        恢复天数, 0 = 未恢复
    """
    if drawdown.empty:
        return 0

    trough_idx = drawdown.idxmin()
    trough_pos = drawdown.index.get_loc(trough_idx)

    # 从最低点之后找恢复到 0
    post_dd = drawdown.iloc[trough_pos:]
    for i, (idx, val) in enumerate(post_dd.items()):
        if val >= 0:
            return i

    return 0


# ═══════════════════════════════════════════════════════════════════
# 盈亏分析
# ═══════════════════════════════════════════════════════════════════


def compute_win_loss_analysis(returns: pd.Series) -> WinLossAnalysis:
    """盈亏分析

    基于日收益率的正负统计。每个交易日视为一"笔交易"。

    Args:
        returns: 日收益率 Series

    Returns:
        WinLossAnalysis 对象
    """
    if returns.empty:
        return WinLossAnalysis()

    returns = returns.fillna(0)
    n = len(returns)
    wins = returns[returns > 0]
    losses = returns[returns < 0]

    n_wins = len(wins)
    n_losses = len(losses)

    # 平均盈亏
    avg_win = float(wins.mean()) if n_wins > 0 else 0.0
    avg_loss = float(losses.mean()) if n_losses > 0 else 0.0

    # 盈亏比
    profit_factor = (
        abs(float(wins.sum() / losses.sum()))
        if losses.sum() != 0
        else float("inf")
    )

    # 连续盈亏
    signs = np.sign(returns.values)
    max_consec_win, max_consec_loss = _max_streak(signs)
    avg_consec_win, avg_consec_loss = _avg_streak(signs)

    return WinLossAnalysis(
        total_trades=n,
        winning_trades=n_wins,
        losing_trades=n_losses,
        win_rate_pct=round(n_wins / n * 100, 2) if n > 0 else 0.0,
        avg_win_pct=round(avg_win * 100, 4),
        avg_loss_pct=round(avg_loss * 100, 4),
        profit_factor=round(profit_factor, 4),
        max_consecutive_wins=max_consec_win,
        max_consecutive_losses=max_consec_loss,
        avg_consecutive_wins=round(avg_consec_win, 2),
        avg_consecutive_losses=round(avg_consec_loss, 2),
    )


def _max_streak(signs: np.ndarray) -> tuple[int, int]:
    """最大连续正/负长度"""
    if len(signs) == 0:
        return 0, 0

    max_pos = 0
    max_neg = 0
    cur_pos = 0
    cur_neg = 0

    for s in signs:
        if s > 0:
            cur_pos += 1
            cur_neg = 0
            max_pos = max(max_pos, cur_pos)
        elif s < 0:
            cur_neg += 1
            cur_pos = 0
            max_neg = max(max_neg, cur_neg)
        else:
            cur_pos = 0
            cur_neg = 0

    return max_pos, max_neg


def _avg_streak(signs: np.ndarray) -> tuple[float, float]:
    """平均连续正/负长度"""
    if len(signs) == 0:
        return 0.0, 0.0

    pos_streaks = []
    neg_streaks = []
    cur_pos = 0
    cur_neg = 0

    for s in signs:
        if s > 0:
            if cur_neg > 0:
                neg_streaks.append(cur_neg)
                cur_neg = 0
            cur_pos += 1
        elif s < 0:
            if cur_pos > 0:
                pos_streaks.append(cur_pos)
                cur_pos = 0
            cur_neg += 1
        else:
            if cur_pos > 0:
                pos_streaks.append(cur_pos)
                cur_pos = 0
            if cur_neg > 0:
                neg_streaks.append(cur_neg)
                cur_neg = 0

    if cur_pos > 0:
        pos_streaks.append(cur_pos)
    if cur_neg > 0:
        neg_streaks.append(cur_neg)

    avg_pos = float(np.mean(pos_streaks)) if pos_streaks else 0.0
    avg_neg = float(np.mean(neg_streaks)) if neg_streaks else 0.0

    return avg_pos, avg_neg


# ═══════════════════════════════════════════════════════════════════
# 风险指标
# ═══════════════════════════════════════════════════════════════════


def compute_risk_metrics(
    returns: pd.Series,
    rf_annual: float = 0.03,
) -> RiskMetrics:
    """计算风险指标

    Args:
        returns: 日收益率 Series
        rf_annual: 年化无风险利率

    Returns:
        RiskMetrics 对象
    """
    if returns.empty or len(returns) < 5:
        return RiskMetrics()

    returns = returns.fillna(0)
    n = len(returns)

    # VaR (95%)
    var_95 = float(np.percentile(returns, 5))

    # CVaR (95%) — 尾部均值
    tail = returns[returns <= var_95]
    cvar_95 = float(tail.mean()) if len(tail) > 0 else var_95

    # 偏度 & 峰度
    skew = float(returns.skew()) if n > 2 else 0.0
    kurt = float(returns.kurtosis()) if n > 3 else 0.0

    # 下行波动率 (仅负收益)
    downside = returns[returns < 0]
    downside_vol = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else 0.0

    # Sortino 比率
    rf_daily = rf_annual / 252
    excess = returns - rf_daily
    ann_excess = float(excess.mean() * 252)
    sortino = ann_excess / downside_vol if downside_vol > 1e-10 else 0.0

    # Ulcer 指数
    rolling_max = returns.expanding().max()
    drawdown = (returns - rolling_max) / rolling_max
    ulcer = float(np.sqrt((drawdown ** 2).mean()))

    # Pain 指数
    pain = float(drawdown[drawdown < 0].mean()) if (drawdown < 0).any() else 0.0

    # 尾部比率 (95分位 / 5分位)
    top_5 = float(np.percentile(returns, 95))
    bottom_5 = float(np.percentile(returns, 5))
    tail_ratio = abs(top_5 / bottom_5) if bottom_5 != 0 else 0.0

    return RiskMetrics(
        var_95_pct=round(var_95 * 100, 4),
        cvar_95_pct=round(cvar_95 * 100, 4),
        skewness=round(skew, 4),
        kurtosis=round(kurt, 4),
        downside_deviation_pct=round(downside_vol * 100, 2),
        sortino_ratio=round(sortino, 4),
        ulcer_index=round(ulcer * 100, 2),
        pain_index=round(pain * 100, 2),
        tail_ratio=round(tail_ratio, 4),
        daily_value_at_risk_pct=round(var_95 * 100, 4),
    )


# ═══════════════════════════════════════════════════════════════════
# 滚动指标
# ═══════════════════════════════════════════════════════════════════


def compute_rolling_metrics(
    returns: pd.Series,
    window: int = 60,
    rf_annual: float = 0.03,
) -> dict[str, pd.Series]:
    """计算滚动指标

    Args:
        returns: 日收益率 Series
        window: 滚动窗口大小 (交易日)
        rf_annual: 年化无风险利率

    Returns:
        {
            "rolling_sharpe": 滚动 Sharpe,
            "rolling_volatility": 滚动年化波动率,
            "rolling_return": 滚动年化收益,
        }
    """
    if returns.empty or len(returns) < window:
        return {}

    returns = returns.fillna(0)

    # 滚动年化波动率
    rolling_vol = returns.rolling(window).std() * np.sqrt(252)

    # 滚动年化收益
    rolling_ret = returns.rolling(window).apply(
        lambda x: float((1 + x).prod() ** (252 / len(x)) - 1)
        if len(x) >= window // 2
        else 0.0
    )

    # 滚动 Sharpe
    rf_daily = rf_annual / 252
    rolling_excess = returns.rolling(window).mean() - rf_daily
    rolling_sharpe = (rolling_excess * 252) / (returns.rolling(window).std() * np.sqrt(252))
    rolling_sharpe = rolling_sharpe.fillna(0)

    return {
        "rolling_sharpe": rolling_sharpe,
        "rolling_volatility": rolling_vol,
        "rolling_return": rolling_ret,
    }


# ═══════════════════════════════════════════════════════════════════
# 收益分布
# ═══════════════════════════════════════════════════════════════════


def compute_return_distribution(
    returns: pd.Series,
    n_bins: int = 10,
) -> dict:
    """计算收益分布

    Args:
        returns: 日收益率 Series
        n_bins: 分桶数

    Returns:
        {
            "bins": [bin_labels],
            "counts": [count_per_bin],
            "frequencies": [frequency_per_bin],
            "mean": 平均日收益,
            "median": 中位日收益,
            "std": 日收益标准差,
            "min": 最小,
            "max": 最大,
            "positive_pct": 正收益占比,
            "negative_pct": 负收益占比,
            "zero_pct": 零收益占比,
        }
    """
    if returns.empty:
        return {}

    returns = returns.fillna(0)
    values = returns.values * 100  # 转为百分比

    hist, edges = np.histogram(values, bins=n_bins)
    bin_labels = [f"{edges[i]:.2f}~{edges[i+1]:.2f}%" for i in range(len(edges) - 1)]

    return {
        "bins": bin_labels,
        "counts": hist.tolist(),
        "frequencies": (hist / len(values)).tolist(),
        "mean": round(float(values.mean()), 4),
        "median": round(float(np.median(values)), 4),
        "std": round(float(values.std()), 4),
        "min": round(float(values.min()), 4),
        "max": round(float(values.max()), 4),
        "positive_pct": round(float((values > 0).mean()) * 100, 2),
        "negative_pct": round(float((values < 0).mean()) * 100, 2),
        "zero_pct": round(float((values == 0).mean()) * 100, 2),
    }
