"""Data Enrichment Loader V3.3 — 北向/两融/资金流 数据加载

为 Data Enrichment Alpha Pack 提供统一的数据加载接口。
数据源:
1. fund_flow_timeseries.csv — 资金流向 (net_main_force, net_super_large, etc.)
2. north_flow_timeseries.csv — 北向资金 (nb_net_flow, nb_holding, etc.)
3. margin_timeseries.csv — 两融 (margin_buy, margin_balance, sec_lending, etc.)

所有加载器在数据缺失时优雅降级, 返回空 DataFrame 而非崩溃。

用法:
    from factor_lab.alpha.data_enrichment_loader import (
        load_fund_flow, load_north_flow, load_margin,
        get_enriched_data
    )
    df = get_enriched_data(symbols=["000001", "000002"])
"""

from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

from factor_lab.datahub_access import DATAHUB_ROOT, read_fund_flow_partitions

CST = timezone(timedelta(hours=8))

# ─── 路径 ─────────────────────────────────────────────────────────
HERMES_DATA = Path(__file__).resolve().parents[3] / "data"
FUND_FLOW_PATH = DATAHUB_ROOT / "fund_flow"
NORTH_FLOW_PATH = HERMES_DATA / "fundamentals" / "north_flow_timeseries.csv"
MARGIN_PATH = HERMES_DATA / "fundamentals" / "margin_timeseries.csv"

# ─── 资金流字段 ──────────────────────────────────────────────────
FUND_FLOW_COLUMNS = [
    "symbol", "date",
    "net_main_force", "net_super_large", "net_large",
    "net_medium", "net_small",
    "days_inflow", "days_outflow",
]

# ─── 北向字段定义 (预期 CSV 列) ──────────────────────────────────
NORTH_FLOW_COLUMNS = [
    "symbol", "date",
    "nb_net_flow",       # 北向净流入 (万元)
    "nb_total_buy",      # 北向买入总额 (万元)
    "nb_total_sell",     # 北向卖出总额 (万元)
    "nb_holding_value",  # 北向持股市值 (万元)
    "nb_holding_ratio",  # 北向持股占流通A股比 (%)
]

MARGIN_COLUMNS = [
    "symbol", "date",
    "margin_buy",         # 融资买入额 (万元)
    "margin_repay",       # 融资偿还额 (万元)
    "margin_balance",     # 融资余额 (万元)
    "sec_lending_volume", # 融券卖出量 (万股)
    "sec_lending_balance",# 融券余额 (万元)
    "margin_ratio",       # 融资余额/流通市值 (%)
]

# ─── 资金流加载 ──────────────────────────────────────────────────

def load_fund_flow(symbols: list = None) -> pd.DataFrame:
    """加载资金流数据

    参数:
        symbols: 可选, 仅加载指定股票

    返回:
        pd.DataFrame (列: FUND_FLOW_COLUMNS)
        文件不存在时返回空 DataFrame。
    """
    if not symbols or not FUND_FLOW_PATH.exists():
        return pd.DataFrame(columns=FUND_FLOW_COLUMNS)
    try:
        df = read_fund_flow_partitions([str(symbol) for symbol in symbols], root=FUND_FLOW_PATH)
        df.columns = [c.strip().lower() for c in df.columns]
        # 确保列存在
        for col in FUND_FLOW_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0 if col not in ("symbol", "date") else ""
        return df
    except Exception:
        return pd.DataFrame(columns=FUND_FLOW_COLUMNS)


# ─── 北向资金加载 ────────────────────────────────────────────────

def load_north_flow(symbols: list = None) -> pd.DataFrame:
    """加载北向资金数据

    当文件不存在时返回空 DataFrame (所有数值列为 0)。
    字段说明:
        nb_net_flow: 北向净流入, >0 代表外资买入
        nb_holding_change: 北向持仓变动
        nb_flow_intensity: 净流入/成交额, 衡量外资参与度
    """
    if not NORTH_FLOW_PATH.exists():
        return pd.DataFrame(columns=NORTH_FLOW_COLUMNS)
    try:
        df = pd.read_csv(NORTH_FLOW_PATH, encoding="utf-8-sig")
        df.columns = [c.strip().lower() for c in df.columns]
        if symbols:
            df = df[df["symbol"].astype(str).isin(symbols)]
        for col in NORTH_FLOW_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0 if col not in ("symbol", "date") else ""
        return df
    except Exception:
        return pd.DataFrame(columns=NORTH_FLOW_COLUMNS)


# ─── 两融数据加载 ────────────────────────────────────────────────

