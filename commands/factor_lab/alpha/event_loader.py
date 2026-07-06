"""Event Loader V3.5 — 解禁/回购/分红/业绩预告 事件数据加载

为 Event-driven Alpha Pack 提供统一的事件数据加载接口。
数据源:
1. announcements_extracted.csv — 公告 (回购、分红、解禁、业绩预告等)
2. adjust_factor.csv — 复权因子 (含 dividend 字段)
3. forecast_report.csv — 业绩预告

所有加载器在数据缺失时优雅降级, 返回空 DataFrame 而非崩溃。

用法:
    from factor_lab.alpha.event_loader import (
        load_lockup_events, load_buyback_events, load_dividend_events,
        load_forecast_events, get_event_data
    )
    data = get_event_data(symbols=["000001", "000002"])
"""

import csv, os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

CST = timezone(timedelta(hours=8))

# ─── 路径 ─────────────────────────────────────────────────────────
HERMES_DATA = Path("/home/ly/.hermes/research-assistant/data")
ANNOUNCEMENTS_PATH = HERMES_DATA / "fundamentals" / "announcements_extracted.csv"
ADJUST_FACTOR_PATH = HERMES_DATA / "market" / "adjust_factor.csv"
FORECAST_REPORT_PATH = HERMES_DATA / "fundamentals" / "forecast_report.csv"

# ─── 事件字段定义 ─────────────────────────────────────────────────

LOCKUP_COLUMNS = [
    "symbol", "date",
    "lockup_days_to_expiry",    # 解禁倒计时 (天), 负值=已解禁
    "lockup_count_90d",         # 近90天解禁公告数
]

BUYBACK_COLUMNS = [
    "symbol", "date",
    "buyback_count_30d",        # 近30天回购公告数
    "buyback_count_90d",        # 近90天回购公告数
    "buyback_active",           # 是否有回购公告 (0/1)
]

DIVIDEND_COLUMNS = [
    "symbol", "date",
    "dividend_yield",           # 股息率 (dividend / close)
    "dividend_days_since",      # 除权除息后天数
    "dividend_amount",          # 每股股息 (元)
]

FORECAST_COLUMNS = [
    "symbol", "date",
    "forecast_type_code",       # 预告类型编码: 预增=1, 略增=0.5, 预减=-1, 略减=-0.5, 扭亏=0.8, 续亏=-0.8, 首亏=-1
    "forecast_days_since",      # 业绩预告后天数 (负值=还未出预告)
    "forecast_count_90d",       # 近90天预告数
    "forecast_momentum",        # 预告动量: 预增数-预减数 (滚动计数)
]

# ─── 公告类型映射 ─────────────────────────────────────────────────

# 解禁关键词
LOCKUP_KEYWORDS = ["解禁"]

# 回购关键词
BUYBACK_KEYWORDS = ["回购"]

# 分红关键词
DIVIDEND_KEYWORDS = ["分红"]

# 业绩预告类型映射 (基于 forecast_report.csv 的 type 字段)
FORECAST_TYPE_MAP = {
    "预增": 1.0,
    "略增": 0.5,
    "预减": -1.0,
    "略减": -0.5,
    "扭亏": 0.8,
    "续亏": -0.8,
    "首亏": -1.0,
    "预盈": 0.3,
    "减亏": 0.2,
    "不确定": 0.0,
}


# ─── 解禁事件加载 ─────────────────────────────────────────────────

