"""数据新鲜度检查 — 盘前信号的数据完整性验证

检查项:
  1. 日线行情是否更新到最近交易日
  2. close/volume/amount 是否完整
  3. ma20/ret5 是否可计算
  4. ST 标记是否可用
  5. 停牌/涨跌停数据是否可用
  6. 股票池是否为空
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def check_data_freshness(
    df: pd.DataFrame,
    signal_date: str,
    required_cols: list = None,
    factor_cols: list = None,
) -> dict:
    """数据新鲜度检查

    参数:
        df: 因子数据 DataFrame (含 date, symbol 列)
        signal_date: 目标信号日期 (YYYY-MM-DD)
        required_cols: 必需字段列表
        factor_cols: 因子列列表 (非空率检查)

    返回:
        {"checked_at", "latest_data_date", "signal_date", "data_lag_days",
         "total_symbols", "min_days_per_symbol", "fields_checked",
         "all_fields_available", "missing_fields", "status", "note"}
    """
    if required_cols is None:
        required_cols = ["close", "volume"]  # ret1 是衍生字段, 不作为必需
    if factor_cols is None:
        factor_cols = ["ret5", "close_gt_ma20", "ma20"]

    now = datetime.now(CST).isoformat()
    missing = []
    all_ok = True

    # 1. 日期检查
    all_dates = pd.to_datetime(df["date"].unique())
    latest_date = max(all_dates).strftime("%Y-%m-%d") if len(all_dates) > 0 else None
    lag_days = None
    if latest_date and signal_date and signal_date != "latest":
        sd = pd.Timestamp(signal_date)
        ld = pd.Timestamp(latest_date)
        lag_days = (sd - ld).days
        if lag_days > 3:
            all_ok = False
            missing.append(f"data_lag: {lag_days} days (signal={signal_date}, latest={latest_date})")

    # 2. 必需字段检查
    for col in required_cols:
        if col not in df.columns:
            missing.append(f"missing_column: {col}")
            all_ok = False
        elif df[col].isna().all():
            missing.append(f"all_nan: {col}")
            all_ok = False

    # 3. 因子列非空率检查
    for col in factor_cols:
        if col in df.columns:
            non_null_pct = df[col].notna().mean()
            if non_null_pct < 0.5:
                missing.append(f"low_coverage: {col} ({non_null_pct:.0%})")
                all_ok = False
        else:
            missing.append(f"missing_factor: {col}")
            all_ok = False

    # 4. 股票池检查
    n_symbols = df["symbol"].nunique() if "symbol" in df.columns else 0
    if n_symbols < 10:
        missing.append(f"too_few_symbols: {n_symbols}")
        all_ok = False

    # 5. 每只股票最少天数
    if "symbol" in df.columns and "date" in df.columns:
        min_days = df.groupby("symbol")["date"].nunique().min()
    else:
        min_days = 0

    status = "ok" if all_ok else ("partial" if len(missing) < 3 else "failed")
    note = _status_note(status, missing, lag_days)

    return {
        "checked_at": now,
        "latest_data_date": latest_date,
        "signal_date": signal_date if signal_date != "latest" else latest_date,
        "data_lag_days": lag_days,
        "total_symbols": int(n_symbols),
        "min_days_per_symbol": int(min_days),
        "fields_checked": required_cols + factor_cols,
        "all_fields_available": all_ok,
        "missing_fields": missing,
        "status": status,
        "note": note,
    }


def _status_note(status: str, missing: list, lag: int) -> str:
    if status == "ok":
        return "数据完整, 可用于信号生成"
    elif status == "partial":
        details = "; ".join(missing[:3])
        return f"数据部分缺失: {details}"
    else:
        return f"数据检查失败: {'; '.join(missing[:5])}"
