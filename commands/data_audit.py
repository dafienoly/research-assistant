#!/usr/bin/env python3
"""
V4.2 数据审计脚本 — coverage / freshness / missing / survivorship_check

基于 DataHub 统一目录 data/market/daily_kline/ 进行审计。
输出 JSON 报告到 data/audit/health/。

用法:
    from commands.data_audit import (
        coverage, freshness, missing, survivorship_check, run_all_audits
    )

    run_all_audits()

CLI:
    python3 hermes_cli.py data:coverage
    python3 hermes_cli.py data:survivorship
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ─── 目录 ────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # research-assistant/
NORMALIZED_DIR = BASE / "data" / "normalized"
LOCAL_DAILY_DIR = BASE / "data" / "market" / "daily_kline"
SHARED_DAILY_DIR = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")
DAILY_DIR = SHARED_DAILY_DIR if SHARED_DAILY_DIR.exists() else LOCAL_DAILY_DIR
EFFECTIVE_DAILY_DIR = DAILY_DIR
FINA_DIR = NORMALIZED_DIR / "fundamentals"      # 财务 CSV 目录
HEALTH_DIR = BASE / "data" / "audit" / "health"  # 审计输出目录


def _ensure_dirs():
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)


def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _today_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def _today_ymd() -> str:
    return datetime.now(CST).strftime("%Y%m%d")


def _list_csv_files(directory: Path) -> list[Path]:
    """列出目录下所有 .csv 文件"""
    if not directory.exists():
        return []
    return sorted(directory.glob("*.csv"))


def _read_csv(path: Path) -> pd.DataFrame:
    """安全读取 CSV 文件"""
    try:
        df = pd.read_csv(
            path, encoding="utf-8-sig",
            parse_dates=["trade_date"] if path.stat().st_size > 0 else False,
        )
        return df
    except Exception as e:
        logger.error(f"读取 {path} 失败: {e}")
        return pd.DataFrame()


def _daily_files() -> list[Path]:
    """List canonical daily files while retaining test monkeypatch compatibility."""
    if DAILY_DIR != EFFECTIVE_DAILY_DIR:
        files = _list_csv_files(DAILY_DIR)
        return [f for f in files if not f.name.startswith("valuation_")]
    by_code: dict[str, Path] = {}
    for root in (SHARED_DAILY_DIR, LOCAL_DAILY_DIR, NORMALIZED_DIR / "market"):
        for path in _list_csv_files(root):
            if not path.name.startswith("valuation_"):
                by_code[_code_from_path(path)] = path
    return sorted(by_code.values())


def _reference_stocks() -> list[dict[str, Any]]:
    """Load canonical security status without triggering an external provider."""

    path = NORMALIZED_DIR / "reference" / "stock_basic.csv"
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    except (OSError, UnicodeError, pd.errors.ParserError):
        return []
    required = {"ts_code", "list_status"}
    if frame.empty or not required.issubset(frame.columns):
        return []
    frame = frame.dropna(subset=["ts_code"]).copy()
    frame["ts_code"] = frame["ts_code"].str.strip().str.upper()
    frame["list_status"] = frame["list_status"].fillna("").str.strip().str.upper()
    return frame.to_dict(orient="records")


def _active_reference_codes(reference: list[dict[str, Any]]) -> set[str]:
    return {str(row["ts_code"]) for row in reference if row.get("list_status") == "L"}


def _active_daily_scope() -> tuple[list[Path], list[Path], list[dict[str, Any]]]:
    all_files = _daily_files()
    reference = _reference_stocks()
    active_codes = _active_reference_codes(reference)
    if not active_codes:
        return all_files, all_files, reference
    by_code = {_code_from_path(path): path for path in all_files}
    return [by_code[code] for code in sorted(active_codes & set(by_code))], all_files, reference


def _data_roots(files: list[Path]) -> list[str]:
    return sorted({str(path.parent) for path in files})


def _latest_open_day() -> datetime:
    calendar = NORMALIZED_DIR / "calendar" / "trade_calendar.csv"
    if calendar.exists():
        try:
            frame = pd.read_csv(calendar, encoding="utf-8-sig")
            dates = pd.to_datetime(frame.get("cal_date"), format="%Y%m%d", errors="coerce")
            is_open = pd.to_numeric(frame.get("is_open"), errors="coerce")
            today = datetime.now(CST).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
            eligible = dates[(is_open == 1) & (dates <= today)].dropna()
            if not eligible.empty:
                return eligible.max().to_pydatetime()
        except (OSError, UnicodeError, pd.errors.ParserError, TypeError, ValueError):
            pass
    return datetime.now(CST).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)


def _current_suspended_codes(as_of: datetime) -> set[str]:
    source = NORMALIZED_DIR / "suspend" / "records.csv"
    if not source.exists():
        return set()
    try:
        frame = _normalize_trade_date(pd.read_csv(source, encoding="utf-8-sig", dtype={"ts_code": "string"}))
    except (OSError, UnicodeError, pd.errors.ParserError):
        return set()
    if frame.empty or not {"ts_code", "trade_date"}.issubset(frame.columns):
        return set()
    current = frame[frame["trade_date"] == pd.Timestamp(as_of.date())]
    return set(current["ts_code"].dropna().astype("string").str.strip().str.upper())


def _code_from_path(path: Path) -> str:
    stem = path.stem.replace("_daily_kline", "")
    if "." in stem:
        return stem.upper()
    if len(stem) == 6 and stem.isdigit():
        suffix = "SH" if stem.startswith(("5", "6", "9")) else "SZ"
        return f"{stem}.{suffix}"
    return stem


def _normalize_trade_date(df: pd.DataFrame) -> pd.DataFrame:
    for column in ("trade_date", "timeString", "date"):
        if column in df.columns:
            if column != "trade_date":
                df = df.rename(columns={column: "trade_date"})
            raw = df["trade_date"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
            compact = raw.str.fullmatch(r"\d{8}", na=False)
            parsed = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
            parsed.loc[compact] = pd.to_datetime(raw.loc[compact], format="%Y%m%d", errors="coerce")
            parsed.loc[~compact] = pd.to_datetime(raw.loc[~compact], errors="coerce")
            df["trade_date"] = parsed
            return df
    return df


# ══════════════════════════════════════════════════════════════════════
# 覆盖率统计
# ══════════════════════════════════════════════════════════════════════


def coverage() -> dict[str, Any]:
    """统计覆盖率 (有多少只股票/多少天/多少行的数据)

    扫描 data/normalized/market/ 下所有 .csv 文件，统计:
      - 覆盖股票数
      - 日期范围 (最早/最晚交易日)
      - 交易日数量 (合并去重)
      - 总数据行数

    Returns:
        dict: 覆盖率统计报告
    """
    _ensure_dirs()

    daily_files, all_daily_files, reference = _active_daily_scope()
    active_codes = _active_reference_codes(reference)
    total_files = len(active_codes) if active_codes else len(daily_files)
    pulled_codes = {_code_from_path(path) for path in daily_files}
    total_rows = 0
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    all_dates: set[str] = set()
    stocks_with_data: list[dict[str, Any]] = []
    empty_files: list[str] = []

    for f in daily_files:
        ts_code = _code_from_path(f)
        try:
            # 只读前几行获取基本信息，不读全文件
            df = _normalize_trade_date(pd.read_csv(f, encoding="utf-8-sig", nrows=5))
            if df.empty:
                empty_files.append(ts_code)
                continue

            # 读全文件统计行数
            df_full = _normalize_trade_date(pd.read_csv(f, encoding="utf-8-sig"))
            row_count = len(df_full)
            total_rows += row_count

            if "trade_date" in df_full.columns:
                min_d = df_full["trade_date"].min()
                max_d = df_full["trade_date"].max()

                if pd.notna(min_d):
                    d_str = min_d.strftime("%Y-%m-%d")
                    if earliest_date is None or d_str < earliest_date:
                        earliest_date = d_str
                if pd.notna(max_d):
                    d_str = max_d.strftime("%Y-%m-%d")
                    if latest_date is None or d_str > latest_date:
                        latest_date = d_str

                # 收集所有交易日
                dates_set = set(
                    df_full["trade_date"].dropna().dt.strftime("%Y-%m-%d")
                )
                all_dates.update(dates_set)

            # 统计该股票的覆盖天数
            first_date = (
                min_d.strftime("%Y-%m-%d")
                if pd.notna(min_d) else ""
            )
            last_date = (
                max_d.strftime("%Y-%m-%d")
                if pd.notna(max_d) else ""
            )

            stocks_with_data.append({
                "ts_code": ts_code,
                "rows": row_count,
                "first_date": first_date,
                "last_date": last_date,
            })

        except Exception as e:
            logger.warning(f"读取 {f.name} 元数据失败: {e}")
            empty_files.append(ts_code)

    # 排序：按行数降序
    stocks_with_data.sort(key=lambda x: x["rows"], reverse=True)

    # 选取前 5 只和后 5 只作为示例
    top_5 = stocks_with_data[:5] if stocks_with_data else []
    bottom_5 = stocks_with_data[-5:] if len(stocks_with_data) >= 5 else stocks_with_data

    report = {
        "report_type": "coverage",
        "generated_at": _now_str(),
        "data_dir": _data_roots(daily_files)[0] if len(_data_roots(daily_files)) == 1 else "multiple",
        "data_roots": _data_roots(daily_files),
        "universe_status": "OK" if active_codes else "UNKNOWN",
        "universe_source": "data/normalized/reference/stock_basic.csv" if active_codes else None,
        "total_stocks": total_files,
        "stocks_with_data": len(stocks_with_data),
        "active_missing_files": len(active_codes - pulled_codes) if active_codes else None,
        "historical_files_outside_active": len(all_daily_files) - len(daily_files),
        "empty_files": len(empty_files),
        "empty_file_list": empty_files[:20],  # 最多列出 20 个
        "total_rows": total_rows,
        "earliest_date": earliest_date or "",
        "latest_date": latest_date or "",
        "unique_trading_days": len(all_dates),
        "top5_by_rows": top_5,
        "bottom5_by_rows": bottom_5,
        "summary": {
            "coverage_pct": round(
                len(stocks_with_data) / total_files * 100, 2
            ) if total_files > 0 else 0,
            "empty_pct": round(
                len(empty_files) / total_files * 100, 2
            ) if total_files > 0 else 0,
        },
    }

    # 写入 JSON
    report_path = HEALTH_DIR / "coverage.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"📊 覆盖率报告已保存: {report_path}")

    return report


# ══════════════════════════════════════════════════════════════════════
# 数据新鲜度
# ══════════════════════════════════════════════════════════════════════


def freshness() -> dict[str, Any]:
    """检查数据新鲜度 (最新日期 vs 今天)

    扫描 data/normalized/market/ 下所有日线 CSV，
    统计每只股票的最新交易日、距离今天的天数、过时程度。

    Returns:
        dict: 新鲜度报告
    """
    _ensure_dirs()

    daily_files, all_daily_files, reference = _active_daily_scope()
    active_codes = _active_reference_codes(reference)
    today = _latest_open_day()
    today_ymd = today.strftime("%Y%m%d")
    suspended_codes = _current_suspended_codes(today)

    stock_freshness: list[dict[str, Any]] = []
    total_lag_days = 0
    count_with_data = 0
    max_lag = 0
    max_lag_code = ""
    min_lag = 999999
    min_lag_code = ""
    future_date_stocks: list[dict[str, Any]] = []
    suspended_stocks: list[dict[str, Any]] = []
    lag_observations = 0

    for f in daily_files:
        ts_code = _code_from_path(f)
        try:
            df = _normalize_trade_date(pd.read_csv(f, encoding="utf-8-sig"))
            if df.empty or "trade_date" not in df.columns:
                continue

            latest_date = df["trade_date"].max()
            if pd.isna(latest_date):
                continue

            count_with_data += 1
            lag_days = (today - latest_date).days

            if lag_days < 0:
                future_date_stocks.append({
                    "ts_code": ts_code,
                    "latest_date": latest_date.strftime("%Y-%m-%d"),
                    "days_in_future": abs(lag_days),
                })

            is_suspended = ts_code in suspended_codes
            if not is_suspended:
                total_lag_days += lag_days
                lag_observations += 1
            if lag_days > max_lag:
                max_lag = lag_days
                max_lag_code = ts_code
            if lag_days < min_lag:
                min_lag = lag_days
                min_lag_code = ts_code

            # 新鲜度分级
            if is_suspended:
                freshness_level = "suspended"
                suspended_stocks.append(
                    {
                        "ts_code": ts_code,
                        "latest_date": latest_date.strftime("%Y-%m-%d"),
                        "suspended_through": today.strftime("%Y-%m-%d"),
                    }
                )
            elif lag_days <= 7:
                freshness_level = "fresh"
            elif lag_days <= 30:
                freshness_level = "stale"
            elif lag_days <= 90:
                freshness_level = "old"
            else:
                freshness_level = "ancient"

            stock_freshness.append({
                "ts_code": ts_code,
                "latest_date": latest_date.strftime("%Y-%m-%d"),
                "lag_days": lag_days,
                "freshness_level": freshness_level,
            })

        except Exception as e:
            logger.warning(f"读取 {f.name} 新鲜度失败: {e}")

    # 按滞后天数排序
    stock_freshness.sort(key=lambda x: x["lag_days"])

    # 统计各级别数量
    fresh_count = sum(1 for s in stock_freshness if s["freshness_level"] == "fresh")
    stale_count = sum(1 for s in stock_freshness if s["freshness_level"] == "stale")
    old_count = sum(1 for s in stock_freshness if s["freshness_level"] == "old")
    ancient_count = sum(1 for s in stock_freshness if s["freshness_level"] == "ancient")
    suspended_count = sum(1 for s in stock_freshness if s["freshness_level"] == "suspended")

    avg_lag = round(total_lag_days / lag_observations, 1) if lag_observations > 0 else 0
    active_missing = len(active_codes - {_code_from_path(path) for path in daily_files}) if active_codes else 0
    blocking_stocks = [
        row for row in stock_freshness if row["freshness_level"] in {"stale", "old", "ancient"}
    ]

    report = {
        "report_type": "freshness",
        "generated_at": _now_str(),
        "today": today_ymd,
        "as_of_open_date": today.strftime("%Y-%m-%d"),
        "data_dir": _data_roots(daily_files)[0] if len(_data_roots(daily_files)) == 1 else "multiple",
        "data_roots": _data_roots(daily_files),
        "universe_status": "OK" if active_codes else "UNKNOWN",
        "total_stocks": len(active_codes) if active_codes else len(daily_files),
        "stocks_with_data": count_with_data,
        "active_missing_files": active_missing if active_codes else None,
        "historical_files_excluded": len(all_daily_files) - len(daily_files),
        "status": "OK" if active_codes and not active_missing and not blocking_stocks and not future_date_stocks else "PARTIAL",
        "blocking_stock_count": active_missing + len(blocking_stocks) + len(future_date_stocks),
        "average_lag_days": avg_lag,
        "max_lag_days": max_lag,
        "max_lag_code": max_lag_code,
        "min_lag_days": min_lag if min_lag != 999999 else 0,
        "min_lag_code": min_lag_code,
        "future_date_count": len(future_date_stocks),
        "future_date_stocks": future_date_stocks[:20],
        "freshness_distribution": {
            "fresh (<=7d)": fresh_count,
            "stale (8-30d)": stale_count,
            "old (31-90d)": old_count,
            "ancient (>90d)": ancient_count,
            "suspended (canonical)": suspended_count,
        },
        "suspended_stocks": suspended_stocks[:100],
        "stale_stocks": [s for s in stock_freshness if s["freshness_level"] == "stale"][:20],
        "old_stocks": [s for s in stock_freshness if s["freshness_level"] == "old"][:20],
        "ancient_stocks": [s for s in stock_freshness if s["freshness_level"] == "ancient"][:20],
    }

    report_path = HEALTH_DIR / "freshness.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"📊 新鲜度报告已保存: {report_path}")

    return report


# ══════════════════════════════════════════════════════════════════════
# 缺失率报告
# ══════════════════════════════════════════════════════════════════════


def missing() -> dict[str, Any]:
    """缺失率报告 (与原 U0 全A池对比)

    对比 data/normalized/market/ 中已拉取的股票与 U0 全A基础池，
    统计缺失的股票、缺失的交易日期等。

    Returns:
        dict: 缺失率报告
    """
    _ensure_dirs()

    # 1) 从 canonical DataHub reference 获取当前活跃全 A 池。
    # 审计是 read-only consumer，禁止在这里调用 universes/provider 拉取。
    reference = _reference_stocks()
    u0_codes = _active_reference_codes(reference)
    u0_total = len(u0_codes)

    # 2) 扫描已拉取的日线
    daily_files = _daily_files()
    file_by_code = {_code_from_path(f): f for f in daily_files}
    pulled_codes = set(file_by_code)

    # 3) 缺失统计
    if u0_codes:
        missing_codes = sorted(u0_codes - pulled_codes)
        extra_codes = sorted(pulled_codes - u0_codes)  # 已退市等不在 U0 但存在的
        missing_count = len(missing_codes)
        pulled_count = len(pulled_codes & u0_codes)
    else:
        missing_codes = []
        extra_codes = list(pulled_codes)
        missing_count = 0
        pulled_count = len(pulled_codes)

    # 4) 计算每个股票的缺失率 — 用预计交易日 vs 实际行数
    missing_detail: list[dict[str, Any]] = []
    if u0_codes and pulled_codes:
        # 取一个样本日期范围 — 从已有数据中推断
        sample_files = list(daily_files)[:100]  # 取前 100 个文件采样
        expected_days = 0
        for f in sample_files:
            try:
                df = _normalize_trade_date(pd.read_csv(f, encoding="utf-8-sig"))
                if not df.empty and "trade_date" in df.columns:
                    expected_days = max(expected_days, len(df))
            except Exception:
                pass

        # 为每个已拉取股票计算缺失率
        for ts_code in sorted(pulled_codes):
            f = file_by_code.get(ts_code)
            if f is None:
                continue
            try:
                df = pd.read_csv(f, encoding="utf-8-sig")
                actual = len(df)
                ratio = round(
                    (expected_days - actual) / expected_days * 100, 2
                ) if expected_days > 0 else 0
                missing_detail.append({
                    "ts_code": ts_code,
                    "expected_days": expected_days,
                    "actual_days": actual,
                    "missing_pct": max(0, ratio),
                })
            except Exception:
                pass

        missing_detail.sort(key=lambda x: x["missing_pct"], reverse=True)

    report = {
        "report_type": "missing",
        "generated_at": _now_str(),
        "data_dir": _data_roots(daily_files)[0] if len(_data_roots(daily_files)) == 1 else "multiple",
        "data_roots": _data_roots(daily_files),
        "universe_source": "data/normalized/reference/stock_basic.csv" if u0_codes else None,
        "reference_total_all_statuses": len(reference),
        "u0_total": u0_total,
        "u0_codes_in_universe": len(u0_codes),
        "universe_status": "OK" if u0_codes else "UNKNOWN",
        "universe_missing_reason": None if u0_codes else "U0 unavailable or empty; missing coverage cannot be asserted",
        "pulled_stocks": pulled_count,
        "missing_stocks": missing_count,
        "extra_stocks_outside_u0": len(extra_codes),
        "missing_codes_sample": missing_codes[:30],  # 最多列出 30 个
        "extra_codes_sample": extra_codes[:30],
        "missing_detail_top20": missing_detail[:20],
        "summary": {
            "coverage_pct": round(
                pulled_count / u0_total * 100, 2
            ) if u0_total > 0 else 0,
            "missing_pct": round(
                missing_count / u0_total * 100, 2
            ) if u0_total > 0 else 0,
        },
    }

    report_path = HEALTH_DIR / "missing.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"📊 缺失率报告已保存: {report_path}")

    return report


# ══════════════════════════════════════════════════════════════════════
# 生存偏差检查
# ══════════════════════════════════════════════════════════════════════


def survivorship_check() -> dict[str, Any]:
    """生存偏差检查 (退市/ST/停牌股票分析)

    检查 data/normalized/market/ 中已拉取的股票，
    结合 U0 池中的上市状态标记，分析退市/ST/暂停上市股票的数据情况。

    Returns:
        dict: 生存偏差分析报告
    """
    _ensure_dirs()

    daily_files = _daily_files()
    pulled_codes = {_code_from_path(f) for f in daily_files}

    # 1) 读取 canonical reference 中全部 L/P/D 状态，保留退市历史口径。
    reference = _reference_stocks()
    reference_map = {str(row["ts_code"]): row for row in reference}

    # 2) 分析已拉取股票的状态
    delisted: list[dict[str, Any]] = []
    st_stocks: list[dict[str, Any]] = []
    suspended: list[dict[str, Any]] = []
    normal: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []

    for ts_code in sorted(pulled_codes):
        info = reference_map.get(ts_code)
        if info is None:
            unknown.append({"ts_code": ts_code, "reason": "outside_canonical_reference"})
            continue
        list_status = str(info.get("list_status") or "").upper()
        is_listed = list_status == "L"
        name = str(info.get("name") or "")
        board = str(info.get("market") or "")

        # 判断 ST
        is_st = False
        if name:
            name_upper = str(name).upper()
            if name_upper.startswith("ST") or name_upper.startswith("*ST"):
                is_st = True

        # 判断退市
        delist_date = info.get("delist_date", "")
        is_delisted = list_status == "D"
        is_suspended = list_status == "P"

        record = {
            "ts_code": ts_code,
            "name": name,
            "board": board,
            "is_listed": is_listed,
            "is_st": is_st,
            "list_status": list_status,
            "delist_date": str(delist_date) if delist_date else "",
        }

        if is_delisted:
            delisted.append(record)
        elif is_suspended:
            suspended.append(record)
        elif is_st:
            st_stocks.append(record)
        else:
            normal.append(record)

    # 3) 统计
    total_pulled = len(pulled_codes)

    report = {
        "report_type": "survivorship",
        "generated_at": _now_str(),
        "data_dir": _data_roots(daily_files)[0] if len(_data_roots(daily_files)) == 1 else "multiple",
        "data_roots": _data_roots(daily_files),
        "universe_status": "OK" if reference else "UNKNOWN",
        "universe_source": "data/normalized/reference/stock_basic.csv" if reference else None,
        "total_pulled": total_pulled,
        "normal_stocks": len(normal),
        "delisted_stocks": len(delisted),
        "st_stocks": len(st_stocks),
        "suspended_stocks": len(suspended),
        "unknown_stocks": len(unknown),
        "unknown_list": unknown[:30],
        "survivorship_bias_risk": round(
            (len(delisted) + len(st_stocks)) / total_pulled * 100, 2
        ) if total_pulled > 0 else 0,
        "delisted_list": delisted[:30],
        "st_list": st_stocks[:30],
        "note": (
            "生存偏差风险: 若仅分析当前上市股票而忽略已退市/ST股票，"
            "回测结果会被高估。建议保留所有历史数据。"
        ),
    }

    report_path = HEALTH_DIR / "survivorship.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"📊 生存偏差报告已保存: {report_path}")

    return report


# ══════════════════════════════════════════════════════════════════════
# 全量审计
# ══════════════════════════════════════════════════════════════════════


def run_all_audits() -> dict[str, str]:
    """运行所有审计检查并返回报告路径

    Returns:
        dict: {report_name: file_path}
    """
    print("=" * 60)
    print("  📋 V4.2 全量数据审计")
    print("=" * 60)
    print()

    results: dict[str, str] = {}

    print("[1/5] 覆盖率统计...")
    c = coverage()
    results["coverage"] = str(HEALTH_DIR / "coverage.json")
    print(f"      股票数: {c['stocks_with_data']}/{c['total_stocks']}, "
          f"日期范围: {c['earliest_date']} ~ {c['latest_date']}")
    print()

    print("[2/5] 数据新鲜度...")
    f = freshness()
    results["freshness"] = str(HEALTH_DIR / "freshness.json")
    print(f"      平均滞后: {f['average_lag_days']} 天, "
          f"新鲜: {f['freshness_distribution']['fresh (<=7d)']} 只")
    print()

    print("[3/5] 缺失率报告...")
    m = missing()
    results["missing"] = str(HEALTH_DIR / "missing.json")
    print(f"      已拉取: {m['pulled_stocks']}/{m['u0_total']}, "
          f"缺失: {m['missing_stocks']}")
    print()

    print("[4/5] 生存偏差检查...")
    s = survivorship_check()
    results["survivorship"] = str(HEALTH_DIR / "survivorship.json")
    print(f"      退市: {s['delisted_stocks']}, "
          f"ST: {s['st_stocks']}, "
          f"生存偏差风险: {s['survivorship_bias_risk']}%")
    print()

    print("[5/5] 行级完整性检查...")
    from factor_lab.datahub_integrity import audit_daily_integrity

    integrity_report = audit_daily_integrity(output_path=HEALTH_DIR / "integrity.json")
    results["integrity"] = str(HEALTH_DIR / "integrity.json")
    print(
        f"      状态: {integrity_report['status']}, "
        f"问题文件: {integrity_report['problematic_file_count']}, "
        f"缺失活跃文件: {len(integrity_report['missing_active_files'])}"
    )
    print()

    print("=" * 60)
    print(f"  {'✅' if integrity_report['status'] == 'OK' else '❌'} 全部审计完成")
    print(f"  报告目录: {HEALTH_DIR}")
    for name, path in results.items():
        print(f"    {name}: {path}")
    print("=" * 60)

    return results


# ══════════════════════════════════════════════════════════════════════
# CLI Handler Functions
# ══════════════════════════════════════════════════════════════════════


def cmd_coverage(args: list[str]) -> None:
    """处理 data:coverage 命令"""
    coverage()


def cmd_survivorship(args: list[str]) -> None:
    """处理 data:survivorship 命令"""
    survivorship_check()
