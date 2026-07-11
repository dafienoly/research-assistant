"""ETF 跳水预测系统 — 数据采集模块

只读 DataHub canonical ETF 和龙头个股历史/实时数据，不维护副本。
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from factor_lab.datahub_access import daily_kline_path, read_live_snapshot

# ── 监测标的 ──
ETF_CODE = "159516"
ETF_NAME = "半导体设备ETF"

# 龙头个股（板块先行指标）
LEADER_STOCKS = [
    ("002371", "北方华创"),
    ("688012", "中微公司"),
    ("300604", "长川科技"),
    ("688072", "拓荆科技"),
    ("688120", "华海清科"),
]

def _read_canonical_history(code: str, days: int) -> pd.DataFrame:
    path = daily_kline_path(code)
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame = frame.rename(columns={"vol": "volume", "pct_chg": "change_pct", "change": "change_amount"})
    date_column = next((name for name in ("date", "trade_date", "日期", "timeString") if name in frame), None)
    if date_column is None:
        raise ValueError(f"canonical DataHub daily kline has no date column: {path}")
    frame = frame.rename(columns={date_column: "日期"})
    raw_dates = frame["日期"].astype("string").str.replace(r"\.0$", "", regex=True).str.strip()
    compact = raw_dates.str.replace("-", "", regex=False)
    frame["日期"] = pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    frame = frame.dropna(subset=["日期"]).sort_values("日期", kind="stable")
    if frame.empty:
        raise ValueError(f"canonical DataHub daily kline is empty: {path}")
    return frame.tail(days).reset_index(drop=True)


# ═══════════════════════════════════════════════════
# 历史数据采集
# ═══════════════════════════════════════════════════

def fetch_etf_hist(days: int = 250) -> pd.DataFrame:
    """读取 DataHub canonical ETF 历史日 K 线。"""
    df = _read_canonical_history(ETF_CODE, days)
    print(f"  ETF历史: {len(df)} 条 ({df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]})")
    return df


def fetch_leader_hist(days: int = 250) -> dict:
    """读取 DataHub canonical 龙头个股历史日 K 线。"""
    results = {}
    for code, name in LEADER_STOCKS:
        try:
            df = _read_canonical_history(code, days)
            results[code] = df
            print(f"  {name}({code}): {len(df)} 条")
        except Exception as e:
            print(f"  ⚠️ {name}({code}): DataHub 缺失 ({type(e).__name__})")
    return results


def fetch_etf_intraday() -> pd.DataFrame | None:
    """读取 DataHub canonical ETF 最新盘中快照。"""
    try:
        row = read_live_snapshot([ETF_CODE])[ETF_CODE]
        return pd.DataFrame([{
            "日期": row["observed_at"], "开盘": row["open"], "收盘": row["price"],
            "最高": row["high"], "最低": row["low"], "成交量": row["volume"],
            "成交额": row["amount"], "涨跌幅": row["change_pct"],
        }])
    except (FileNotFoundError, KeyError, ValueError):
        return None


# ═══════════════════════════════════════════════════
# 特征工程
# ═══════════════════════════════════════════════════

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """从日K线计算预测特征"""
    if df is None or df.empty:
        return df

    df = df.copy()
    # 兼容旧中文列名；canonical DataHub 使用英文列名。
    col_map = {
        "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
        "涨跌幅": "change_pct", "涨跌额": "change_amount", "换手率": "turnover",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    # 确保数值
    for c in ["close", "high", "low", "volume", "amount"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # ── 基础特征 ──
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]
    amount = df["amount"]

    # 收益率
    df["ret1"] = close.pct_change(1)
    df["ret5"] = close.pct_change(5)
    df["ret10"] = close.pct_change(10)
    df["ret20"] = close.pct_change(20)

    # 波动率
    df["amplitude_raw"] = (high - low) / close.shift(1) * 100  # 当日振幅%
    df["amp_ma5"] = df["amplitude_raw"].rolling(5).mean()

    # 成交量
    df["vol_ratio"] = vol / vol.rolling(5).mean()  # 量比
    df["amount_ma5"] = amount.rolling(5).mean()

    # ── 跳水标签（预测目标）──
    # label=1: 当日从最高价回撤 ≥4% 或 当日跌幅 ≥4%
    df["intraday_drop"] = (high - close) / high * 100  # 从最高回撤%
    df["target_dive"] = ((df["intraday_drop"] >= 4) | (df["ret1"] <= -4)).astype(int)
    # 或 5日内最大回撤 > 4%
    df["max_drawdown_5"] = df["close"].rolling(5).apply(
        lambda x: (x.max() - x.min()) / x.max() * 100 if len(x) == 5 else 0
    )
    df["target_dive"] = df[["target_dive", "intraday_drop"]].max(axis=1)

    # ── 先行信号特征 ──
    # 信号1: 前日涨幅过高 → 今日回调风险
    df["prev_ret5"] = df["ret5"].shift(1)
    df["prev_amplitude"] = df["amplitude_raw"].shift(1)

    # 信号2: 放量滞涨 → 多空分歧
    df["vol_price_div"] = (df["vol_ratio"] > 1.5) & (abs(df["ret1"]) < 0.5)

    # 信号3: 连续上涨后的高开低走
    df["consec_up"] = (df["ret1"] > 0).rolling(3).sum()
    df["high_low_ratio"] = (close - low) / (high - low + 0.001)
    df["open_close_ratio"] = (close - df["open"]) / (high - low + 0.001)

    # ── 时间特征 ──
    if "日期" in df.columns:
        dates = pd.to_datetime(df["日期"])
    elif "timeString" in df.columns:
        dates = pd.to_datetime(df["timeString"])
    else:
        dates = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.RangeIndex(len(df))
    if hasattr(dates, 'dt'):
        df["day_of_week"] = dates.dt.dayofweek  # 0=Mon
        df["is_monday"] = (dates.dt.dayofweek == 0).astype(int)
        df["is_friday"] = (dates.dt.dayofweek == 4).astype(int)
        df["month_start"] = (dates.dt.day <= 5).astype(int)  # 月初5天
        df["month_end"] = (dates.dt.day >= 25).astype(int)   # 月末5天
        df["pre_holiday"] = 0  # 节假日特征（简化：周末前）
        df["post_holiday"] = 0

    return df


# ═══════════════════════════════════════════════════
# 信号回测
# ═══════════════════════════════════════════════════

def backtest_signals(df: pd.DataFrame) -> dict:
    """回测每个信号的历史预测准确率"""
    if df is None or df.empty:
        return {}

    results = {}
    target = df["target_dive"]

    # 定义信号和阈值
    signals = {
        "prev_ret5>5": df["prev_ret5"] > 5,
        "prev_amplitude>8": (df.get("amplitude_raw", df.get("prev_amplitude", pd.Series(0))) > 8) if "amplitude_raw" in df or "prev_amplitude" in df else pd.Series(False, index=df.index),
        "vol_price_div": df.get("vol_price_div", pd.Series(False)),
        "consec_up>=3": df["consec_up"] >= 3,
        "high_low_ratio<0.3": df["high_low_ratio"] < 0.3,
        "open_close_ratio<0.25": df["open_close_ratio"] < 0.25,
        "ret1<-2": df["ret1"] < -2,
    }

    for name, mask in signals.items():
        triggered = mask.sum()
        if triggered == 0:
            results[name] = {"触发次数": 0, "命中次数": 0, "次日精确率%": 0, "跳水概率%": 0}
            continue
        hits = (mask & (target >= 2)).sum()  # 次日跳水≥2%
        acc = hits / triggered * 100 if triggered > 0 else 0
        # 条件概率: P(跳水|信号)
        p_dive = (mask & (target > 0)).sum() / triggered * 100
        results[name] = {
            "触发次数": int(triggered),
            "命中次数": int(hits),
            "次日精确率%": round(acc, 1),
            "跳水概率%": round(p_dive, 1),
        }

    return results


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=250, help="回测天数")
    p.add_argument("--fetch-only", action="store_true", help="只拉数据不做回测")
    p.add_argument("--backtest-only", action="store_true", help="只用已有数据做回测")
    args = p.parse_args()

    print(f"\n{'═'*50}")
    print("  ETF跳水预测 — 数据采集&回测")
    print(f"  标的: {ETF_CODE}({ETF_NAME}) + {len(LEADER_STOCKS)}只龙头")
    print(f"{'═'*50}")

    if not args.backtest_only:
        print("\n--- 读取 DataHub ETF 历史 ---")
        df_etf = fetch_etf_hist(days=args.days)
        print("\n--- 拉取龙头历史 ---")
        fetch_leader_hist(days=args.days)
    else:
        df_etf = fetch_etf_hist(days=args.days)
        print(f"\n--- 读取 DataHub 数据: {len(df_etf)} 条 ---")

    if not args.fetch_only:
        print("\n--- 特征工程+回测 ---")
        df = compute_features(df_etf)
        if df is not None:
            results = backtest_signals(df)
            print(f"\n  信号回测结果 ({args.days}天):")
            print(f"  {'信号名':<25s} {'触发':>6s} {'命中':>6s} {'准确率':>8s} {'跳水概率':>10s}")
            print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*8} {'-'*10}")
            for name, r in sorted(results.items(), key=lambda x: -x[1].get("跳水概率%", 0)):
                print(f"  {name:<25s} {r['触发次数']:>6d} {r['命中次数']:>6d} "
                      f"{r['次日精确率%']:>7.1f}% {r['跳水概率%']:>8.1f}%")

            # 综合跳水概率
            print("\n  综合跳水概率 (任意信号触发):")
            any_signal = pd.DataFrame({k: v for k, v in [
                (k, v) for k, v in [
                    ("prev_ret5>5", df["prev_ret5"] > 5),
                    ("prev_amplitude>8", df.get("amplitude_raw", pd.Series(0, index=df.index)) > 8),
                    ("vol_price_div", df["vol_price_div"]),
                    ("consec_up>=3", df["consec_up"] >= 3),
                    ("high_low_ratio<0.3", df["high_low_ratio"] < 0.3),
                    ("open_close_ratio<0.25", df["open_close_ratio"] < 0.25),
                ]
            ]}).any(axis=1)
            triggered = any_signal.sum()
            if triggered > 0:
                dive_when_triggered = (any_signal & (df["target_dive"] > 0)).sum()
                print(f"  触发天数: {triggered}/{len(df)}")
                print(f"  触发后跳水率: {dive_when_triggered/triggered*100:.1f}%")
                print(f"  整体跳水率: {(df['target_dive']>0).sum()/len(df)*100:.1f}%")

    print(f"\n{'═'*50}\n")


if __name__ == "__main__":
    main()
