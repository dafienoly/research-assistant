"""资金流兼容入口；业务消费只读 canonical DataHub 分区。"""

from __future__ import annotations

import json
import sys

import pandas as pd

from factor_lab.datahub_access import read_fund_flow_partitions, read_trade_calendar


def extract_stock_fund_flow(code: str) -> dict:
    """返回单标的最新 canonical 资金流；缺失时显式 MISSING。"""
    digits = "".join(character for character in str(code) if character.isdigit())[:6]
    if len(digits) != 6:
        return {"code": str(code), "type": "stock", "data_status": "INVALID", "error": "invalid stock code"}
    frame = read_fund_flow_partitions([digits])
    if frame.empty:
        return {
            "code": digits,
            "type": "stock",
            "data_status": "MISSING",
            "error": "canonical DataHub fund-flow partition unavailable",
        }
    row = frame.sort_values("date", kind="stable").iloc[-1]
    observed = pd.to_datetime(str(row["date"]), errors="coerce")
    calendar = read_trade_calendar()
    open_dates = pd.to_datetime(
        calendar.loc[calendar["is_open"] == 1, "cal_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    ).dropna()
    latest_open = open_dates.max() if not open_dates.empty else pd.NaT
    lag_days = None if pd.isna(observed) or pd.isna(latest_open) else int((latest_open - observed).days)
    status = "OK" if lag_days is not None and lag_days <= 7 else "STALE"
    values = {
        key: (None if value != value else float(value))
        for key, value in row.items()
        if key.startswith("net_")
    }
    return {
        "code": digits,
        "type": "stock",
        "data_status": status,
        "observed_at": str(row["date"]),
        "latest_open_date": None if pd.isna(latest_open) else latest_open.strftime("%Y%m%d"),
        "lag_days": lag_days,
        "source": "datahub:moneyflow",
        **values,
    }


def extract_market_fund_flow() -> dict:
    """市场汇总尚无 canonical owned dataset，明确 fail-closed。"""
    return {
        "type": "market",
        "data_status": "MISSING",
        "error": "canonical market-wide fund-flow dataset unavailable",
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "market":
        result = extract_market_fund_flow()
    elif len(sys.argv) > 1:
        result = extract_stock_fund_flow(sys.argv[1])
    else:
        print("用法: python3 fund_flow.py <代码>  |  python3 fund_flow.py market")
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