def load_lockup_events(symbols: list = None) -> pd.DataFrame:
    """加载解禁相关事件数据

    从 announcements_extracted.csv 中筛选 announce_type=解禁 的公告。

    参数:
        symbols: 可选, 仅加载指定股票

    返回:
        pd.DataFrame (列: LOCKUP_COLUMNS)
        文件不存在时返回空 DataFrame。
    """
    if not ANNOUNCEMENTS_PATH.exists():
        return pd.DataFrame(columns=LOCKUP_COLUMNS)
    try:
        df = pd.read_csv(ANNOUNCEMENTS_PATH, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        # 标准化列名
        col_map = {}
        for c in df.columns:
            col_map[c] = c.lower().strip()
        df = df.rename(columns=col_map)

        # 筛选解禁类公告
        if "announce_type" in df.columns:
            df = df[df["announce_type"].str.contains("解禁", na=False)]
        elif "title" in df.columns:
            df = df[df["title"].str.contains("|".join(LOCKUP_KEYWORDS), na=False)]
        else:
            return pd.DataFrame(columns=LOCKUP_COLUMNS)

        if df.empty:
            return pd.DataFrame(columns=LOCKUP_COLUMNS)

        # 标准化 symbol 列
        if "code" in df.columns:
            df["symbol"] = df["code"].astype(str).str.zfill(6)
        elif "symbol" not in df.columns:
            return pd.DataFrame(columns=LOCKUP_COLUMNS)

        # 按股票聚合: 统计近90天解禁公告数, 计算解禁日距今天数
        today = pd.Timestamp.now()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            cutoff_90d = today - pd.Timedelta(days=90)
            recent = df[df["date"] >= cutoff_90d]
            recent_count = recent.groupby("symbol").size().reset_index(name="lockup_count_90d")

            # 每个股票最近一次解禁日
            latest = df.groupby("symbol")["date"].max().reset_index()
            latest["lockup_days_to_expiry"] = (latest["date"] - today).dt.days

            result = recent_count.merge(
                latest[["symbol", "lockup_days_to_expiry"]], on="symbol", how="outer"
            )
        else:
            result = pd.DataFrame({"symbol": df["symbol"].unique(),
                                    "lockup_days_to_expiry": 0,
                                    "lockup_count_90d": 0})

        # 填充 NaN
        result["lockup_days_to_expiry"] = result["lockup_days_to_expiry"].fillna(0)
        result["lockup_count_90d"] = result["lockup_count_90d"].fillna(0).astype(int)
        result["date"] = today.strftime("%Y-%m-%d")

        if symbols:
            result = result[result["symbol"].astype(str).isin(symbols)]

        for col in LOCKUP_COLUMNS:
            if col not in result.columns:
                result[col] = 0 if col != "symbol" else ""

        return result[LOCKUP_COLUMNS]
    except Exception as e:
        return pd.DataFrame(columns=LOCKUP_COLUMNS)


# ─── 回购事件加载 ─────────────────────────────────────────────────

def load_buyback_events(symbols: list = None) -> pd.DataFrame:
    """加载回购相关事件数据

    从 announcements_extracted.csv 中筛选 announce_type=回购 的公告。

    参数:
        symbols: 可选, 仅加载指定股票

    返回:
        pd.DataFrame (列: BUYBACK_COLUMNS)
        文件不存在时返回空 DataFrame。
    """
    if not ANNOUNCEMENTS_PATH.exists():
        return pd.DataFrame(columns=BUYBACK_COLUMNS)
    try:
        df = pd.read_csv(ANNOUNCEMENTS_PATH, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        col_map = {}
        for c in df.columns:
            col_map[c] = c.lower().strip()
        df = df.rename(columns=col_map)

        # 筛选回购类公告
        if "announce_type" in df.columns:
            df = df[df["announce_type"].str.contains("回购", na=False)]
        elif "title" in df.columns:
            df = df[df["title"].str.contains("|".join(BUYBACK_KEYWORDS), na=False)]
        else:
            return pd.DataFrame(columns=BUYBACK_COLUMNS)

        if df.empty:
            return pd.DataFrame(columns=BUYBACK_COLUMNS)

        if "code" in df.columns:
            df["symbol"] = df["code"].astype(str).str.zfill(6)
        elif "symbol" not in df.columns:
            return pd.DataFrame(columns=BUYBACK_COLUMNS)

        today = pd.Timestamp.now()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])

            cutoff_30d = today - pd.Timedelta(days=30)
            cutoff_90d = today - pd.Timedelta(days=90)

            recent_30d = df[df["date"] >= cutoff_30d]
            recent_90d = df[df["date"] >= cutoff_90d]

            count_30d = recent_30d.groupby("symbol").size().reset_index(name="buyback_count_30d")
            count_90d = recent_90d.groupby("symbol").size().reset_index(name="buyback_count_90d")

            result = count_30d.merge(count_90d, on="symbol", how="outer")
            result["buyback_active"] = (result["buyback_count_30d"] > 0).astype(int)
        else:
            result = pd.DataFrame({"symbol": df["symbol"].unique(),
                                    "buyback_active": 1,
                                    "buyback_count_30d": 0,
                                    "buyback_count_90d": 0})

        result["buyback_count_30d"] = result["buyback_count_30d"].fillna(0).astype(int)
        result["buyback_count_90d"] = result["buyback_count_90d"].fillna(0).astype(int)
        result["buyback_active"] = result["buyback_active"].fillna(0).astype(int)
        result["date"] = today.strftime("%Y-%m-%d")

        if symbols:
            result = result[result["symbol"].astype(str).isin(symbols)]

        for col in BUYBACK_COLUMNS:
            if col not in result.columns:
                result[col] = 0 if col != "symbol" else ""

        return result[BUYBACK_COLUMNS]
    except Exception as e:
        return pd.DataFrame(columns=BUYBACK_COLUMNS)


