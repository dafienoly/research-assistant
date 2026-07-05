"""因子 Top 组分位数回测 — 选前 20% 等权买入 + 同池等权基准"""
import sys, pandas as pd, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

ADJ_FACTOR = 1.1  # 非ST涨停幅度
ST_ADJ_FACTOR = 1.05  # ST涨停幅度

def is_limit_up(close: float, prev_close: float) -> bool:
    """是否涨停（价格 >= 前收盘 * 涨幅上限）"""
    if pd.isna(close) or pd.isna(prev_close) or prev_close == 0:
        return False
    return close >= prev_close * ADJ_FACTOR - 0.01

def is_limit_down(close: float, prev_close: float) -> bool:
    """是否跌停"""
    if pd.isna(close) or pd.isna(prev_close) or prev_close == 0:
        return False
    return close <= prev_close / ADJ_FACTOR + 0.01

def filter_tradable(df: pd.DataFrame, date_col: str = "date",
                    price_col: str = "close", vol_col: str = "volume",
                    min_volume: int = 100000) -> pd.DataFrame:
    """过滤不可交易股票"""
    # 成交量过低
    if vol_col in df.columns:
        df = df[df[vol_col] >= min_volume].copy()
    # 缺失价格
    if price_col in df.columns:
        df = df[df[price_col].notna()].copy()
    return df

def compute_universe_ew_returns(
    close_prices: pd.DataFrame,
    rebal_dates: list,
    all_dates: list,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10,
) -> pd.Series:
    """计算股票池等权基准（所有可交易股票等权持有，同频率调仓）"""
    daily_ret = close_prices.pct_change()
    rebal_set = set(rebal_dates) if hasattr(rebal_dates, '__iter__') else set()
    ew_rets = pd.Series(0.0, index=all_dates)
    prev_universe = []
    
    for d in all_dates:
        if d not in daily_ret.index:
            ew_rets[d] = 0
            continue
        
        if d in rebal_set:
            # 等权持有所有股票
            today_data = close_prices.loc[d].dropna()
            universe = list(today_data.index)
        else:
            universe = prev_universe
        
        if not universe:
            ew_rets[d] = 0
            prev_universe = universe
            continue
        
        available = [s for s in universe if s in daily_ret.columns]
        if not available:
            ew_rets[d] = 0
            prev_universe = universe
            continue
        
        ret = daily_ret.loc[d, available].mean()
        if d in rebal_set:
            tc = commission_rate + stamp_tax_rate + slippage_bps / 10000
            ret -= tc
        ew_rets[d] = ret
        prev_universe = universe
    
    return ew_rets


def run_top_group_backtest(
    universe_symbols: list,
    factor_series: pd.Series,
    close_prices: pd.DataFrame,
    start_date: str,
    end_date: str,
    top_quantile: float = 0.2,
    rebalance: str = "weekly",
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10,
    market_benchmark_returns: pd.Series = None,
    market_benchmark_name: str = "沪深300",
    strategy_name: str = "TopGroup",
    factor_name: str = "factor",
    factor_expression: str = "",
    universe_name: str = "",
) -> "BacktestResult":
    """因子 Top 组分位数回测
    
    输出:
      - strategy_returns: Top组等权收益
      - universe_ew_returns: 同池等权基准
      - market_benchmark_returns: 市场基准(沪深300)
    """
    from reports.report_schema import BacktestResult, compute_equity_curve
    
    daily_ret = close_prices.pct_change()
    dates = pd.bdate_range(start=start_date, end=end_date)
    dates = dates[dates.isin(close_prices.index)]
    
    if rebalance == "weekly":
        rebal_dates = dates[dates.dayofweek == 0]
    elif rebalance == "monthly":
        rebal_dates = dates[dates.is_month_start]
    else:
        rebal_dates = dates
    rebal_set = set(rebal_dates)
    
    # ── 策略收益 ──
    strat_rets = pd.Series(0.0, index=dates)
    positions_log = []
    prev_portfolio = []
    
    for d in dates:
        tradeable_today = True  # 简化版本，不做逐日ST/涨跌停过滤
        
        if d in rebal_set:
            if d in factor_series.index.get_level_values(0):
                f_day = factor_series.loc[d]
                f_day = f_day.dropna().sort_values(ascending=False)
                n_stocks = max(1, int(len(f_day) * top_quantile))
                portfolio = list(f_day.index[:n_stocks])
            else:
                portfolio = prev_portfolio
        else:
            portfolio = prev_portfolio
        
        if not portfolio:
            strat_rets[d] = 0
            prev_portfolio = portfolio
            continue
        
        if d in daily_ret.index:
            available = [s for s in portfolio if s in daily_ret.columns]
            ret = daily_ret.loc[d, available].mean() if available else 0
            if d in rebal_set:
                tc = commission_rate + stamp_tax_rate + slippage_bps / 10000
                ret -= tc
            strat_rets[d] = ret
        
        prev_portfolio = portfolio
        positions_log.append({"date": str(d.date()), "holdings": len(portfolio)})
    
    # ── 同池等权基准 ──
    ew_rets = compute_universe_ew_returns(
        close_prices, rebal_dates, dates,
        commission_rate, stamp_tax_rate, slippage_bps)
    
    # ── 对齐 ──
    common = dates
    if market_benchmark_returns is not None:
        common = dates.intersection(market_benchmark_returns.index)
        mkt_rets = market_benchmark_returns.reindex(common, fill_value=0)
    else:
        mkt_rets = pd.Series(0.0, index=common)
    
    strat_rets = strat_rets.reindex(common).fillna(0)
    ew_rets = ew_rets.reindex(common).fillna(0)
    
    equity = compute_equity_curve(strat_rets)
    ew_equity = compute_equity_curve(ew_rets)
    mkt_equity = compute_equity_curve(mkt_rets)
    positions_df = pd.DataFrame(positions_log) if positions_log else None
    
    return BacktestResult(
        strategy_returns=strat_rets,
        benchmark_returns=ew_rets,  # QuantStats 基准 = 同池等权
        equity_curve=equity,
        benchmark_curve=ew_equity,
        positions=positions_df,
        factor_name=factor_name,
        factor_expression=factor_expression,
        strategy_name=strategy_name,
        universe=universe_name,
        benchmark_name=market_benchmark_name,
        start_date=start_date,
        end_date=end_date,
        rebalance_freq=rebalance,
        cost_config={"commission_rate": commission_rate, "stamp_tax_rate": stamp_tax_rate, "slippage_bps": slippage_bps},
        # 新增字段（扩展属性存到cost_config或返回对象）
        _extras={
            "universe_ew_returns": ew_rets,
            "market_benchmark_returns": mkt_rets,
            "universe_ew_equity": ew_equity,
            "market_benchmark_equity": mkt_equity,
            "universe_ew_name": "等权基准",
            "market_benchmark_name": market_benchmark_name,
        },
    )