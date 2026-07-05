"""统一回测和指标计算 — canonical 方法

所有模块统一从此处导入, 确保 Sharpe/回撤/收益计算一致。
"""
import numpy as np
import pandas as pd


def calc_sharpe(returns: pd.Series, rf_annual: float = 0.03) -> float:
    """年化 Sharpe Ratio (含无风险利率)

    这是 canonical Sharpe 计算方法, 所有 _quick_backtest 必须使用此函数。
    """
    if len(returns) < 5 or returns.std() < 1e-10:
        return 0.0
    excess = returns - rf_annual / 252
    return float(excess.mean() / excess.std() * np.sqrt(252))


def calc_max_drawdown(equity: pd.Series) -> float:
    """最大回撤"""
    if len(equity) < 2:
        return 0.0
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    return float(dd.min())


def calc_calmar(cagr: float, max_dd: float) -> float:
    """Calmar Ratio (= CAGR / |MaxDD|)"""
    return cagr / abs(max_dd) if abs(max_dd) > 0.01 else 0.0


def calc_cagr(cum_return: float, n_days: int) -> float:
    """年化收益率"""
    if n_days < 20:
        return 0.0
    years = n_days / 252
    return (1 + cum_return) ** (1 / years) - 1 if years > 0 else 0.0


def compute_metrics(returns: pd.Series) -> dict:
    """统一回测指标计算

    返回:
        cumulative_return_pct, max_drawdown_pct, sharpe, calmar, cagr_pct, win_rate_pct, n_days
    """
    returns = returns.fillna(0)
    eq = (1 + returns).cumprod()
    cum_ret = float(eq.iloc[-1]) - 1 if len(eq) > 0 else 0
    dd = calc_max_drawdown(eq)
    sharpe = calc_sharpe(returns)
    cagr = calc_cagr(cum_ret, len(returns))
    calmar = calc_calmar(cagr, dd)
    win_rate = float((returns > 0).mean()) if len(returns) > 0 else 0

    return {
        "cumulative_return_pct": round(cum_ret * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "cagr_pct": round(cagr * 100, 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "n_days": len(returns),
    }
