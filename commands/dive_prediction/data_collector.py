"""ETF 跳水预测系统 — 数据采集模块

从 akshare 拉取 ETF 和龙头个股的历史/实时数据。
数据统一存到 config.PATHS["daily_kline"]，不自己维护副本。
"""
import os, json, csv, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PATHS, VENV_PYTHON
from dive_prediction.proxy_bypass import call_no_proxy, no_proxy_for

CST = timezone(timedelta(hours=8))

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

# 数据统一存储路径（与 DataHub 共享）
KLINE_DIR = PATHS["daily_kline"]


def ensure_dir():
    KLINE_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════
# 历史数据采集
# ═══════════════════════════════════════════════════

def fetch_etf_hist(days: int = 250) -> pd.DataFrame:
    """拉取 ETF 历史日K线"""
    import akshare as ak
    end = datetime.now(CST)
    start = end - timedelta(days=days + 20)
    df = call_no_proxy(
        ak.fund_etf_hist_em,
        symbol=ETF_CODE, period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    df = df.sort_values("日期")
    df.to_csv(KLINE_DIR / f"{ETF_CODE}_hist.csv", index=False)
    print(f"  ETF历史: {len(df)} 条 ({df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]})")
    return df


def fetch_leader_hist(days: int = 250) -> dict:
    """拉取龙头个股历史日K线（如果 proxy 阻塞则静默跳过）"""
    import akshare as ak
    end = datetime.now(CST)
    start = end - timedelta(days=days + 20)
    results = {}
    for code, name in LEADER_STOCKS:
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            df = df.sort_values("日期")
            df.to_csv(KLINE_DIR / f"{code}_hist.csv", index=False)
            results[code] = df
            print(f"  {name}({code}): {len(df)} 条")
        except Exception as e:
            # stock_zh_a_hist 可能被 proxy 阻塞，不影响主流程
            print(f"  ⚠️ {name}({code}): 跳过 ({type(e).__name__})")
    return results


def fetch_etf_intraday() -> pd.DataFrame | None:
    """拉取 ETF 当日分时"""
    import akshare as ak
    try:
        df = ak.fund_etf_hist_em(
            symbol=ETF_CODE,
            period="daily",
            start_date=datetime.now(CST).strftime("%Y%m%d"),
            end_date=datetime.now(CST).strftime("%Y%m%d"),
            adjust="qfq",
        )
        return df
    except Exception:
        return None


# ═══════════════════════════════════════════════════
# 特征工程
# ═══════════════════════════════════════════════════

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """从日K线计算预测特征"""
    if df is None or df.empty:
        return df

    df = df.copy()
    # 列名映射 (akshare ETF 用中文列名)
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

    total = len(df)
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

    ensure_dir()
    print(f"\n{'═'*50}")
    print(f"  ETF跳水预测 — 数据采集&回测")
    print(f"  标的: {ETF_CODE}({ETF_NAME}) + {len(LEADER_STOCKS)}只龙头")
    print(f"{'═'*50}")

    if not args.backtest_only:
        print("\n--- 拉取 ETF 历史 ---")
        df_etf = fetch_etf_hist(days=args.days)
        print("\n--- 拉取龙头历史 ---")
        fetch_leader_hist(days=args.days)
    else:
        csv_path = KLINE_DIR / f"{ETF_CODE}_hist.csv"
        if csv_path.exists():
            df_etf = pd.read_csv(csv_path)
            print(f"\n--- 读取本地数据: {len(df_etf)} 条 ---")
        else:
            print("⚠️ 本地无数据，请先运行 --fetch-only")
            return

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
            print(f"\n  综合跳水概率 (任意信号触发):")
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
