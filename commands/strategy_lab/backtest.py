"""通用多标的多因子回测引擎

T日收盘信号 → T+1开盘成交。支持任意因子组合，由 strategy YAML 驱动。
"""
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

from factor_lab.datahub_access import daily_kline_path

CST = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_DIR = ROOT / "research_outputs/universes"


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


# ─── 数据加载 ───────────────────────────────────────────────

def load_kline(symbol: str) -> list[dict]:
    try:
        source = daily_kline_path(symbol)
    except FileNotFoundError:
        return []
    frame = pd.read_csv(source, encoding="utf-8-sig", low_memory=False)
    frame = frame.rename(columns={"trade_date": "date", "vol": "volume", "ts_code": "symbol"})
    if frame.empty or not {"date", "close"}.issubset(frame.columns):
        return []
    if "symbol" not in frame:
        frame["symbol"] = str(symbol).split(".")[0]
    raw_dates = frame["date"].astype("string").str.replace(r"\.0$", "", regex=True)
    compact = raw_dates.str.fullmatch(r"\d{8}", na=False)
    parsed = pd.to_datetime(raw_dates.where(compact), format="%Y%m%d", errors="coerce")
    parsed = parsed.fillna(pd.to_datetime(raw_dates.where(~compact), format="mixed", errors="coerce"))
    frame["date"] = parsed.dt.strftime("%Y-%m-%d")
    frame = frame.dropna(subset=["date"])
    return frame.to_dict(orient="records")


def to_float(v, default=0.0):
    try:
        return float(v) if v else default
    except (ValueError, TypeError):
        return default


# ─── 因子计算 ────────────────────────────────────────────────

def compute_factor_ret20(rows: list[dict]) -> list[Optional[float]]:
    closes = [to_float(r.get("close")) for r in rows]
    result = []
    for i in range(len(closes)):
        if i < 20:
            result.append(None)
        else:
            result.append((closes[i] - closes[i - 20]) / closes[i - 20] if closes[i - 20] else 0)
    return result


def compute_factor_ma20_gt_ma60(rows: list[dict]) -> list[Optional[float]]:
    closes = [to_float(r.get("close")) for r in rows]
    result = []
    for i in range(len(closes)):
        if i < 60:
            result.append(None)
        else:
            ma20 = sum(closes[i - 19:i + 1]) / 20
            ma60 = sum(closes[i - 59:i + 1]) / 60
            result.append(1.0 if ma20 > ma60 else 0.0)
    return result


def compute_factor_vol_ratio20(rows: list[dict]) -> list[Optional[float]]:
    volumes = [to_float(r.get("volume")) for r in rows]
    result = []
    for i in range(len(volumes)):
        if i < 20:
            result.append(None)
        else:
            avg_vol = sum(volumes[i - 19:i + 1]) / 20
            result.append(volumes[i] / avg_vol if avg_vol else 1.0)
    return result


FACTOR_FUNCS = {
    "ret20": compute_factor_ret20,
    "ma20_gt_ma60": compute_factor_ma20_gt_ma60,
    "vol_ratio20": compute_factor_vol_ratio20,
}


def compute_factors(rows: list[dict], factor_configs: list[dict]) -> list[dict]:
    """对一组K线计算所有因子，返回每行带因子值的dict"""
    if not rows:
        return []
    result = []
    factor_values = {}
    for fc in factor_configs:
        name = fc["name"]
        fn = FACTOR_FUNCS.get(name)
        if fn:
            factor_values[name] = fn(rows)
    for i, r in enumerate(rows):
        entry = {
            "date": r.get("date", ""),
            "symbol": r.get("symbol", r.get("code", "")),
            "open": to_float(r.get("open")),
            "high": to_float(r.get("high")),
            "low": to_float(r.get("low")),
            "close": to_float(r.get("close")),
            "volume": to_float(r.get("volume")),
        }
        for fc in factor_configs:
            name = fc["name"]
            vals = factor_values.get(name, [])
            entry[f"factor_{name}"] = vals[i] if i < len(vals) else None
        result.append(entry)
    return result


# ─── 执行模拟器 ──────────────────────────────────────────────

