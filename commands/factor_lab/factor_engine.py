"""因子计算引擎 — 加载数据 → 批量算因子"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
KLINE = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")

# 基本面
FUND_CSV = Path("/home/ly/.hermes/research-assistant/data/fundamentals/fundamentals_timeseries.csv")
FUND_FIELDS = ["roe", "net_margin", "gross_margin", "debt_ratio", "eps", "net_profit", "revenue"]

# 资金流向
FLOW_CSV = Path("/home/ly/.hermes/research-assistant/data/fundamentals/fund_flow_timeseries.csv")
FLOW_FIELDS = ["net_main_force", "net_super_large", "net_large", "net_medium", "net_small", "days_inflow", "days_outflow"]

# 北向资金
NORTH_CSV = Path("/home/ly/.hermes/research-assistant/data/north_flow_timeseries.csv")
NORTH_FIELDS = ["nb_net_flow", "nb_holding", "nb_total"]

# 两融
MARGIN_CSV = Path("/home/ly/.hermes/research-assistant/data/margin_timeseries.csv")
MARGIN_FIELDS = ["margin_buy", "margin_repay", "margin_balance", "sec_lending"]

# 综合事件
EVENT_CSV = Path("/home/ly/.hermes/research-assistant/data/event_timeseries.csv")
EVENT_FIELDS = ["event_type", "event_desc", "impact_score"]

# 新闻情绪
SENTIMENT_CSV = Path("/home/ly/.hermes/research-assistant/data/news_sentiment_timeseries.csv")
SENTIMENT_FIELDS = ["sentiment_score", "positive_count", "negative_count", "neutral_count"]


def _load_csv(path: Path, fields: list[str]) -> pd.DataFrame:
    """加载通用 CSV: 检查存在→读取→日期解析→数值化"""
    if not path.exists():
        print(f"  ⚠️ {path.name} 不存在，跳过")
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"symbol": str})
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    for col in fields:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _merge_left(kline_df: pd.DataFrame, src_df: pd.DataFrame, fields: list[str], label: str):
    """通用左合并: 按 symbol+date 合并并填充 0"""
    if src_df.empty:
        return kline_df
    df = kline_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    src = src_df.copy()
    src["date"] = pd.to_datetime(src["date"])
    merged = df.merge(src, on=["symbol", "date"], how="left")
    for col in fields:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    print(f"  {label}: {len([c for c in fields if c in merged.columns])} 个字段已合并")
    return merged


# ─── 基本面 (as-of merge, 防未来函数) ──────────────────

def load_fundamentals() -> pd.DataFrame:
    if not FUND_CSV.exists():
        print("  ⚠️ 基本面数据文件不存在，跳过")
        return pd.DataFrame()
    fund = pd.read_csv(FUND_CSV, encoding="utf-8-sig", dtype={"symbol": str})
    if fund.empty:
        return fund
    fund["pub_date"] = pd.to_datetime(fund["pub_date"])
    fund["report_date"] = pd.to_datetime(fund["report_date"])
    for col in FUND_FIELDS:
        if col in fund.columns:
            fund[col] = pd.to_numeric(fund[col], errors="coerce")
    fund = fund.sort_values(["symbol", "pub_date"]).reset_index(drop=True)
    fund = fund.dropna(subset=FUND_FIELDS, how="all")
    return fund


def merge_fundamentals(kline_df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    if fund_df.empty:
        return kline_df
    df = kline_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    result_rows = []
    for sym, grp in df.groupby("symbol"):
        sym_fund = fund_df[fund_df["symbol"] == sym].sort_values("pub_date")
        grp = grp.sort_values("date")
        if sym_fund.empty:
            for col in FUND_FIELDS:
                grp[col] = np.nan
            result_rows.append(grp)
            continue
        merged = pd.merge_asof(
            grp.sort_values("date"),
            sym_fund[["pub_date"] + FUND_FIELDS].sort_values("pub_date"),
            left_on="date", right_on="pub_date",
            direction="backward",
        )
        result_rows.append(merged)
    result = pd.concat(result_rows, ignore_index=True)
    for col in FUND_FIELDS:
        if col in result.columns:
            result[col] = result.groupby("symbol")[col].ffill()
    return result


# ─── 资金流向 ──────────────────

def load_fund_flow() -> pd.DataFrame:
    return _load_csv(FLOW_CSV, FLOW_FIELDS)


def merge_fund_flow(kline_df, flow_df):
    return _merge_left(kline_df, flow_df, FLOW_FIELDS, "💰 资金流向")


# ─── 北向资金 ──────────────────

def load_north_bound() -> pd.DataFrame:
    return _load_csv(NORTH_CSV, NORTH_FIELDS)


def merge_north_bound(kline_df, north_df):
    return _merge_left(kline_df, north_df, NORTH_FIELDS, "🌐 北向资金")


# ─── 两融数据 ──────────────────

def load_margin_trading() -> pd.DataFrame:
    return _load_csv(MARGIN_CSV, MARGIN_FIELDS)


def merge_margin_trading(kline_df, margin_df):
    return _merge_left(kline_df, margin_df, MARGIN_FIELDS, "💳 两融数据")


# ─── 综合事件 ──────────────────

def load_events() -> pd.DataFrame:
    return _load_csv(EVENT_CSV, EVENT_FIELDS)


def merge_events(kline_df, event_df):
    return _merge_left(kline_df, event_df, EVENT_FIELDS, "📅 事件数据")


# ─── 新闻情绪 ──────────────────

def load_sentiment() -> pd.DataFrame:
    return _load_csv(SENTIMENT_CSV, SENTIMENT_FIELDS)


def merge_sentiment(kline_df, sent_df):
    return _merge_left(kline_df, sent_df, SENTIMENT_FIELDS, "📰 新闻情绪")


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def load_stock_kline(symbols: list, start_date: str = "2025-01-01",
                     end_date: str = "2026-06-30", min_days: int = 60) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        f = KLINE / f"{sym}.csv"
        if not f.exists():
            continue
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            df["symbol"] = sym
            rows.append(df)
        except:
            continue
    if not rows:
        return pd.DataFrame()
    all_df = pd.concat(rows, ignore_index=True)
    all_df["date"] = pd.to_datetime(all_df["date"])
    all_df = all_df[(all_df["date"] >= start_date) & (all_df["date"] <= end_date)].copy()
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in all_df.columns:
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")
    all_df = all_df.sort_values(["symbol", "date"]).reset_index(drop=True)

    valid = all_df.groupby("symbol")["date"].nunique()
    keep = valid[valid >= min_days].index
    before = all_df["symbol"].nunique()
    all_df = all_df[all_df["symbol"].isin(keep)].copy()
    after = all_df["symbol"].nunique()
    if before != after:
        print(f"  过滤: {before - after} 只股票不足 {min_days} 个交易日, 保留 {after} 只")

    # 基本面 (as-of merge)
    fund_df = load_fundamentals()
    if not fund_df.empty:
        all_df = merge_fundamentals(all_df, fund_df)

    # 日频数据：左连接 symbol+date
    for loader, merger, label in [
        (load_fund_flow, merge_fund_flow, "资金流向"),
        (load_north_bound, merge_north_bound, "北向资金"),
        (load_margin_trading, merge_margin_trading, "两融数据"),
        (load_events, merge_events, "事件数据"),
        (load_sentiment, merge_sentiment, "新闻情绪"),
    ]:
        src = loader()
        if not src.empty:
            all_df = merger(all_df, src)

    return all_df


def compute_all(kline_df: pd.DataFrame) -> pd.DataFrame:
    """批量计算所有因子"""
    from factor_lab.factor_base import REGISTRY, _load_evolved
    _load_evolved()
    results = {}
    for f in REGISTRY:
        if f["category"] == "evolved":
            continue
        try:
            s = f["func"](kline_df, **f["params"])
            results[f["name"]] = s
        except Exception:
            results[f["name"]] = pd.Series(np.nan, index=kline_df.index)

    temp_df = kline_df.copy()
    for col, s in results.items():
        temp_df[col] = s.values

    for f in REGISTRY:
        if f["category"] != "evolved":
            continue
        try:
            s = f["func"](temp_df)
            results[f["name"]] = s
        except Exception:
            results[f["name"]] = pd.Series(0.0, index=kline_df.index)

    out = kline_df[["date", "symbol", "close"]].copy()
    if "ret1" in kline_df.columns:
        out["ret1"] = kline_df["ret1"].values
    for col in results:
        out[col] = results[col].values
    return out
