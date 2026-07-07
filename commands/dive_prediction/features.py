"""全特征版模型评估 — 龙头个股/技术指标/大市/新闻情感/降阈值"""
import sys, json, warnings, re
from pathlib import Path
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PATHS

ETF_CODE = "159516"
KLINE = PATHS["daily_kline"]
LEADER_CODES = ["002371","688012","300604","688072","688120"]


def load_etf() -> pd.DataFrame:
    path = KLINE / f"{ETF_CODE}_hist.csv"
    if not path.exists():
        path = KLINE / f"{ETF_CODE}_daily_kline.csv"
    df = pd.read_csv(path)
    col_map = {"日期": "date", "timeString": "date"}
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    for c in ["open","close","high","low","volume","amount"]:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_leaders() -> dict:
    """返回 {code: df}"""
    result = {}
    for code in LEADER_CODES:
        path = KLINE / f"{code}_daily_kline.csv"
        if path.exists():
            df = pd.read_csv(path)
            df["timeString"] = pd.to_datetime(df["timeString"])
            for c in ["open","close","high","low","volume","amount"]:
                if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
            result[code] = df.sort_values("timeString").reset_index(drop=True)
    return result


def compute_full_features(df_etf: pd.DataFrame, leader_dfs: dict) -> pd.DataFrame:
    """计算全部特征，返回带标签的 DataFrame"""
    df = df_etf.copy()
    close, high, low = df["close"], df["high"], df["low"]
    vol, amount = df["volume"], df["amount"]

    # ── 基础量价特征 ──
    df["ret1"] = close.pct_change(1)
    df["ret5"] = close.pct_change(5)
    df["ret10"] = close.pct_change(10)
    df["ret20"] = close.pct_change(20)
    df["amplitude"] = (high - low) / close.shift(1) * 100
    df["vol_ratio"] = vol / vol.rolling(5).mean()
    df["amount_ma5"] = amount.rolling(5).mean()
    df["high_low_ratio"] = (close - low) / (high - low + 0.001)
    df["open_close_ratio"] = (close - df["open"]) / (high - low + 0.001)
    df["consec_up"] = (df["ret1"] > 0).rolling(3).sum()

    # ── 技术指标 (Priority 2) ──
    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi_14"] = 100 - 100 / (1 + rs)

    # 布林带 %B
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bollinger_%b"] = (close - ma20) / (2 * std20 + 1e-9)

    # 量价相关性 (5日滚动)
    df["vol_price_corr_5"] = close.rolling(5).corr(vol.rolling(5).mean())

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # ── 龙头个股特征 (Priority 1) ──
    if leader_dfs:
        merged = None
        for code, ldf in leader_dfs.items():
            sub = ldf[["timeString", "close", "volume"]].rename(
                columns={"close": f"{code}_close", "volume": f"{code}_vol"})
            if merged is None:
                merged = sub
            else:
                merged = merged.merge(sub, on="timeString", how="outer")
        merged = merged.sort_values("timeString").ffill()
        # 与 ETF 数据对齐
        df = df.merge(merged, left_on="date", right_on="timeString", how="left")
        df.ffill(inplace=True)

        # 个股涨跌幅
        for code in LEADER_CODES:
            col = f"{code}_close"
            if col in df.columns:
                df[f"{code}_ret1"] = df[col].pct_change(1)

        # 板块平均涨跌幅
        ret_cols = [f"{c}_ret1" for c in LEADER_CODES if f"{c}_ret1" in df.columns]
        if ret_cols:
            df["leader_avg_ret"] = df[ret_cols].mean(axis=1)
            df["leader_etf_divergence"] = df["leader_avg_ret"] - df["ret1"]
            df["leader_volatility"] = df[ret_cols].std(axis=1)
            df["leader_up_ratio"] = (df[ret_cols] > 0).sum(axis=1) / len(ret_cols)

    # ── 时间特征 ──
    date_col = df.get("date") if "date" in df.columns else (df.get("日期") if "日期" in df.columns else None)
    if date_col is not None and hasattr(pd.to_datetime(date_col, errors="coerce"), 'dt'):
        dates = pd.to_datetime(date_col, errors="coerce")
        df["date"] = dates  # ensure datetime type
        df["day_of_week"] = dates.dt.dayofweek
        df["is_monday"] = (dates.dt.dayofweek == 0).astype(int)
        df["is_friday"] = (dates.dt.dayofweek == 4).astype(int)
        df["month_start"] = (dates.dt.day <= 5).astype(int)
        df["month_end"] = (dates.dt.day >= 25).astype(int)

    # ── 跳水标签 (Priority 4: 降低阈值) ──
    df["intraday_drop"] = (high - close) / high * 100
    # 三档标签
    df["label_dive_4pct"] = ((df["intraday_drop"] >= 4) | (df["ret1"] <= -4)).astype(int)
    df["label_dive_3pct"] = ((df["intraday_drop"] >= 3) | (df["ret1"] <= -3)).astype(int)
    df["label_dive_25pct"] = ((df["intraday_drop"] >= 2.5) | (df["ret1"] <= -2.5)).astype(int)

    return df


def prepare_Xy(df: pd.DataFrame, label_col: str = "label_dive_4pct") -> tuple:
    """Shift 特征，返回 (X, y, feature_names)"""
    feature_cols = [
        # 基础量价
        "ret1","ret5","ret10","ret20","amplitude","vol_ratio","amount_ma5",
        "high_low_ratio","open_close_ratio","consec_up",
        # 技术指标
        "rsi_14","bollinger_%b","vol_price_corr_5","macd","macd_hist",
        # 龙头个股
        "leader_avg_ret","leader_etf_divergence","leader_volatility","leader_up_ratio",
        # 时间
        "day_of_week","is_monday","is_friday","month_start","month_end",
    ]
    available = [c for c in feature_cols if c in df.columns]
    X = df[available].shift(1).values  # T日特征预测T+1日
    y = df[label_col].values
    mask = ~np.isnan(X[:, 0]) if len(X) > 0 else slice(None)
    return X[mask], y[mask], available
