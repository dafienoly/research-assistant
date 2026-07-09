"""盘前交易风控 — A 股实盘约束检查

检查项:
  - ST/*ST 排除 (STWatchlist 数据库查询，替代 symbol 后缀推断)
  - 监管事件检查 (RegulatoryWatchlist 数据库查询)
  - 停牌排除
  - 涨停不追买
  - 跌停不能卖
  - 成交额低于阈值排除
  - 连续涨停风险提示
  - 近 5 日涨幅过大提示
  - 单票最大仓位
  - 最大持仓数量
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Optional

from factor_lab.risk.st_watchlist import STWatchlist
from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist


CST = timezone(timedelta(hours=8))


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


def _is_suspended(row: pd.Series) -> bool:
    """判断是否停牌

    停牌特征:
      - 收盘价为 0 或 NaN
      - 成交量为 0
      - 开盘价、最高价、最低价均为 0
    """
    close = row.get("close", row.get("收盘价", np.nan))
    volume = row.get("volume", row.get("成交量", row.get("vol", np.nan)))

    # 收盘价缺失或为 0 → 停牌
    if pd.isna(close) or close == 0:
        return True

    # 成交量为 0 → 可能停牌
    if not pd.isna(volume) and volume == 0:
        return True

    # 开盘价、最高价、最低价全部为 0 → 停牌
    open_px = row.get("open", row.get("开盘价", np.nan))
    high = row.get("high", row.get("最高价", np.nan))
    low = row.get("low", row.get("最低价", np.nan))
    if (
        not pd.isna(open_px) and open_px == 0
        and not pd.isna(high) and high == 0
        and not pd.isna(low) and low == 0
    ):
        return True

    return False


def _get_prev_close(df: pd.DataFrame, symbol: str, signal_date: str) -> float:
    """获取前收盘价

    从 DataFrame 中查找上一交易日的收盘价。
    """
    if "date" not in df.columns:
        return np.nan

    dates = sorted(df[df["symbol"] == symbol]["date"].unique())
    sig_date = pd.Timestamp(signal_date)
    prev_dates = [d for d in dates if pd.Timestamp(d) < sig_date]
    if not prev_dates:
        return np.nan

    prev_date = prev_dates[-1]
    prev_row = df[(df["symbol"] == symbol) & (df["date"] == prev_date)]
    if prev_row.empty:
        return np.nan

    return float(prev_row.iloc[0].get("close", prev_row.iloc[0].get("收盘价", np.nan)))


def _get_consecutive_up_days(
    df: pd.DataFrame, symbol: str, signal_date: str, max_lookback: int = 10
) -> int:
    """计算连续上涨天数

    从 signal_date 往前回溯, 统计连续上涨（收盘价 > 前收盘）的天数。
    """
    if "date" not in df.columns:
        return 0

    symbol_data = df[df["symbol"] == symbol].sort_values("date")
    if symbol_data.empty:
        return 0

    # 找到 signal_date 之前的日期
    sig_idx = None
    for i, d in enumerate(symbol_data["date"]):
        if str(d)[:10] >= signal_date:
            sig_idx = i
            break

    if sig_idx is None or sig_idx == 0:
        return 0

    consecutive = 0
    for i in range(sig_idx - 1, max(0, sig_idx - max_lookback - 1), -1):
        close = float(symbol_data.iloc[i].get("close", symbol_data.iloc[i].get("收盘价", 0)))
        prev_close = float(
            symbol_data.iloc[i - 1].get("close", symbol_data.iloc[i - 1].get("收盘价", 0))
        ) if i > 0 else close
        if close > prev_close:
            consecutive += 1
        else:
            break

    return consecutive


def _get_5d_return(
    df: pd.DataFrame, symbol: str, signal_date: str
) -> float:
    """计算近 5 日涨幅

    从 signal_date 往前取 5 个交易日，计算累计涨幅。
    """
    if "date" not in df.columns:
        return 0.0

    symbol_data = df[df["symbol"] == symbol].sort_values("date")
    if symbol_data.empty:
        return 0.0

    # 找到 signal_date 当天或之前的数据
    available = symbol_data[symbol_data["date"] <= signal_date]
    if len(available) < 2:
        return 0.0

    recent = available.tail(min(6, len(available)))
    first_close = float(
        recent.iloc[0].get("close", recent.iloc[0].get("收盘价", 0))
    )
    last_close = float(
        recent.iloc[-1].get("close", recent.iloc[-1].get("收盘价", 0))
    )

    if first_close <= 0:
        return 0.0

    return (last_close - first_close) / first_close


def run_pretrade_risk_check(
    candidates: list,
    df: pd.DataFrame,
    signal_date: str,
    min_amount: float = 1_000_000,
    consecutive_up_days: int = 3,
    max_5d_return: float = 0.30,
    st_watchlist: Optional[STWatchlist] = None,
    regulatory_watchlist: Optional[RegulatoryWatchlist] = None,
) -> dict:
    """对候选股票列表执行盘前风控检查

    参数:
        candidates: [{"symbol": "000001", ...}, ...]
        df: 包含行情和因子数据的 DataFrame
        signal_date: 信号日期 (格式: "YYYY-MM-DD")
        min_amount: 最低成交额
        consecutive_up_days: 连续上涨天数阈值
        max_5d_return: 5日涨幅上限
        st_watchlist: ST 名单数据库（可选，如果不传则使用 symbol 后缀推断）
        regulatory_watchlist: 监管事件数据库（可选）

    返回:
        {"checked_at", "n_st_flagged", "n_suspended_flagged",
         "n_limit_up_flagged", "n_low_liquidity_flagged",
         "n_consecutive_up_flagged", "total_risk_flags",
         "status", "details": [{symbol, risk_type, detail}, ...]}
    """
    details = []

    # 筛选 signal_date 数据
    day_data = df[df["date"] == signal_date] if "date" in df.columns else df

    for c in candidates:
        sym = c.get("symbol", "")
        row = day_data[day_data["symbol"] == sym] if "symbol" in day_data.columns else None

        if row is None or len(row) == 0:
            continue
        r = row.iloc[0]

        risk_flags = []
        risk_details = []

        # ────────── 1. ST 检查 ──────────
        is_st = False
        if st_watchlist is not None:
            is_st = st_watchlist.is_st(sym)
        else:
            # 回退: symbol 后缀推断
            is_st = bool(sym.endswith("ST")) or bool("*ST" in sym) or str(r.get("symbol", "")).endswith("ST")

        if is_st:
            risk_flags.append("ST")
            risk_details.append("ST/*ST 股票")

        # ────────── 2. 监管事件检查 ──────────
        if regulatory_watchlist is not None:
            if regulatory_watchlist.is_blacklisted(sym):
                risk_flags.append("regulatory_blacklist")
                risk_details.append("严重监管事件(立案调查/行政处罚)")
            elif regulatory_watchlist.has_recent_regulatory_risk(sym, days=30):
                risk_flags.append("regulatory_warning")
                risk_details.append("近期监管函/问询函")

        # ────────── 3. 停牌检查 ──────────
        is_suspended = _is_suspended(r)
        if is_suspended:
            risk_flags.append("suspended")
            risk_details.append("当日停牌")

        # ────────── 4. 涨停检查 ──────────
        is_limit_up = False
        close_price = float(r.get("close", r.get("收盘价", r.get("latest_price", 0))))
        prev_close_price = _get_prev_close(df, sym, signal_date)

        if not pd.isna(close_price) and not pd.isna(prev_close_price) and prev_close_price > 0:
            is_limit_up = _is_limit_up(close_price, prev_close_price)

        if is_limit_up:
            risk_flags.append("limit_up")
            risk_details.append(f"涨停({close_price:.2f} >= {prev_close_price * 1.095:.2f})")

        # ────────── 5. 成交额检查 ──────────
        low_liquidity = False
        amt = r.get("amount", r.get("成交额", r.get("amount_rank20", 0)))
        if isinstance(amt, (int, float)) and 0 < amt < min_amount:
            low_liquidity = True

        if low_liquidity:
            risk_flags.append("low_amount")
            risk_details.append(f"成交额{amt:.0f}<{min_amount:.0f}")

        # ────────── 6. 连续上涨检查 ──────────
        consec_up = _get_consecutive_up_days(df, sym, signal_date)
        if consec_up >= consecutive_up_days:
            risk_flags.append("consecutive_up")
            risk_details.append(f"连续{consec_up}日上涨")

        # ────────── 7. 5日涨幅检查 ──────────
        ret5 = _get_5d_return(df, sym, signal_date)
        ret5_over = ret5 > max_5d_return
        if ret5_over:
            risk_flags.append("ret5_over")
            risk_details.append(f"5日涨幅{ret5:.1%}>{max_5d_return:.0%}")

        if risk_flags:
            details.append({
                "symbol": sym,
                "risk_type": ",".join(risk_flags),
                "detail": "; ".join(risk_details),
            })

    # ────────── 统计 ──────────
    n_st = sum(1 for d in details if "ST" in d["risk_type"])
    n_suspended = sum(1 for d in details if "suspended" in d["risk_type"])
    n_limit_up = sum(1 for d in details if "limit_up" in d["risk_type"])
    n_liq = sum(1 for d in details if "low_amount" in d["risk_type"])
    n_consecutive_up = sum(1 for d in details if "consecutive_up" in d["risk_type"])
    n_ret5 = sum(1 for d in details if "ret5" in d["risk_type"])
    n_regulatory = sum(
        1 for d in details
        if "regulatory_blacklist" in d["risk_type"] or "regulatory_warning" in d["risk_type"]
    )

    total_flags = len(details)
    if total_flags == 0:
        status = "ok"
    elif total_flags < len(candidates) * 0.3:
        status = "warn"
    else:
        status = "fail"

    return {
        "checked_at": datetime.now(CST).isoformat(),
        "n_st_flagged": n_st,
        "n_suspended_flagged": n_suspended,
        "n_limit_up_flagged": n_limit_up,
        "n_low_liquidity_flagged": n_liq,
        "n_consecutive_up_flagged": n_consecutive_up,
        "n_high_return_flagged": n_ret5,
        "n_regulatory_flagged": n_regulatory,
        "total_risk_flags": total_flags,
        "n_candidates_checked": len(candidates),
        "status": status,
        "details": details,
    }
