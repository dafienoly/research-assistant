"""因子计算引擎 — 加载数据 → 批量算因子"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta, timezone

from factor_lab.datahub_access import daily_kline_path, factor_input_locations, read_stock_industry_map

CST = timezone(timedelta(hours=8))
_INPUTS = factor_input_locations()
KLINE = _INPUTS.daily_kline

# 基本面
FUND_CSV = _INPUTS.fundamentals
FUND_FIELDS = [
    # 原有
    "roe", "net_margin", "gross_margin", "debt_ratio", "eps", "net_profit", "revenue",
    # V3.2.2 新增 — 估值/成长/综合质量
    "pe_ttm", "pb_lf", "ps_ttm", "pcf_ttm",
    "roe_ttm", "roa_ttm",
    "revenue_growth_q", "profit_growth_q", "profit_surprise",
    "current_ratio", "asset_turnover",
    "dividend_yield", "free_cash_flow_yield",
]

# 资金流向
FLOW_CSV = _INPUTS.fund_flow
FLOW_FIELDS = ["net_main_force", "net_super_large", "net_large", "net_medium", "net_small", "days_inflow", "days_outflow"]

# 北向资金
NORTH_CSV = _INPUTS.north_flow
NORTH_FIELDS = ["nb_net_flow", "nb_total_buy", "nb_total_sell", "nb_holding_value", "nb_holding_ratio"]

# 两融
MARGIN_CSV = _INPUTS.margin
MARGIN_FIELDS = ["margin_buy", "margin_repay", "margin_balance", "margin_ratio", "sec_lending_volume", "sec_lending_balance"]

# 综合事件
EVENT_CSV = _INPUTS.events
EVENT_FIELDS = ["event_type", "event_desc", "impact_score"]

# 新闻情绪
SENTIMENT_CSV = _INPUTS.sentiment
SENTIMENT_FIELDS = ["sentiment_score", "positive_count", "negative_count", "neutral_count"]


def _load_csv(path: Path, fields: list[str]) -> pd.DataFrame:
    """加载通用 CSV: 检查存在→读取→符号补齐→日期规范化→数值化"""
    if not path.exists():
        print(f"  ⚠️ {path.name} 不存在，跳过")
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"symbol": str})
    if df.empty:
        return df
    required = {"symbol", "date"}
    missing_required = required - set(df.columns)
    available_fields = [field for field in fields if field in df.columns]
    if missing_required or not available_fields:
        print(
            f"  ⚠️ {path.name} schema 不兼容，跳过: "
            f"missing={sorted(missing_required)}, fields={available_fields}"
        )
        return pd.DataFrame()
    df["symbol"] = df["symbol"].str.strip().str.zfill(6)
    # 日期列兼容多种格式:
    #   整数类型(20260705) → 先转 str, 再用 %Y%m%d 解析
    #   字符串类型(2026-07-03 / 20260707 12:42) → mixed 解析 + normalize
    if df["date"].dtype in ("int64", "Int64", "float64", "Float64"):
        df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    else:
        df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    df["date"] = df["date"].dt.normalize()  # 去掉时间分量
    for col in available_fields:
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
    # 只对实际存在的列做 dropna（有些 V3.2.2 新增字段可能尚未拉取）
    existing_fund_fields = [c for c in FUND_FIELDS if c in fund.columns]
    if existing_fund_fields:
        fund = fund.dropna(subset=existing_fund_fields, how="all")

    # 检查 V3.2.2 新增字段是否缺失
    extra_fields = [
        "pe_ttm", "pb_lf", "ps_ttm", "pcf_ttm",
        "roe_ttm", "roa_ttm",
        "revenue_growth_q", "profit_growth_q", "profit_surprise",
        "current_ratio", "asset_turnover",
        "dividend_yield", "free_cash_flow_yield",
    ]
    missing = [col for col in extra_fields if col not in fund.columns]
    if missing:
        print(f"  ⚠️ 基本面CSV缺少 {len(missing)}/{len(extra_fields)} 个新增字段: {missing}")
        print("    → 这些字段对应的因子将不可用, 请更新数据源后重新拉取")
    else:
        print(f"  ✅ 基本面CSV包含全部 {len(extra_fields)} 个V3.2.2新增字段")
    return fund


def merge_fundamentals(kline_df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    if fund_df.empty:
        return kline_df
    df = kline_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    # 只合并在 fund_df 中实际存在的列（V3.2.2 新增字段可能尚未拉取）
    existing_ff = [c for c in FUND_FIELDS if c in fund_df.columns]
    if not existing_ff:
        return kline_df
    result_rows = []
    for sym, grp in df.groupby("symbol"):
        sym_fund = fund_df[fund_df["symbol"] == sym].sort_values("pub_date")
        grp = grp.sort_values("date")
        if sym_fund.empty:
            for col in existing_ff:
                grp[col] = np.nan
            result_rows.append(grp)
            continue
        merged = pd.merge_asof(
            grp.sort_values("date"),
            sym_fund[["pub_date"] + existing_ff].sort_values("pub_date"),
            left_on="date", right_on="pub_date",
            direction="backward",
        )
        result_rows.append(merged)
    result = pd.concat(result_rows, ignore_index=True)
    for col in existing_ff:
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
        try:
            source = daily_kline_path(str(sym), root=KLINE)
        except FileNotFoundError:
            continue
        try:
            df = pd.read_csv(source, encoding="utf-8-sig")
            df = df.rename(columns={"trade_date": "date", "vol": "volume"})
            if "date" not in df.columns:
                continue
            df["symbol"] = sym
            rows.append(df)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    all_df = pd.concat(rows, ignore_index=True)
    raw_dates = all_df["date"].astype("string").str.replace(r"\.0$", "", regex=True)
    compact = raw_dates.str.fullmatch(r"\d{8}", na=False)
    parsed_dates = pd.to_datetime(raw_dates, errors="coerce")
    parsed_dates.loc[compact] = pd.to_datetime(raw_dates.loc[compact], format="%Y%m%d", errors="coerce")
    all_df["date"] = parsed_dates
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


def _load_industry_map() -> dict:
    """加载 canonical DataHub symbol→行业映射，不在因子层触发外部拉取。"""
    try:
        result = read_stock_industry_map()
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"  ⚠️ canonical DataHub 行业映射不可用: {exc}")
        return {}

    print(f"  🏭 行业映射加载: {len(result)} 条 (from DataHub stock_basic)")
    return result


def compute_all(kline_df: pd.DataFrame) -> pd.DataFrame:
    """批量计算所有因子"""
    from factor_lab.factor_base import REGISTRY, _load_evolved

    # ─── 自动合并行业分类 ─────────────────────────────
    if "industry" not in kline_df.columns:
        industry_map = _load_industry_map()
        if industry_map:
            kline_df["industry"] = kline_df["symbol"].map(industry_map).fillna("unknown")
        else:
            kline_df["industry"] = "unknown"
        n_industries = kline_df["industry"].nunique()
        print(f"  🏭 行业分类已合并: {n_industries} 个行业, {kline_df['industry'].isna().sum()} 缺失")
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

    # 用 pd.concat 一次性合并所有因子列（避免 DataFrame fragmentation）
    factor_cols = pd.DataFrame(results, index=kline_df.index)

    # 补全推导列（供表达式解析器使用）
    derived = {}
    if "ret1" not in kline_df.columns and "close" in kline_df.columns:
        derived["ret1"] = kline_df.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(1)
        ).fillna(0)
    if "returns" not in kline_df.columns and "ret1" in derived:
        derived["returns"] = derived["ret1"]
    if "vwap" not in kline_df.columns:
        denom = kline_df["volume"].replace(0, np.nan) if "volume" in kline_df.columns else np.nan
        if "amount" in kline_df.columns and denom is not np.nan:
            derived["vwap"] = kline_df["amount"] / denom
        else:
            derived["vwap"] = kline_df["close"]
    derived_cols = pd.DataFrame(derived, index=kline_df.index) if derived else pd.DataFrame()

    temp_df = pd.concat([kline_df, factor_cols, derived_cols], axis=1)

    for f in REGISTRY:
        if f["category"] != "evolved":
            continue
        try:
            s = f["func"](temp_df)
            results[f["name"]] = s
        except Exception as e:
            print(f"  ⚠️ 进化因子计算失败 {f['name']}: {e}")
            results[f["name"]] = pd.Series(np.nan, index=kline_df.index)

    out = kline_df[["date", "symbol", "close"]].copy()
    if "ret1" in kline_df.columns:
        out["ret1"] = kline_df["ret1"].values
    for col in results:
        out[col] = results[col].values
    return out