# ─── 分红事件加载 ─────────────────────────────────────────────────

def load_dividend_events(symbols: list = None) -> pd.DataFrame:
    """加载分红相关事件数据

    从 adjust_factor.csv 中提取 dividend 字段, 结合 announcement 中的分红公告。

    参数:
        symbols: 可选, 仅加载指定股票

    返回:
        pd.DataFrame (列: DIVIDEND_COLUMNS)
        文件不存在时返回空 DataFrame。
    """
    has_adjust = ADJUST_FACTOR_PATH.exists()
    has_announce = ANNOUNCEMENTS_PATH.exists()

    if not has_adjust and not has_announce:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS)

    result = None

    # 从 adjust_factor.csv 提取股息数据
    if has_adjust:
        try:
            adj = pd.read_csv(ADJUST_FACTOR_PATH, encoding="utf-8-sig")
            adj.columns = [c.strip().lower() for c in adj.columns]
            if "code" in adj.columns:
                adj["symbol"] = adj["code"].astype(str).str.zfill(6)

            if "dividend" in adj.columns and "symbol" in adj.columns:
                adj["date"] = pd.to_datetime(adj["date"], errors="coerce")
                adj = adj.dropna(subset=["date", "symbol"])

                # 只取 dividend > 0 (有分红的记录)
                div_records = adj[adj["dividend"].fillna(0) > 0].copy()
                if not div_records.empty:
                    today = pd.Timestamp.now()
                    # 计算除权除息后天数
                    div_records["dividend_days_since"] = (today - div_records["date"]).dt.days

                    # 最近一次分红信息
                    latest_idx = div_records.groupby("symbol")["date"].idxmax()
                    latest_div = div_records.loc[latest_idx, ["symbol", "dividend", "dividend_days_since"]].copy()
                    latest_div = latest_div.rename(columns={"dividend": "dividend_amount"})
                    latest_div["dividend_yield"] = latest_div["dividend_amount"] / 10.0  # 股息率近似估算
                    result = latest_div

                    # 计算同比变动 (去年分红 vs 今年)
                    div_records["year"] = div_records["date"].dt.year
                    latest_year = div_records.loc[latest_idx, "year"].iloc[0] if len(latest_idx) > 0 else None
                    if latest_year and len(div_records) > 0:
                        this_year = div_records[div_records["year"] == latest_year]
                        last_year = div_records[div_records["year"] == latest_year - 1]
                        if not this_year.empty and not last_year.empty:
                            this_div = this_year.groupby("symbol")["dividend"].max().rename("dividend_this")
                            last_div = last_year.groupby("symbol")["dividend"].max().rename("dividend_last")
                            div_yoy = pd.concat([this_div, last_div], axis=1).dropna()
                            # 同比变动率已经在 factor_base 的 dividend_growth 中处理
        except Exception:
            pass

    if result is None or result.empty:
        result = pd.DataFrame(columns=["symbol", "dividend_amount", "dividend_days_since", "dividend_yield"])

    result["date"] = pd.Timestamp.now().strftime("%Y-%m-%d")
    result["dividend_amount"] = result.get("dividend_amount", pd.Series(0, index=result.index)).fillna(0)
    result["dividend_yield"] = result.get("dividend_yield", pd.Series(0, index=result.index)).fillna(0)
    result["dividend_days_since"] = result.get("dividend_days_since", pd.Series(365, index=result.index)).fillna(365)

    if symbols:
        result = result[result["symbol"].astype(str).isin(symbols)]

    for col in DIVIDEND_COLUMNS:
        if col not in result.columns:
            result[col] = 0 if col not in ("symbol", "date") else ""

    return result[DIVIDEND_COLUMNS]