def load_margin(symbols: list = None) -> pd.DataFrame:
    """加载两融(融资融券)数据

    当文件不存在时返回空 DataFrame (所有数值列为 0)。
    字段说明:
        margin_buy:          融资买入额, 反映做多意愿
        margin_repay:        融资偿还额
        margin_balance:      融资余额, 存量杠杆
        sec_lending_volume:  融券卖出量, 反映做空意愿
        sec_lending_balance: 融券余额
        margin_ratio:        融资余额/流通市值, 杠杆率
    """
    if not MARGIN_PATH.exists():
        return pd.DataFrame(columns=MARGIN_COLUMNS)
    try:
        df = pd.read_csv(MARGIN_PATH, encoding="utf-8-sig")
        df.columns = [c.strip().lower() for c in df.columns]
        if symbols:
            df = df[df["symbol"].astype(str).isin(symbols)]
        for col in MARGIN_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0 if col not in ("symbol", "date") else ""
        return df
    except Exception:
        return pd.DataFrame(columns=MARGIN_COLUMNS)


# ─── 统一加载入口 ─────────────────────────────────────────────────

def get_enriched_data(symbols: list = None) -> dict:
    """获取所有数据增强 DataFrame

    返回:
        dict: {
            "fund_flow": DataFrame,
            "north_flow": DataFrame,
            "margin": DataFrame,
            "has_fund_flow": bool,
            "has_north_flow": bool,
            "has_margin": bool,
        }
    """
    ff = load_fund_flow(symbols)
    nf = load_north_flow(symbols)
    mg = load_margin(symbols)

    return {
        "fund_flow": ff,
        "north_flow": nf,
        "margin": mg,
        "has_fund_flow": len(ff) > 0,
        "has_north_flow": len(nf) > 0,
        "has_margin": len(mg) > 0,
    }


def merge_enriched(df: pd.DataFrame) -> pd.DataFrame:
    """将数据增强列合并到主 DataFrame

    以 (symbol, date) 为 key, 左连接所有可用数据。

    参数:
        df: 主 DataFrame (必须包含 symbol, date 列)

    返回:
        pd.DataFrame: 包含所有可用数据增强列的 DataFrame
        缺失的列填充为 0。
    """
    if df.empty:
        return df

    result = df.copy()

    # 确保 key 列类型一致
    if "symbol" in result.columns:
        result["symbol"] = result["symbol"].astype(str)
    if "date" in result.columns:
        result["date"] = result["date"].astype(str)

    symbols = result["symbol"].dropna().astype(str).unique().tolist() if "symbol" in result else []
    enriched = get_enriched_data(symbols)

    # 资金流
    if enriched["has_fund_flow"]:
        ff = enriched["fund_flow"].copy()
        ff["symbol"] = ff["symbol"].astype(str)
        ff["date"] = ff["date"].astype(str)
        merge_cols = [c for c in FUND_FLOW_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            ff[["symbol", "date"] + merge_cols],
            on=["symbol", "date"], how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    # 北向
    if enriched["has_north_flow"]:
        nf = enriched["north_flow"].copy()
        nf["symbol"] = nf["symbol"].astype(str)
        nf["date"] = nf["date"].astype(str)
        merge_cols = [c for c in NORTH_FLOW_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            nf[["symbol", "date"] + merge_cols],
            on=["symbol", "date"], how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    # 两融
    if enriched["has_margin"]:
        mg = enriched["margin"].copy()
        mg["symbol"] = mg["symbol"].astype(str)
        mg["date"] = mg["date"].astype(str)
        merge_cols = [c for c in MARGIN_COLUMNS if c not in ("symbol", "date")]
        result = result.merge(
            mg[["symbol", "date"] + merge_cols],
            on=["symbol", "date"], how="left"
        )
        for c in merge_cols:
            if c in result.columns:
                result[c] = result[c].fillna(0)

    return result


def load_fund_flow_timeseries(symbols: list | None = None) -> pd.DataFrame:
    """Compatibility helper requiring an explicit symbol scope."""
    return load_fund_flow(symbols)


def data_enrichment_status() -> dict:
    """返回数据增强数据源状态报告"""
    return {
        "fund_flow_exists": FUND_FLOW_PATH.exists(),
        "north_flow_exists": NORTH_FLOW_PATH.exists(),
        "margin_exists": MARGIN_PATH.exists(),
        "fund_flow_path": str(FUND_FLOW_PATH),
        "north_flow_path": str(NORTH_FLOW_PATH),
        "margin_path": str(MARGIN_PATH),
        "fund_flow_columns": FUND_FLOW_COLUMNS,
        "north_flow_columns": NORTH_FLOW_COLUMNS,
        "margin_columns": MARGIN_COLUMNS,
        "checked_at": datetime.now(CST).isoformat(),
    }


if __name__ == "__main__":
    status = data_enrichment_status()
    print("Data Enrichment Data Sources:")
    print(f"  Fund Flow:     {'✅' if status['fund_flow_exists'] else '❌'} {status['fund_flow_path']}")
    print(f"  North Flow:    {'✅' if status['north_flow_exists'] else '❌'} {status['north_flow_path']}")
    print(f"  Margin:        {'✅' if status['margin_exists'] else '❌'} {status['margin_path']}")
    print(f"  Checked at: {status['checked_at']}")
