"""因子计算引擎 — 加载数据 → 批量算因子"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
KLINE = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")
FUND_CSV = Path("/home/ly/.hermes/research-assistant/data/fundamentals/fundamentals_timeseries.csv")
FUND_FIELDS = ["roe", "net_margin", "gross_margin", "debt_ratio", "eps", "net_profit", "revenue"]
FLOW_CSV = Path("/home/ly/.hermes/research-assistant/data/fundamentals/fund_flow_timeseries.csv")
FLOW_FIELDS = ["net_main_force", "net_super_large", "net_large", "net_medium", "net_small", "days_inflow", "days_outflow"]
SENTIMENT_CSV = Path("/home/ly/.hermes/research-assistant/data/fundamentals/news_sentiment_timeseries.csv")
SENTIMENT_FIELDS = ["sentiment_score", "positive_count", "negative_count", "neutral_count"]


def load_fundamentals() -> pd.DataFrame:
    """加载基本面时序数据（多季度，含 pub_date 用于前瞻对齐）"""
    if not FUND_CSV.exists():
        print("  ⚠️ 基本面数据文件不存在，跳过")
        return pd.DataFrame()
    fund = pd.read_csv(FUND_CSV, encoding="utf-8-sig", dtype={"symbol": str})
    if fund.empty:
        return fund
    fund["pub_date"] = pd.to_datetime(fund["pub_date"])
    fund["report_date"] = pd.to_datetime(fund["report_date"])

    # 数值化
    for col in FUND_FIELDS:
        if col in fund.columns:
            fund[col] = pd.to_numeric(fund[col], errors="coerce")

    # 每个股票按 pub_date 排序
    fund = fund.sort_values(["symbol", "pub_date"]).reset_index(drop=True)
    # 移除完全 NaN 的行
    fund = fund.dropna(subset=FUND_FIELDS, how="all")
    return fund


def merge_fundamentals(kline_df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    """将基本面数据前瞻对齐到日 K 线

    逻辑：对每个交易日，取该日之前最新一期的已发布财报数据
    （用 pub_date 做 as-of join，防止未来函数）
    """
    if fund_df.empty:
        return kline_df

    df = kline_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    # 对每只股票做 as-of merge
    result_rows = []
    for sym, grp in df.groupby("symbol"):
        sym_fund = fund_df[fund_df["symbol"] == sym].sort_values("pub_date")
        grp = grp.sort_values("date")

        if sym_fund.empty:
            # 无基本面数据，填充 NaN
            for col in FUND_FIELDS:
                grp[col] = np.nan
            result_rows.append(grp)
            continue

        # as-of merge: 对每个交易日，取 pub_date 之前的最近一期财报
        merged = pd.merge_asof(
            grp.sort_values("date"),
            sym_fund[["pub_date"] + FUND_FIELDS].sort_values("pub_date"),
            left_on="date", right_on="pub_date",
            direction="backward",  # 取最近一期已发布的
        )
        # 删除多余的 pub_date 列（保留用于验证）
        result_rows.append(merged)

    result = pd.concat(result_rows, ignore_index=True)
    # 日期还没发布的数据用前一期填充
    for col in FUND_FIELDS:
        if col in result.columns:
            result[col] = result.groupby("symbol")[col].ffill()

    return result


def load_fund_flow() -> pd.DataFrame:
    """加载资金流向时序数据"""
    if not FLOW_CSV.exists():
        print("  ⚠️ 资金流向数据文件不存在，跳过")
        return pd.DataFrame()
    flow = pd.read_csv(FLOW_CSV, encoding="utf-8-sig", dtype={"symbol": str})
    if flow.empty:
        return flow
    flow["date"] = pd.to_datetime(flow["date"])
    for col in FLOW_FIELDS:
        if col in flow.columns:
            flow[col] = pd.to_numeric(flow[col], errors="coerce")
    return flow


def merge_fund_flow(kline_df: pd.DataFrame, flow_df: pd.DataFrame) -> pd.DataFrame:
    """将资金流向数据按日期+股票合并到 K 线"""
    if flow_df.empty:
        return kline_df
    df = kline_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    flow_df = flow_df.copy()
    flow_df["date"] = pd.to_datetime(flow_df["date"])
    
    # 左连接: 按 symbol + date
    merged = df.merge(flow_df, on=["symbol", "date"], how="left")
    # 没有数据的填充 0
    for col in FLOW_FIELDS:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    return merged


def load_sentiment() -> pd.DataFrame:
    """加载新闻情绪时序数据"""
    if not SENTIMENT_CSV.exists():
        print("  ⚠️ 新闻情绪数据文件不存在，跳过")
        return pd.DataFrame()
    s = pd.read_csv(SENTIMENT_CSV, encoding="utf-8-sig", dtype={"symbol": str})
    if s.empty:
        return s
    s["date"] = pd.to_datetime(s["date"])
    for col in SENTIMENT_FIELDS:
        if col in s.columns:
            s[col] = pd.to_numeric(s[col], errors="coerce")
    return s


def merge_sentiment(kline_df: pd.DataFrame, sent_df: pd.DataFrame) -> pd.DataFrame:
    """将新闻情绪数据合并到 K 线"""
    if sent_df.empty:
        return kline_df
    df = kline_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    sent_df = sent_df.copy()
    sent_df["date"] = pd.to_datetime(sent_df["date"])
    merged = df.merge(sent_df, on=["symbol", "date"], how="left")
    for col in SENTIMENT_FIELDS:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    return merged


def load_stock_kline(symbols: list, start_date: str = "2025-01-01",
                     end_date: str = "2026-06-30", min_days: int = 60) -> pd.DataFrame:
    """加载多只股票的 K 线数据 + 基本面数据

    过滤条件:
      - 有效时间范围: start_date ~ end_date
      - 单只股票数据不足 min_days 个交易日则剔除
    """
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

    # 过滤交易天数不足的股票
    valid = all_df.groupby("symbol")["date"].nunique()
    keep = valid[valid >= min_days].index
    before = all_df["symbol"].nunique()
    all_df = all_df[all_df["symbol"].isin(keep)].copy()
    after = all_df["symbol"].nunique()
    if before != after:
        print(f"  过滤: {before - after} 只股票不足 {min_days} 个交易日, 保留 {after} 只")

    # 合并且对齐基本面数据
    fund_df = load_fundamentals()
    if not fund_df.empty:
        n_before = len(all_df.columns)
        all_df = merge_fundamentals(all_df, fund_df)
        n_after = len(all_df.columns)
        added = [c for c in FUND_FIELDS if c in all_df.columns]
        print(f"  📊 基本面: {len(added)} 个字段已合并 ({', '.join(added)})")

    # 合并资金流向数据
    flow_df = load_fund_flow()
    if not flow_df.empty:
        n_before = len(all_df.columns)
        all_df = merge_fund_flow(all_df, flow_df)
        n_after = len(all_df.columns)
        added = [c for c in FLOW_FIELDS if c in all_df.columns]
        print(f"  💰 资金流向: {len(added)} 个字段已合并 ({', '.join(added)})")

    # 合并新闻情绪数据
    sent_df = load_sentiment()
    if not sent_df.empty:
        n_before = len(all_df.columns)
        all_df = merge_sentiment(all_df, sent_df)
        n_after = len(all_df.columns)
        added = [c for c in SENTIMENT_FIELDS if c in all_df.columns]
        print(f"  📰 新闻情绪: {len(added)} 个字段已合并 ({', '.join(added)})")

    return all_df

def compute_all(kline_df: pd.DataFrame) -> pd.DataFrame:
    """批量计算所有因子（两阶段：先算基础因子，再算进化组合因子）"""
    from factor_lab.factor_base import REGISTRY, _load_evolved
    _load_evolved()
    # 第一阶段：算非 evolved 的基础因子
    results = {}
    for f in REGISTRY:
        if f["category"] == "evolved":
            continue
        try:
            s = f["func"](kline_df, **f["params"])
            results[f["name"]] = s
        except Exception:
            results[f["name"]] = pd.Series(np.nan, index=kline_df.index)
    
    # 把基础因子合并到 kline_df，供进化因子引用
    temp_df = kline_df.copy()
    for col, s in results.items():
        temp_df[col] = s.values
    
    # 第二阶段：算进化因子
    for f in REGISTRY:
        if f["category"] != "evolved":
            continue
        try:
            s = f["func"](temp_df)
            results[f["name"]] = s
        except Exception:
            results[f["name"]] = pd.Series(0.0, index=kline_df.index)
    
    # 合并输出
    out = kline_df[["date", "symbol", "close"]].copy()
    if "ret1" in kline_df.columns:
        out["ret1"] = kline_df["ret1"].values
    for col in results:
        out[col] = results[col].values
    return out