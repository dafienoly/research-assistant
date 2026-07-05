"""A股真实交易约束回测器

实现 AShareBacktester — 考虑涨停/跌停/停牌/ST/最小成交额/
100股整数倍/单票权重上限/T+1 等真实 A 股交易约束的回测引擎。

使用方式:
    from factor_lab.strategy.execution_aware_backtester import AShareBacktester

返回:
    {
        'returns': pd.Series (日收益率),
        'equity_curve': pd.Series,
        'positions': pd.DataFrame (调仓日持仓),
        'trades': pd.DataFrame (交易流水),
        'metrics': {cumulative_return_pct, max_drawdown_pct, sharpe, calmar, cagr_pct, win_rate_pct},
        'turnover': float (年化换手率),
        'n_trades': int,
        'execution_log': [警告/错误列表],
    }

注意:
    所有数据缺失必须标记 partial, 不允许 silent fallback。
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.metrics import compute_metrics


# ═══════════════════════════════════════════════════════════
# 涨停/跌停判断（独立函数，可直接外部调用）
# ═══════════════════════════════════════════════════════════

def _is_limit_up(close: float, prev_close: float) -> bool:
    """判断是否涨停 (>= 前收盘 * 1.095, 容忍撮合价差)"""
    if pd.isna(close) or pd.isna(prev_close) or prev_close <= 0:
        return False
    return close >= prev_close * 1.095 - 0.005


def _is_limit_down(close: float, prev_close: float) -> bool:
    """判断是否跌停 (<= 前收盘 * 0.905, 容忍撮合价差)"""
    if pd.isna(close) or pd.isna(prev_close) or prev_close <= 0:
        return False
    return close <= prev_close * 0.905 + 0.005


# ═══════════════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════════════

def _infer_st(symbol: str, execution_log: list, date: pd.Timestamp | None = None) -> bool:
    """通过 symbol 后缀推断是否 ST

    在没有 ST 标记字段时的 fallback 判断。
    检查 symbol 中是否包含 ST/*ST 标记。
    若无法判断，记录 warning 并返回 False。
    """
    if not isinstance(symbol, str) or len(symbol) < 3:
        return False

    # 提取 A 股代码 (前6位数字)
    code = "".join(ch for ch in symbol if ch.isdigit())[:6] if any(ch.isdigit() for ch in symbol) else ""

    # 常见 ST 标记 — 严格匹配
    upper = symbol.upper().strip()
    if "*ST" in upper:
        return True
    if " S T " in upper:
        return True

    # "ST" 作为独立标记（前后是非字母或边界）
    import re
    if re.search(r'(?:^|[\s.\-_\[])[SsTt]{2}(?:$|[\s.\-_\]]|\.)', symbol):
        return True

    # 宽松: ST 作为子串出现且 symbol 较短（含 ST 标记的股票代码通常较短）
    if "ST" in upper and len(symbol) <= 12:
        return True

    # A 股代码段 (6 位数字) 无法判断则警告
    if len(code) >= 6 and code.isdigit():
        _log_once(
            execution_log,
            f"partial: 无法通过 symbol 后缀判断 {symbol} 是否 ST (无ST标记字段), "
            f"默认视为非 ST",
        )

    return False


def _log_once(execution_log: list, msg: str) -> None:
    """避免重复日志"""
    if msg not in execution_log:
        execution_log.append(msg)


def _require_not_empty(df: pd.DataFrame, name: str) -> None:
    if df is None or df.empty:
        raise ValueError(f"{name} 不能为空")


def _get_rebalance_dates(all_dates: list[pd.Timestamp], rebalance: str) -> list[pd.Timestamp]:
    """根据调仓频率生成调仓日列表"""
    if rebalance == "daily":
        return list(all_dates)
    elif rebalance == "weekly":
        return [d for d in all_dates if d.dayofweek == 0]
    elif rebalance == "monthly":
        # 每月第一个交易日
        seen: set[tuple[int, int]] = set()
        result: list[pd.Timestamp] = []
        for d in all_dates:
            ym = (d.year, d.month)
            if ym not in seen:
                seen.add(ym)
                result.append(d)
        return result
    else:
        raise ValueError(f"不支持的调仓频率: {rebalance}")


def _calc_commission(
    amount: float,
    commission_rate: float,
    min_commission: float,
) -> float:
    """计算佣金（双向收取）"""
    comm = amount * commission_rate
    return max(comm, min_commission)


def _calc_stamp_tax(amount: float, rate: float) -> float:
    """计算印花税（仅卖出收取）"""
    return amount * rate


def _calc_slippage(amount: float, slippage_bps: int) -> float:
    """计算滑点成本"""
    return amount * slippage_bps / 10000


def _calc_trade_cost(
    amount: float,
    is_buy: bool,
    commission_rate: float,
    min_commission: float,
    stamp_tax_rate_sell: float,
    slippage_bps: int,
) -> float:
    """计算单笔交易总成本"""
    comm = _calc_commission(amount, commission_rate, min_commission)
    stamp = _calc_stamp_tax(amount, stamp_tax_rate_sell) if not is_buy else 0.0
    slip = _calc_slippage(amount, slippage_bps)
    return comm + stamp + slip


def _empty_result(execution_log: list[str]) -> dict:
    return {
        "returns": pd.Series(dtype=float),
        "equity_curve": pd.Series(dtype=float),
        "positions": pd.DataFrame(),
        "trades": pd.DataFrame(),
        "metrics": {
            "cumulative_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "calmar": 0.0,
            "cagr_pct": 0.0,
            "win_rate_pct": 0.0,
        },
        "turnover": 0.0,
        "n_trades": 0,
        "execution_log": execution_log,
    }


def _record_positions(
    positions_records: list[dict],
    holdings: dict[str, dict],
    date: pd.Timestamp,
) -> None:
    """记录当前持仓快照"""
    positions_records.append({
        "date": date,
        "holdings": {sym: pos["quantity"] for sym, pos in holdings.items() if pos["quantity"] > 0},
        "n_holdings": sum(1 for p in holdings.values() if p["quantity"] > 0),
    })


# ═══════════════════════════════════════════════════════════
# AShareBacktester
# ═══════════════════════════════════════════════════════════

class AShareBacktester:
    """A 股真实交易约束回测器

    Parameters
    ----------
    close_pivot : pd.DataFrame
        日收盘价 pivot table, index=date, columns=symbol
    open_pivot : pd.DataFrame, optional
        日开盘价 pivot table
    high_pivot : pd.DataFrame, optional
        日最高价 pivot table
    low_pivot : pd.DataFrame, optional
        日最低价 pivot table
    volume_pivot : pd.DataFrame, optional
        日成交量 pivot table
    amount_pivot : pd.DataFrame, optional
        日成交额 pivot table
    """

    def __init__(
        self,
        close_pivot: pd.DataFrame,
        open_pivot: pd.DataFrame | None = None,
        high_pivot: pd.DataFrame | None = None,
        low_pivot: pd.DataFrame | None = None,
        volume_pivot: pd.DataFrame | None = None,
        amount_pivot: pd.DataFrame | None = None,
    ):
        # 必需数据
        _require_not_empty(close_pivot, "close_pivot")
        self.close = close_pivot.copy()

        # 可选数据
        self.open = open_pivot.copy() if open_pivot is not None else None
        self.high = high_pivot.copy() if high_pivot is not None else None
        self.low = low_pivot.copy() if low_pivot is not None else None
        self.volume = volume_pivot.copy() if volume_pivot is not None else None
        self.amount = amount_pivot.copy() if amount_pivot is not None else None

        # 默认交易成本（A股真实标准）
        self.commission_rate = 0.0003       # 万3
        self.min_commission = 5.0           # 最低5元
        self.stamp_tax_rate_sell = 0.001    # 卖出千1
        self.slippage_bps = 10              # 10bps 滑点

    # ──────────────────────────────────────────
    # 交易成本设置
    # ──────────────────────────────────────────

    def set_cost(
        self,
        commission_rate: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax_rate_sell: float = 0.001,
        slippage_bps: int = 10,
    ) -> None:
        """设置交易成本参数"""
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate_sell = stamp_tax_rate_sell
        self.slippage_bps = slippage_bps

    # ──────────────────────────────────────────
    # 主回测入口
    # ──────────────────────────────────────────

    def run(
        self,
        factor_df: pd.DataFrame,
        factor_col: str,
        top_n: int = 20,
        rebalance: str = "monthly",
        start_date: str | None = None,
        end_date: str | None = None,
        limit_up_exclude: bool = True,
        limit_down_exclude: bool = False,
        suspend_exclude: bool = True,
        st_exclude: bool = True,
        min_amount: float = 1_000_000,
        lot_size: int = 100,
        max_single_weight: float = 0.15,
        max_holdings: int = 20,
    ) -> dict:
        """执行回测

        Parameters
        ----------
        factor_df : pd.DataFrame
            含 date, symbol, factor_col 列的因子数据
        factor_col : str
            因子值列名
        top_n : int
            每次调仓选股数
        rebalance : str
            调仓频率: 'monthly', 'weekly', 'daily'
        start_date, end_date : str, optional
            回测日期范围
        limit_up_exclude : bool
            涨停不可买
        limit_down_exclude : bool
            跌停不可卖（调仓时可能持有）
        suspend_exclude : bool
            停牌排除
        st_exclude : bool
            ST 排除
        min_amount : float
            最低日成交额（元）
        lot_size : int
            最小交易单位（股）, A股为100
        max_single_weight : float
            单票最大权重
        max_holdings : int
            最大持仓数

        Returns
        -------
        dict
        """
        execution_log: list[str] = []

        # ── 参数校验 ──
        if top_n <= 0:
            execution_log.append("partial: top_n 必须 > 0")
            return _empty_result(execution_log)
        if max_single_weight <= 0 or max_single_weight > 1:
            execution_log.append("partial: max_single_weight 必须在 (0,1]")
            return _empty_result(execution_log)

        # ── 准备日期序列 ──
        factor_df = factor_df.copy()
        factor_df["date"] = pd.to_datetime(factor_df["date"])
        all_dates = sorted(factor_df["date"].unique())

        if start_date:
            all_dates = [d for d in all_dates if d >= pd.Timestamp(start_date)]
        if end_date:
            all_dates = [d for d in all_dates if d <= pd.Timestamp(end_date)]

        if len(all_dates) < 2:
            execution_log.append("partial: 有效交易日不足2天, 无法回测")
            return _empty_result(execution_log)

        # 调仓日
        rebal_dates = _get_rebalance_dates(all_dates, rebalance)
        if not rebal_dates:
            execution_log.append("partial: 无调仓日, 返回空结果")
            return _empty_result(execution_log)
        # 首个调仓日之前的日期也能正常计算收益（空仓）
        rebal_set = set(rebal_dates)

        # ── 对齐数据日期 ──
        close = self.close.reindex(all_dates)
        open_ = self.open.reindex(all_dates) if self.open is not None else None

        # 前收盘（昨日收盘价用于涨跌停判断）
        prev_close = close.shift(1)

        # ── 状态变量 ──
        capital = 1_000_000.0  # 初始资金
        cash = capital
        holdings: dict[str, dict] = {}  # symbol -> {quantity, cost_price, buy_date, last_close}

        daily_returns: list[float] = []
        equity_series: list[float] = []
        positions_records: list[dict] = []
        trade_records: list[dict] = []

        total_buy_amount = 0.0
        total_sell_amount = 0.0

        # ST 缓存 (避免重复推断)
        st_cache: dict[str, bool] = {}

        # ── 获取日成交额 pivot （用于 min_amount 过滤） ──
        amount_pivot = (
            self.amount.reindex(all_dates)
            if self.amount is not None
            else None
        )

        # ── 逐日回测 ──
        for i, d in enumerate(all_dates):
            # 当日行情
            day_close: pd.Series = close.loc[d] if d in close.index else pd.Series(dtype=float)
            day_open: pd.Series = open_.loc[d] if open_ is not None and d in open_.index else pd.Series(dtype=float)
            day_amount: pd.Series = amount_pivot.loc[d] if amount_pivot is not None and d in amount_pivot.index else pd.Series(dtype=float)
            day_prev_close: pd.Series = prev_close.loc[d] if d in prev_close.index else pd.Series(dtype=float)

            # ── 1. 计算持仓市值 ──
            position_value = 0.0
            for sym, pos in list(holdings.items()):
                price = day_close.get(sym, np.nan)
                if pd.isna(price):
                    # 停牌/缺失, 使用上日收盘估值（标记 partial）
                    last = pos.get("last_close")
                    if last is not None and not pd.isna(last):
                        price = last
                        execution_log.append(
                            f"partial: {d.date()} {sym} 收盘价缺失, "
                            f"使用前日收盘 {price:.2f} 估值"
                        )
                    else:
                        price = 0.0
                pos["last_price"] = price  # 更新最新价
                pos["last_close"] = price
                position_value += pos["quantity"] * price

            total_value = cash + position_value

            # ── 2. 日收益率 ──
            daily_return = 0.0
            if i > 0:
                prev_total = equity_series[-1] if equity_series else capital
                if prev_total > 0:
                    daily_return = total_value / prev_total - 1
            daily_returns.append(daily_return)
            equity_series.append(total_value)

            # ── 3. 调仓日执行 ──
            if d in rebal_set:
                # 3a. 获取当日因子值
                day_factor_data = factor_df[factor_df["date"] == d].copy()
                if day_factor_data.empty:
                    execution_log.append(
                        f"partial: {d.date()} 无因子数据, 跳过调仓"
                    )
                    _record_positions(positions_records, holdings, d)
                    continue

                day_factor_data = day_factor_data.dropna(subset=[factor_col])
                day_factor_data = day_factor_data.sort_values(
                    factor_col, ascending=False
                )

                # 3b. 过滤候选票
                skipped: dict[str, list[str]] = {
                    "st": [],
                    "suspend": [],
                    "limit_up": [],
                    "limit_down": [],
                    "low_amount": [],
                    "missing_data": [],
                    "no_price": [],
                }
                candidates: list[tuple[str, float, float]] = []  # (symbol, factor_val, buy_price)

                for _, row in day_factor_data.iterrows():
                    sym = row["symbol"]

                    # 最多取 top_n 个候选
                    if len(candidates) >= top_n:
                        break

                    # ST 推断 + 排除
                    if st_exclude and sym not in st_cache:
                        st_cache[sym] = _infer_st(sym, execution_log, d)
                    if st_exclude and st_cache.get(sym, False):
                        skipped["st"].append(sym)
                        continue

                    # 停牌/价格缺失 排除
                    close_price = day_close.get(sym, np.nan)
                    if pd.isna(close_price) or close_price <= 0:
                        if suspend_exclude:
                            skipped["suspend"].append(sym)
                        else:
                            skipped["no_price"].append(sym)
                        continue

                    # 涨停不可买
                    prev_px = day_prev_close.get(sym, np.nan)
                    if limit_up_exclude and not pd.isna(prev_px) and prev_px > 0:
                        if _is_limit_up(close_price, prev_px):
                            skipped["limit_up"].append(sym)
                            continue

                    # 跌停不可卖 (影响卖方; 买入时通常不影响, 但跌停票当日买入也有风险)
                    if limit_down_exclude and not pd.isna(prev_px) and prev_px > 0:
                        if _is_limit_down(close_price, prev_px):
                            skipped["limit_down"].append(sym)
                            continue

                    # 最低成交额过滤
                    amt = day_amount.get(sym, np.nan)
                    if pd.isna(amt) or amt < min_amount:
                        skipped["low_amount"].append(sym)
                        continue

                    # 开盘价缺失（用于买入定价）
                    open_price = day_open.get(sym, np.nan)
                    if pd.isna(open_price) or open_price <= 0:
                        skipped["missing_data"].append(sym)
                        continue

                    candidates.append((sym, row[factor_col], open_price))

                # 记录过滤统计
                for reason, syms in skipped.items():
                    if syms:
                        execution_log.append(
                            f"partial: {d.date()} {reason}排除 {len(syms)} 只"
                        )

                if not candidates:
                    execution_log.append(
                        f"partial: {d.date()} 无可用候选票, 空仓持有现金"
                    )
                    _record_positions(positions_records, holdings, d)
                    continue

                # ── T+1 限制: 先卖后买 ──
                # 确定目标持仓 set
                target_symbols = {sym for sym, _, _ in candidates[:top_n]}

                # 收集需要卖出的持仓 (当前有但不在目标中的)
                sell_list = []
                for sym, pos in holdings.items():
                    if pos["quantity"] > 0 and sym not in target_symbols:
                        # 检查跌停不可卖
                        sell_price = day_close.get(sym, np.nan)
                        if pd.isna(sell_price) or sell_price <= 0:
                            execution_log.append(
                                f"partial: {d.date()} {sym} 卖出价缺失, 跳过卖出"
                            )
                            continue

                        prev_px = day_prev_close.get(sym, np.nan)
                        if limit_down_exclude and not pd.isna(prev_px) and prev_px > 0:
                            if _is_limit_down(sell_price, prev_px):
                                execution_log.append(
                                    f"partial: {d.date()} {sym} 跌停不可卖, 暂持"
                                )
                                continue

                        sell_list.append((sym, pos["quantity"], sell_price))

                # ── 执行卖出 ──
                sell_proceeds = 0.0
                for sym, qty, price in sell_list:
                    sell_amount = qty * price
                    cost = _calc_trade_cost(
                        sell_amount,
                        is_buy=False,
                        commission_rate=self.commission_rate,
                        min_commission=self.min_commission,
                        stamp_tax_rate_sell=self.stamp_tax_rate_sell,
                        slippage_bps=self.slippage_bps,
                    )
                    net_proceeds = sell_amount - cost
                    cash += net_proceeds
                    total_sell_amount += sell_amount

                    trade_records.append({
                        "date": d,
                        "symbol": sym,
                        "action": "SELL",
                        "price": round(price, 4),
                        "quantity": qty,
                        "amount": round(sell_amount, 2),
                        "cost": round(cost, 2),
                        "net_proceeds": round(net_proceeds, 2),
                    })

                    # 清理持仓
                    del holdings[sym]

                # ── 执行买入 ──
                if candidates:
                    # 计算可用现金（预留一点余量避免浮点误差）
                    available_cash = cash * 0.999

                    # 目标池（不超过 top_n）
                    buy_targets = candidates[:max_holdings]

                    # 如果已有持仓是目标持仓，不重复买入
                    existing_target_holdings = {
                        sym for sym in holdings if holdings[sym]["quantity"] > 0
                    }

                    # 计算权重分配
                    buy_targets_filtered = [
                        (sym, fv, bp)
                        for sym, fv, bp in buy_targets
                        if sym not in existing_target_holdings
                    ]

                    if buy_targets_filtered:
                        n_buy = min(len(buy_targets_filtered), max_holdings)
                        # 等权分配
                        per_target_cash = available_cash / n_buy

                        for sym, fv, buy_price in buy_targets_filtered[:n_buy]:
                            # 计算可买数量（考虑单票权重上限）
                            max_qty_by_weight = int(
                                (total_value * max_single_weight) / buy_price / lot_size
                            ) * lot_size

                            # 等权分配数量
                            target_qty = int(per_target_cash / buy_price / lot_size) * lot_size

                            # 取较小值
                            target_qty = min(target_qty, max_qty_by_weight)

                            if target_qty <= 0:
                                # 至少买一个 lot
                                target_qty = int(per_target_cash / buy_price / lot_size) * lot_size
                                if target_qty <= 0:
                                    execution_log.append(
                                        f"partial: {d.date()} {sym} 资金不足买入1手"
                                    )
                                    continue

                            buy_amount = target_qty * buy_price
                            cost = _calc_trade_cost(
                                buy_amount,
                                is_buy=True,
                                commission_rate=self.commission_rate,
                                min_commission=self.min_commission,
                                stamp_tax_rate_sell=self.stamp_tax_rate_sell,
                                slippage_bps=self.slippage_bps,
                            )
                            total_cost = buy_amount + cost

                            if total_cost > cash:
                                # 资金不足, 减少到能买的量
                                max_qty = int((cash * 0.99) / buy_price / lot_size) * lot_size
                                if max_qty <= 0:
                                    execution_log.append(
                                        f"partial: {d.date()} {sym} 现金不足买入"
                                    )
                                    continue
                                target_qty = max_qty
                                buy_amount = target_qty * buy_price
                                cost = _calc_trade_cost(
                                    buy_amount,
                                    is_buy=True,
                                    commission_rate=self.commission_rate,
                                    min_commission=self.min_commission,
                                    stamp_tax_rate_sell=self.stamp_tax_rate_sell,
                                    slippage_bps=self.slippage_bps,
                                )
                                total_cost = buy_amount + cost

                            cash -= total_cost
                            total_buy_amount += buy_amount

                            holdings[sym] = {
                                "quantity": target_qty,
                                "cost_price": buy_price,
                                "cost_total": buy_amount,
                                "buy_date": d,
                                "last_close": buy_price,
                                "last_price": buy_price,
                            }

                            trade_records.append({
                                "date": d,
                                "symbol": sym,
                                "action": "BUY",
                                "price": round(buy_price, 4),
                                "quantity": target_qty,
                                "amount": round(buy_amount, 2),
                                "cost": round(cost, 2),
                                "factor_value": round(fv, 6),
                            })

                # 记录调仓日持仓
                _record_positions(positions_records, holdings, d)

            # 非调仓日: 仅记录持仓快照
            else:
                _record_positions(positions_records, holdings, d)

        # ══════════════════════════════════════════
        # 构建返回结果
        # ══════════════════════════════════════════

        # 收益率序列
        returns = pd.Series(daily_returns, index=all_dates, name="strategy_return")

        # 净值曲线
        equity = pd.Series(equity_series, index=all_dates, name="equity")

        # 指标
        metrics = compute_metrics(returns)

        # 持仓 DataFrame
        positions_df = pd.DataFrame(positions_records) if positions_records else pd.DataFrame()
        if not positions_df.empty:
            positions_df = positions_df.set_index("date") if "date" in positions_df.columns else positions_df

        # 交易流水 DataFrame
        trades_df = pd.DataFrame(trade_records) if trade_records else pd.DataFrame()
        if not trades_df.empty:
            trades_df = trades_df.set_index("date") if "date" in trades_df.columns else trades_df

        # 换手率 = sum(|买卖金额|) / 平均总资产
        total_trade_amount = total_buy_amount + total_sell_amount
        avg_equity = np.mean(equity_series) if equity_series else capital
        turnover = total_trade_amount / avg_equity if avg_equity > 0 else 0.0
        # 年化换手率 = 每次调仓换手 * (252 / 间隔天数)
        n_years = len(all_dates) / 252
        annual_turnover = turnover / n_years if n_years > 0.5 else turnover

        return {
            "returns": returns,
            "equity_curve": equity,
            "positions": positions_df,
            "trades": trades_df,
            "metrics": metrics,
            "turnover": round(annual_turnover, 4),
            "n_trades": len(trade_records),
            "execution_log": execution_log,
        }