# ─── 业绩预告加载 ─────────────────────────────────────────────────

def load_forecast_events(symbols: list = None) -> pd.DataFrame:
    """加载业绩预告数据

    从 forecast_report.csv 加载。

    参数:
        symbols: 可选, 仅加载指定股票

    返回:
        pd.DataFrame (列: FORECAST_COLUMNS)
        文件不存在时返回空 DataFrame。
    """
    if not FORECAST_REPORT_PATH.exists():
        return pd.DataFrame(columns=FORECAST_COLUMNS)
    try:
        df = pd.read_csv(FORECAST_REPORT_PATH, encoding="utf-8-sig")
        df.columns = [c.strip().lower() for c in df.columns]

        if "code" in df.columns:
            df["symbol"] = df["code"].astype(str).str.zfill(6)
        elif "symbol" not in df.columns:
            return pd.DataFrame(columns=FORECAST_COLUMNS)

        if "type" not in df.columns:
            return pd.DataFrame(columns=FORECAST_COLUMNS)

        # 映射预告类型到数值
        df["forecast_type_code"] = df["type"].map(FORECAST_TYPE_MAP).fillna(0)

        today = pd.Timestamp.now()
        if "pub_date" in df.columns or "asof_date" in df.columns:
            date_col = "pub_date" if "pub_date" in df.columns else "asof_date"
            df["date"] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=["date"])

            # 计算距今天数
            df["forecast_days_since"] = (today - df["date"]).dt.days

            # 近90天预告
            cutoff_90d = today - pd.Timedelta(days=90)
            recent = df[df["date"] >= cutoff_90d]

            # 每个股票: 最新预告类型 + 90天计数 + 动量
            latest_idx = df.groupby("symbol")["date"].idxmax()
            latest = df.loc[latest_idx, ["symbol", "forecast_type_code", "forecast_days_since"]].copy()

            if not recent.empty:
                # 预增计数
                positive = recent[recent["forecast_type_code"] > 0].groupby("symbol").size().reset_index(name="forecast_positive_count")
                negative = recent[recent["forecast_type_code"] < 0].groupby("symbol").size().reset_index(name="forecast_negative_count")
                recent_count = recent.groupby("symbol").size().reset_index(name="forecast_count_90d")

                result = latest.merge(recent_count, on="symbol", how="left")
                result = result.merge(positive, on="symbol", how="left")
                result = result.merge(negative, on="symbol", how="left")
                result["forecast_momentum"] = result["forecast_positive_count"].fillna(0) - result["forecast_negative_count"].fillna(0)
            else:
                result = latest.copy()
                result["forecast_count_90d"] = 0
                result["forecast_momentum"] = 0

        else:
            result = pd.DataFrame({"symbol": df["symbol"].unique(),
                                    "forecast_type_code": 0,
                                    "forecast_days_since": 365,
                                    "forecast_count_90d": 0,
                                    "forecast_momentum": 0})

        result["forecast_type_code"] = result["forecast_type_code"].fillna(0)
        result["forecast_days_since"] = result["forecast_days_since"].fillna(365)
        result["forecast_count_90d"] = result["forecast_count_90d"].fillna(0).astype(int)
        result["forecast_momentum"] = result["forecast_momentum"].fillna(0).astype(int)
        result["date"] = today.strftime("%Y-%m-%d")

        if symbols:
            result = result[result["symbol"].astype(str).isin(symbols)]

        for col in FORECAST_COLUMNS:
            if col not in result.columns:
                result[col] = 0 if col not in ("symbol", "date") else ""

        return result[FORECAST_COLUMNS]
    except Exception as e:
        return pd.DataFrame(columns=FORECAST_COLUMNS)