class ExecutionSimulator:
    def __init__(self, cost_cfg: dict):
        self.commission = cost_cfg.get("commission_rate", 0.0003)
        self.min_commission = cost_cfg.get("min_commission", 5)
        self.stamp_tax = cost_cfg.get("stamp_tax_rate_sell", 0.0005)
        self.slippage = cost_cfg.get("slippage_bps", 5) / 10000.0
        self.lot = cost_cfg.get("lot_size", 100)

    def buy_cost(self, price: float, shares: int) -> float:
        value = price * shares
        fee = max(value * self.commission, self.min_commission)
        return value + fee

    def sell_proceeds(self, price: float, shares: int) -> float:
        value = price * shares
        fee = max(value * self.commission, self.min_commission)
        tax = value * self.stamp_tax
        return value - fee - tax

    def max_shares(self, cash: float, price: float) -> int:
        if price <= 0 or cash <= 0:
            return 0
        unit_cost = price * self.lot * (1 + self.commission + self.slippage)
        return (int(cash // unit_cost)) * self.lot


# ─── 回测主循环 ─────────────────────────────────────────────

def run(cfg: dict, start_date: str | None = None,
        end_date: str | None = None,
        factor_weight_overrides: dict | None = None) -> dict:
    """通用回测入口

    cfg: 策略 YAML 配置
    start_date/end_date: 可选，限定回测日期范围
    factor_weight_overrides: 可选，覆盖因子权重，如 {'ret20': 0.3, 'top_n': 10}
    """
    name = cfg.get("name", "unnamed")
    universe_name = cfg.get("universe", {}).get("name", "")
    factor_configs_raw = cfg.get("factors", [])

    # 应用因子权重覆盖
    factor_configs = []
    for fc in factor_configs_raw:
        new_fc = dict(fc)
        if factor_weight_overrides and fc["name"] in factor_weight_overrides:
            new_fc["weight"] = factor_weight_overrides[fc["name"]]
        factor_configs.append(new_fc)

    portfolio_cfg = dict(cfg.get("portfolio", {}))
    if factor_weight_overrides and "top_n" in factor_weight_overrides:
        portfolio_cfg["top_n"] = factor_weight_overrides["top_n"]
    cost_cfg = cfg.get("cost", {})
    top_n = portfolio_cfg.get("top_n", 10)
    initial_cash = float(portfolio_cfg.get("initial_cash", 1_000_000))
    max_weight = portfolio_cfg.get("max_single_weight", 0.15)

    executor = ExecutionSimulator(cost_cfg)

    # 读 universe
    universe_file = UNIVERSE_DIR / f"{universe_name}.csv"
    symbols = []
    if universe_file.exists():
        with open(universe_file) as f:
            for r in csv.DictReader(f):
                s = r.get("symbol", "").strip()
                if s:
                    symbols.append(s)

    if not symbols:
        # fallback: 手动指定
        symbols = ["688012", "002371", "688981", "300502", "002916", "603986", "688008", "688041",
                   "300308", "300394", "600584", "002156", "688019", "688126", "300236"]

    # 加载所有股票K线
    all_klines = {}
    for sym in symbols:
        rows = load_kline(sym)
        if rows:
            all_klines[sym] = rows

    # 计算因子
    factor_data = {}
    for sym, rows in all_klines.items():
        factor_data[sym] = compute_factors(rows, factor_configs)

    # 收集所有交易日
    all_dates = set()
    for sym, data in factor_data.items():
        for d in data:
            all_dates.add(d["date"])
    # 过滤交易日范围
    trading_dates = sorted(all_dates)
    if start_date:
        trading_dates = [d for d in trading_dates if d >= start_date]
    if end_date:
        trading_dates = [d for d in trading_dates if d <= end_date]

    if not trading_dates:
        return {"strategy": name, "status": "no_data", "message": "无K线数据"}

    # 回测主循环
    cash = initial_cash
    holdings = {}  # symbol -> shares
    equity_curve = []
    trades = []

    for t_idx in range(1, len(trading_dates)):
        today = trading_dates[t_idx]
        signal_date = trading_dates[t_idx - 1]  # T日收盘信号

        # 计算信号（基于T日收盘）
        scores = {}
        for sym in symbols:
            feats = factor_data.get(sym, [])
            feat_today = None
            for f in feats:
                if f["date"] == signal_date:
                    feat_today = f
                    break
            if not feat_today:
                continue
            score = 0.0
            has_any_factor = False
            for fc in factor_configs:
                name = fc["name"]
                val = feat_today.get(f"factor_{name}")
                if val is None:
                    continue
                has_any_factor = True
                # 归一化 ret20: -0.2..0.5 → 0..100
                if name == "ret20":
                    norm = max(0, min(100, (val + 0.2) / 0.7 * 100))
                    score += norm * fc.get("weight", 0)
                elif name == "ma20_gt_ma60":
                    score += val * 100 * fc.get("weight", 0)
                elif name == "vol_ratio20":
                    norm = max(0, min(100, val * 50))
                    score += norm * fc.get("weight", 0)
                else:
                    score += (val if isinstance(val, (int, float)) else 0) * fc.get("weight", 0)
            if has_any_factor and score > 0:
                scores[sym] = round(score, 1)

        # 选前top_n
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_n]
        target_symbols = {s for s, _ in ranked}

        # T日收盘价 → T+1开盘成交
        # 处理卖出
        for sym in list(holdings.keys()):
            if sym not in target_symbols:
                feats = factor_data.get(sym, [])
                exit_row = None
                for f in feats:
                    if f["date"] == today:
                        exit_row = f
                        break
                if exit_row and holdings[sym] > 0:
                    sell_price = exit_row["open"] * (1 - executor.slippage)
                    proceeds = executor.sell_proceeds(sell_price, holdings[sym])
                    cash += proceeds
                    trades.append({
                        "date": today, "symbol": sym, "action": "sell",
                        "price": round(sell_price, 2), "shares": holdings[sym],
                        "proceeds": round(proceeds, 2),
                    })
                    del holdings[sym]

        # 处理买入
        for sym in target_symbols:
            if sym in holdings:
                continue  # 已持有
            feats = factor_data.get(sym, [])
            buy_row = None
            for f in feats:
                if f["date"] == today:
                    buy_row = f
                    break
            if not buy_row:
                continue
            buy_price = buy_row["open"] * (1 + executor.slippage)
            max_weight_cash = initial_cash * max_weight
            alloc = min(cash * 0.9, max_weight_cash) / top_n
            shares = executor.max_shares(alloc, buy_price)
            if shares > 0:
                cost = executor.buy_cost(buy_price, shares)
                if cost <= cash:
                    cash -= cost
                    holdings[sym] = holdings.get(sym, 0) + shares
                    trades.append({
                        "date": today, "symbol": sym, "action": "buy",
                        "price": round(buy_price, 2), "shares": shares,
                        "cost": round(cost, 2),
                    })

        # 计算组合市值
        portfolio_value = cash
        for sym, shares in holdings.items():
            feats = factor_data.get(sym, [])
            price_row = None
            for f in feats:
                if f["date"] == today:
                    price_row = f
                    break
            if price_row:
                portfolio_value += shares * price_row["close"]

        equity_curve.append({
            "date": today, "equity": round(portfolio_value, 2),
            "cash": round(cash, 2), "holdings": len(holdings),
        })

    # 计算指标
    if equity_curve:
        start_eq = initial_cash
        end_eq = equity_curve[-1]["equity"]
        total_return = (end_eq - start_eq) / start_eq if start_eq else 0
        annual_return = total_return  # 简化
        closes_list = [e["equity"] for e in equity_curve]
        peak = closes_list[0]
        max_dd = 0
        for v in closes_list:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
        closed_trades = len([t for t in trades if t["action"] == "sell"])
        wins = 0
        for t in trades:
            if t["action"] == "sell" and t.get("proceeds", 0) > 0:
                # 粗略: 上次买入成本
                wins += 1  # simplified
    else:
        total_return = annual_return = max_dd = 0
        closed_trades = 0

    result = {
        "strategy": name,
        "status": "completed",
        "data_range": {"start": trading_dates[0], "end": trading_dates[-1]},
        "initial_cash": initial_cash,
        "final_equity": round(end_eq, 2) if equity_curve else initial_cash,
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "max_drawdown": round(max_dd, 4),
        "closed_trades": closed_trades,
        "total_trades": len(trades),
        "universe_size": len(symbols),
        "created_at": now_str(),
    }
    return result
