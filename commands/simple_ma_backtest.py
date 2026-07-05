#!/usr/bin/env python3
"""Simple long-only moving-average crossover backtest.

Signals are calculated from close prices on day T and executed at the next
available open. This avoids same-bar look-ahead in the example template.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


@dataclass
class Trade:
    entry_date: str
    exit_date: str | None
    entry_price: float
    exit_price: float | None
    shares: int
    gross_pnl: float | None
    net_pnl: float | None
    return_pct: float | None


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in ("", ".csv"):
        return pd.read_csv(path)
    raise SystemExit("Input suffix must be .csv or .parquet")


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min()) if len(drawdown) else 0.0


def annualized_return(equity: pd.Series, dates: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    days = max((dates.iloc[-1] - dates.iloc[0]).days, 1)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    return float((1.0 + total_return) ** (365.0 / days) - 1.0)


def sharpe_ratio(returns: pd.Series) -> float:
    returns = returns.dropna()
    if returns.empty or returns.std(ddof=0) == 0:
        return 0.0
    return float(math.sqrt(252) * returns.mean() / returns.std(ddof=0))


def prepare_data(df: pd.DataFrame, symbol: str | None, start: str | None, end: str | None) -> pd.DataFrame:
    # 兼容 'code' → 'symbol' 列名
    if "symbol" not in df.columns and "code" in df.columns:
        df = df.rename(columns={"code": "symbol"})
    required = ["date", "symbol", "open", "close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "symbol", "open", "close"])
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["open", "close"])

    if symbol:
        df = df[df["symbol"] == symbol.upper()]
    symbols = sorted(df["symbol"].unique())
    if len(symbols) != 1:
        raise SystemExit(f"Backtest requires exactly one symbol, found: {symbols}")
    if start:
        df = df[df["date"] >= pd.to_datetime(start)]
    if end:
        df = df[df["date"] <= pd.to_datetime(end)]
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(df) < 30:
        raise SystemExit("Not enough rows for a meaningful moving-average backtest.")
    return df


def run_backtest(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    initial_cash: float,
    lot_size: int,
    commission: float,
    stamp_duty: float,
    slippage_bps: float,
) -> tuple[pd.DataFrame, list[Trade], dict]:
    if fast >= slow:
        raise SystemExit("--fast must be smaller than --slow")
    if initial_cash <= 0:
        raise SystemExit("--initial-cash must be positive")

    df = df.copy()
    df["fast_ma"] = df["close"].rolling(fast, min_periods=fast).mean()
    df["slow_ma"] = df["close"].rolling(slow, min_periods=slow).mean()
    above = df["fast_ma"] > df["slow_ma"]
    df["signal"] = 0
    df.loc[above & (~above.shift(1).fillna(False)), "signal"] = 1
    df.loc[(~above) & above.shift(1).fillna(False), "signal"] = -1

    cash = float(initial_cash)
    shares = 0
    entry_price: float | None = None
    entry_date: str | None = None
    trades: list[Trade] = []
    equity_rows = []
    slippage = slippage_bps / 10000.0
    total_trade_value = 0.0

    # Execute yesterday's signal at today's open.
    for index in range(1, len(df)):
        today = df.iloc[index]
        prior = df.iloc[index - 1]
        signal = int(prior["signal"])
        trade_date = today["date"].strftime("%Y-%m-%d")
        open_price = float(today["open"])

        if signal == 1 and shares == 0 and open_price > 0:
            buy_price = open_price * (1.0 + slippage)
            max_shares = int(cash / (buy_price * (1.0 + commission)))
            if lot_size > 1:
                max_shares = (max_shares // lot_size) * lot_size
            if max_shares > 0:
                trade_value = max_shares * buy_price
                fee = trade_value * commission
                cash -= trade_value + fee
                shares = max_shares
                entry_price = buy_price
                entry_date = trade_date
                total_trade_value += trade_value

        elif signal == -1 and shares > 0 and open_price > 0:
            sell_price = open_price * (1.0 - slippage)
            trade_value = shares * sell_price
            fee = trade_value * (commission + stamp_duty)
            cash += trade_value - fee
            gross_pnl = (sell_price - float(entry_price)) * shares
            net_pnl = cash - initial_cash - sum(t.net_pnl or 0.0 for t in trades)
            trades.append(
                Trade(
                    entry_date=str(entry_date),
                    exit_date=trade_date,
                    entry_price=float(entry_price),
                    exit_price=sell_price,
                    shares=shares,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    return_pct=net_pnl / (float(entry_price) * shares),
                )
            )
            total_trade_value += trade_value
            shares = 0
            entry_price = None
            entry_date = None

        close_price = float(today["close"])
        equity_rows.append(
            {
                "date": trade_date,
                "cash": cash,
                "shares": shares,
                "close": close_price,
                "position_value": shares * close_price,
                "equity": cash + shares * close_price,
                "signal_from_prior_close": signal,
            }
        )

    equity = pd.DataFrame(equity_rows)
    equity["return"] = equity["equity"].pct_change()
    closed = [trade for trade in trades if trade.net_pnl is not None]
    wins = [trade for trade in closed if float(trade.net_pnl) > 0]
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "symbol": str(df["symbol"].iloc[0]),
        "first_date": df["date"].iloc[0].strftime("%Y-%m-%d"),
        "last_date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "initial_cash": initial_cash,
        "final_equity": float(equity["equity"].iloc[-1]),
        "total_return": float(equity["equity"].iloc[-1] / initial_cash - 1.0),
        "annualized_return": annualized_return(equity["equity"], pd.to_datetime(equity["date"])),
        "annualized_volatility": float(equity["return"].std(ddof=0) * math.sqrt(252)),
        "sharpe": sharpe_ratio(equity["return"]),
        "max_drawdown": max_drawdown(equity["equity"]),
        "closed_trades": len(closed),
        "win_rate": float(len(wins) / len(closed)) if closed else 0.0,
        "turnover": float(total_trade_value / initial_cash),
        "assumptions": {
            "execution": "Signal from close on day T, trade at next open.",
            "fast_ma": fast,
            "slow_ma": slow,
            "lot_size": lot_size,
            "commission": commission,
            "stamp_duty": stamp_duty,
            "slippage_bps": slippage_bps,
        },
    }

    if shares > 0 and entry_price is not None and entry_date is not None:
        trades.append(
            Trade(
                entry_date=entry_date,
                exit_date=None,
                entry_price=entry_price,
                exit_price=None,
                shares=shares,
                gross_pnl=None,
                net_pnl=None,
                return_pct=None,
            )
        )
    return equity, trades, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--fast", type=int, default=5)
    parser.add_argument("--slow", type=int, default=20)
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--commission", type=float, default=0.0003)
    parser.add_argument("--stamp-duty", type=float, default=0.0005)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    df = prepare_data(read_table(args.input), args.symbol, args.start, args.end)
    equity, trades, summary = run_backtest(
        df=df,
        fast=args.fast,
        slow=args.slow,
        initial_cash=args.initial_cash,
        lot_size=args.lot_size,
        commission=args.commission,
        stamp_duty=args.stamp_duty,
        slippage_bps=args.slippage_bps,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    equity_path = args.output_dir / "equity_curve.csv"
    trades_path = args.output_dir / "trades.csv"
    summary_path = args.output_dir / "summary.json"
    equity.to_csv(equity_path, index=False, encoding="utf-8-sig")
    pd.DataFrame([asdict(trade) for trade in trades]).to_csv(trades_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {equity_path}")
    print(f"Wrote {trades_path}")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