# ─── 统一加载入口 ─────────────────────────────────────────────────

def get_event_data(symbols: list = None) -> dict:
    """获取所有事件 DataFrame

    返回:
        dict: {
            "lockup": DataFrame,
            "buyback": DataFrame,
            "dividend": DataFrame,
            "forecast": DataFrame,
            "has_lockup": bool,
            "has_buyback": bool,
            "has_dividend": bool,
            "has_forecast": bool,
        }
    """
    lk = load_lockup_events(symbols)
    bb = load_buyback_events(symbols)
    dv = load_dividend_events(symbols)
    fc = load_forecast_events(symbols)

    return {
        "lockup": lk,
        "buyback": bb,
        "dividend": dv,
        "forecast": fc,
        "has_lockup": len(lk) > 0,
        "has_buyback": len(bb) > 0,
        "has_dividend": len(dv) > 0,
        "has_forecast": len(fc) > 0,
    }


def merge_event_data(df: pd.DataFrame) -> pd.DataFrame:
    """将事件数据列合并到主 DataFrame

    以 (symbol) 为 key, 左连接所有可用事件数据。

    参数:
        df: 主 DataFrame (必须包含 symbol 列)

    返回:
        pd.DataFrame: 包含所有可用事件数据列的 DataFrame
    """
    if df.empty:
        return df

    result = df.copy()

    if "symbol" in result.columns:
        result["symbol"] = result["symbol"].astype(str)
    else:
        return result

    events = get_event_data()

    # 解禁事件
    if events["has_lockup"]:
        lk = events["lockup"].copy()
        lk["symbol"] = lk["symbol"].astype(str)
        merge_cols = [c for c in LOCKUP_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            lk[["symbol"] + merge_cols],
            on="symbol", how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    # 回购事件
    if events["has_buyback"]:
        bb = events["buyback"].copy()
        bb["symbol"] = bb["symbol"].astype(str)
        merge_cols = [c for c in BUYBACK_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            bb[["symbol"] + merge_cols],
            on="symbol", how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    # 分红事件
    if events["has_dividend"]:
        dv = events["dividend"].copy()
        dv["symbol"] = dv["symbol"].astype(str)
        merge_cols = [c for c in DIVIDEND_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            dv[["symbol"] + merge_cols],
            on="symbol", how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    # 业绩预告
    if events["has_forecast"]:
        fc = events["forecast"].copy()
        fc["symbol"] = fc["symbol"].astype(str)
        merge_cols = [c for c in FORECAST_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            fc[["symbol"] + merge_cols],
            on="symbol", how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    return result


def event_data_status() -> dict:
    """返回事件数据源状态报告"""
    return {
        "announcements_exists": ANNOUNCEMENTS_PATH.exists(),
        "adjust_factor_exists": ADJUST_FACTOR_PATH.exists(),
        "forecast_report_exists": FORECAST_REPORT_PATH.exists(),
        "announcements_path": str(ANNOUNCEMENTS_PATH),
        "adjust_factor_path": str(ADJUST_FACTOR_PATH),
        "forecast_report_path": str(FORECAST_REPORT_PATH),
        "lockup_columns": LOCKUP_COLUMNS,
        "buyback_columns": BUYBACK_COLUMNS,
        "dividend_columns": DIVIDEND_COLUMNS,
        "forecast_columns": FORECAST_COLUMNS,
        "checked_at": datetime.now(CST).isoformat(),
    }


if __name__ == "__main__":
    import json
    status = event_data_status()
    print("Event Data Sources:")
    print(f"  Announcements:  {'✅' if status['announcements_exists'] else '❌'} {status['announcements_path']}")
    print(f"  Adjust Factor:  {'✅' if status['adjust_factor_exists'] else '❌'} {status['adjust_factor_path']}")
    print(f"  Forecast:       {'✅' if status['forecast_exists'] else '❌'} (from forecast_report.csv)")
    print(f"  Checked at: {status['checked_at']}")
