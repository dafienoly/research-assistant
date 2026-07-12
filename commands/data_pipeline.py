#!/usr/bin/env python3
"""
V4.2 全A日线批量拉取 — 批量拉取脚本

提供 batch_daily / batch_fina / batch_valuation 三个批量拉取入口，
基于 TushareMarketProvider / TushareFinaProvider 实现。

用法:
    from commands.data_pipeline import batch_daily, batch_fina, batch_valuation

    batch_daily(ts_codes=["688012.SH", "000001.SZ"], start="20190101", end="20260708")
    batch_fina(ts_codes=["688012.SH"], start="20190101", end="20260708")
    batch_valuation(ts_codes=["688012.SH"], start="20190101", end="20260708")

CLI:
    python3 hermes_cli.py data:pull-daily --start 20190101 --end 20260708
    python3 hermes_cli.py data:pull-fina --start 20190101 --end 20260708
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

try:
    from commands.data_providers.tushare import (
        TushareFinaProvider,
        TushareFundFlowProvider,
        TushareMarketProvider,
    )
    from commands.data_recovery import RecoveryManifest, atomic_write_frame, frame_date_range, merge_without_data_loss
except ModuleNotFoundError:
    from data_providers.tushare import (
        TushareFinaProvider,
        TushareFundFlowProvider,
        TushareMarketProvider,
    )
    from data_recovery import RecoveryManifest, atomic_write_frame, frame_date_range, merge_without_data_loss

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ─── 目录 ────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # research-assistant/
NORMALIZED_DIR = BASE / "data" / "normalized"
DAILY_DIR = NORMALIZED_DIR / "market"
FINA_DIR = NORMALIZED_DIR / "fundamentals"
VALUATION_DIR = NORMALIZED_DIR / "market"    # daily_basic 落在 market/valuation_{ts_code}.csv
FUND_FLOW_DIR = NORMALIZED_DIR / "fund_flow" # 个股资金流向
NORTH_FLOW_DIR = BASE / "data"               # 北向资金文件直接放 data/
ETC_DIR = NORMALIZED_DIR                     # concept, industry 等
INTRADAY_SNAPSHOT = BASE / "data" / "market" / "live_snapshot.csv"
RECOVERY_AUDIT_DIR = BASE / "data" / "audit" / "recovery"
INCREMENTAL_STATE_PATH = RECOVERY_AUDIT_DIR / "incremental_state.json"

# ─── 分批配置 ────────────────────────────────────────────────────────
BATCH_SIZE = 10           # 每批最多同时拉取的股票数（逐股模式）
BATCH_SLEEP = 1.5         # 批间休眠秒数（叠加在 TushareClient 内置限流之上）
FUNDAMENTAL_EMPTY_STREAK_LIMIT = 8  # 连续空结果时熔断，避免无效 API 风暴

# ─── Provider 单例 ───────────────────────────────────────────────────
_market_provider: Optional[TushareMarketProvider] = None
_fina_provider: Optional[TushareFinaProvider] = None
_fund_flow_provider: Optional[TushareFundFlowProvider] = None


def _get_market_provider() -> TushareMarketProvider:
    global _market_provider
    if _market_provider is None:
        _market_provider = TushareMarketProvider()
    return _market_provider


def _get_fina_provider() -> TushareFinaProvider:
    global _fina_provider
    if _fina_provider is None:
        _fina_provider = TushareFinaProvider()
    return _fina_provider


def _ensure_dirs():
    """确保归一化数据目录存在"""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    FINA_DIR.mkdir(parents=True, exist_ok=True)
    VALUATION_DIR.mkdir(parents=True, exist_ok=True)
    FUND_FLOW_DIR.mkdir(parents=True, exist_ok=True)


def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _get_ts_client():
    """获取 TushareClient 单例"""
    from factor_lab.data.tushare_client import get_ts_client
    return get_ts_client()


def _get_fund_flow_provider():
    """延迟初始化 TushareFundFlowProvider"""
    global _fund_flow_provider
    if _fund_flow_provider is None:
        from data_providers.tushare.tushare_fund_flow import TushareFundFlowProvider
        _fund_flow_provider = TushareFundFlowProvider()
    return _fund_flow_provider


# ─── CSV 增量追加辅助 ──────────────────────────────────────────────


def _read_csv_safe(path: Path) -> pd.DataFrame:
    """安全读取 CSV，文件不存在返回空 DataFrame"""
    if path.exists():
        try:
            return pd.read_csv(path, dtype_backend="numpy_nullable", on_bad_lines="warn")
        except Exception:
            return pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="warn")
    return pd.DataFrame()


def _append_to_csv(
    filepath: Path,
    new_rows: pd.DataFrame,
    dedup_cols: list[str],
    sort_cols: list[str] | None = None,
) -> int:
    """追加新行到 CSV，按 dedup_cols 去重，返回新增行数

    ⚠️ 写入后立即 fsync 确保落盘（避免 WSL page cache 丢失数据）
    """
    existing = _read_csv_safe(filepath)
    if existing.empty:
        combined = new_rows.copy()
    else:
        # 统一重复列的数据类型（避免 string vs int 等冲突）
        for col in dedup_cols:
            if col in existing.columns and col in new_rows.columns:
                new_rows[col] = new_rows[col].astype(str)
                existing[col] = existing[col].astype(str)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    available_dedup = [col for col in dedup_cols if col in combined.columns]
    if available_dedup:
        combined = combined.drop_duplicates(subset=available_dedup, keep="last")
    if sort_cols:
        ok_cols = [c for c in sort_cols if c in combined.columns]
        if ok_cols:
            # 排序列统一转 str 后排序
            for c in ok_cols:
                combined[c] = combined[c].astype(str)
            combined = combined.sort_values(ok_cols).reset_index(drop=True)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            prefix=f".{filepath.name}.",
            suffix=".tmp",
            dir=filepath.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            combined.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, filepath)
        temp_path = None
        _fsync_directory(filepath.parent)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    added = len(combined) - len(existing)
    return max(added, 0)


def _fsync_file(path: Path) -> None:
    """强制文件数据 + 父目录落盘（防止目录项丢失）"""
    import os as _os
    try:
        fd = _os.open(str(path), _os.O_WRONLY)
        try:
            _os.fsync(fd)
        finally:
            _os.close(fd)
        # 同步父目录（确保目录项持久化）
        dfd = _os.open(str(path.parent), _os.O_RDONLY)
        try:
            _os.fsync(dfd)
        finally:
            _os.close(dfd)
    except Exception:
        pass  # fsync 失败不应阻断流程


def _fsync_directory(path: Path) -> None:
    """持久化目录项；不支持目录 fsync 的文件系统上安全降级。"""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        logger.warning("directory fsync unavailable: %s", path, exc_info=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写 checkpoint，防止进程中断留下半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
        _fsync_directory(path.parent)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _read_incremental_state() -> dict[str, Any]:
    """Read the last fully persisted trading date for append-only updates."""
    try:
        payload = json.loads(INCREMENTAL_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"version": 1, "datasets": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("datasets"), dict):
        return {"version": 1, "datasets": {}}
    return payload


def _incremental_fast_path(dataset: str, trade_date: str) -> bool:
    """Use append-only writes only after a prior complete day is recorded."""
    last_date = _read_incremental_state().get("datasets", {}).get(dataset, {}).get("last_trade_date")
    return isinstance(last_date, str) and last_date < trade_date


def _record_incremental_state(dataset: str, trade_date: str, *, rows: int, files: int) -> None:
    state = _read_incremental_state()
    state.setdefault("version", 1)
    state.setdefault("datasets", {})[dataset] = {
        "last_trade_date": trade_date,
        "rows_added": int(rows),
        "files_touched": int(files),
        "recorded_at": datetime.now(CST).isoformat(),
    }
    _atomic_write_json(INCREMENTAL_STATE_PATH, state)


def _append_rows_without_rewrite(path: Path, frame: pd.DataFrame) -> int:
    """Append a new date partition without reading/re-writing history.

    The caller must have proven that this is a strictly newer trading date via
    ``INCREMENTAL_STATE_PATH``. Missing outputs are rejected instead of being
    recreated, so an accidental deletion cannot silently discard history.
    """
    if not path.is_file():
        raise FileNotFoundError(f"existing canonical output missing: {path}")
    if frame.empty:
        return 0
    try:
        columns = list(pd.read_csv(path, encoding="utf-8-sig", nrows=0).columns)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"existing canonical output unreadable: {path}") from exc
    if columns != list(frame.columns):
        raise ValueError(f"canonical output schema changed: {path}")
    with path.open("a", encoding="utf-8", newline="") as handle:
        with path.open("rb") as existing:
            existing.seek(0, os.SEEK_END)
            if existing.tell():
                existing.seek(-1, os.SEEK_END)
            if existing.tell() and existing.read(1) != b"\n":
                handle.write("\n")
        frame.to_csv(handle, index=False, header=False)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)
    return len(frame)


# ══════════════════════════════════════════════════════════════════════
# 按交易日全量更新 — 每次 API 调用获取全A当天数据，拆分写逐股 CSV
# ══════════════════════════════════════════════════════════════════════


def incremental_daily(trade_date: str = "") -> dict:
    """按交易日一次性拉取全A日线，拆分写入逐股 CSV

    Args:
        trade_date: YYYYMMDD，默认当天

    Returns:
        dict: {status, trade_date, stocks_count, rows_added, errors}

    Tushare daily(trade_date=) 返回当天所有股票数据（一次 API 调用）
    """
    tc = _get_ts_client()
    if not trade_date:
        trade_date = datetime.now(CST).strftime("%Y%m%d")

    print(f"  📅 日线增量: {trade_date}")
    df = tc._query("daily", fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount", trade_date=trade_date)
    if df.empty:
        print(f"     ⚠️  {trade_date} 无日线数据")
        return {"status": "empty", "trade_date": trade_date, "stocks": 0}

    _ensure_dirs()
    total_added = 0
    stocks = 0
    errors: list[str] = []
    fast_path = _incremental_fast_path("daily", trade_date)

    for ts_code, group in df.groupby("ts_code"):
        try:
            group = group.reset_index(drop=True)
            out = DAILY_DIR / f"{ts_code}.csv"
            added = (
                _append_rows_without_rewrite(out, group)
                if fast_path
                else _append_to_csv(out, group, dedup_cols=["trade_date"], sort_cols=["trade_date"])
            )
            if added > 0:
                total_added += added
                stocks += 1
        except Exception as e:
            errors.append(f"{ts_code}: {e}")

    status = "partial" if errors else "ok"
    if status == "ok":
        _record_incremental_state("daily", trade_date, rows=total_added, files=stocks)
    print(f"     ✅ {stocks} 只股票, 新增 {total_added} 行{ ' ⚠️ ' + str(len(errors)) + ' 错误' if errors else ''}")
    return {
        "status": status,
        "trade_date": trade_date,
        "stocks": stocks,
        "rows_added": total_added,
        "errors": errors,
        "write_mode": "append_only" if fast_path else "merge_once",
    }


def incremental_valuation(trade_date: str = "") -> dict:
    """按交易日全量拉取估值数据 (daily_basic)，拆分写入逐股 CSV

    Args:
        trade_date: YYYYMMDD，默认当天
    """
    tc = _get_ts_client()
    if not trade_date:
        trade_date = datetime.now(CST).strftime("%Y%m%d")

    print(f"  📅 估值增量: {trade_date}")
    fields = "ts_code,trade_date,pe,pe_ttm,pb,total_mv,circ_mv,turnover_rate,volume_ratio"
    df = tc._query("daily_basic", fields=fields, trade_date=trade_date)
    if df.empty:
        print(f"     ⚠️  {trade_date} 无估值数据")
        return {"status": "empty", "trade_date": trade_date, "stocks": 0}

    _ensure_dirs()
    total_added = 0
    stocks = 0
    errors: list[str] = []
    fast_path = _incremental_fast_path("valuation", trade_date)

    for ts_code, group in df.groupby("ts_code"):
        try:
            group = group.reset_index(drop=True)
            out = VALUATION_DIR / f"valuation_{ts_code}.csv"
            added = (
                _append_rows_without_rewrite(out, group)
                if fast_path
                else _append_to_csv(out, group, dedup_cols=["trade_date"], sort_cols=["trade_date"])
            )
            if added > 0:
                total_added += added
                stocks += 1
        except Exception as e:
            errors.append(f"{ts_code}: {e}")

    status = "partial" if errors else "ok"
    if status == "ok":
        _record_incremental_state("valuation", trade_date, rows=total_added, files=stocks)
    print(f"     ✅ {stocks} 只股票, 新增 {total_added} 行{ ' ⚠️' if errors else ''}")
    return {
        "status": status,
        "trade_date": trade_date,
        "stocks": stocks,
        "rows_added": total_added,
        "errors": errors,
        "write_mode": "append_only" if fast_path else "merge_once",
    }


def incremental_fund_flow(trade_date: str = "") -> dict:
    """按交易日全量拉取个股资金流向，拆分写入逐股 CSV

    一次 moneyflow(trade_date=) 调用获取全A当天资金流向。
    """
    tc = _get_ts_client()
    if not trade_date:
        trade_date = datetime.now(CST).strftime("%Y%m%d")

    print(f"  📅 资金流向增量: {trade_date}")
    df = tc._query("moneyflow", trade_date=trade_date)
    if df.empty:
        print(f"     ⚠️  {trade_date} 无资金流向数据")
        return {"status": "empty", "trade_date": trade_date, "stocks": 0}

    _ensure_dirs()
    total_added = 0
    stocks = 0
    errors: list[str] = []
    fast_path = _incremental_fast_path("fund_flow", trade_date)

    for ts_code, group in df.groupby("ts_code"):
        try:
            group = group.reset_index(drop=True)
            out = FUND_FLOW_DIR / f"{ts_code}.csv"
            added = (
                _append_rows_without_rewrite(out, group)
                if fast_path
                else _append_to_csv(out, group, dedup_cols=["trade_date"], sort_cols=["trade_date"])
            )
            if added > 0:
                total_added += added
                stocks += 1
        except Exception as e:
            errors.append(f"{ts_code}: {e}")

    status = "partial" if errors else "ok"
    if status == "ok":
        _record_incremental_state("fund_flow", trade_date, rows=total_added, files=stocks)
    print(f"     ✅ {stocks} 只股票, 新增 {total_added} 行{ ' ⚠️' if errors else ''}")
    return {
        "status": status,
        "trade_date": trade_date,
        "stocks": stocks,
        "rows_added": total_added,
        "errors": errors,
        "write_mode": "append_only" if fast_path else "merge_once",
    }


def incremental_north_flow(trade_date: str = "") -> dict:
    """更新北向资金时序文件（moneyflow_hsgt + hsgt_top10）

    北向数据写入 data/north_flow_timeseries.csv（追加去重）。
    """
    tc = _get_ts_client()
    if not trade_date:
        trade_date = datetime.now(CST).strftime("%Y%m%d")

    print(f"  📅 北向资金增量: {trade_date}")
    results: dict[str, int] = {}

    # moneyflow_hsgt — 沪深港通整体资金流向
    df = tc._query("moneyflow_hsgt", start_date=trade_date, end_date=trade_date)
    if not df.empty:
        out = NORTH_FLOW_DIR / "north_flow_timeseries.csv"
        added = _append_to_csv(out, df, dedup_cols=["trade_date"], sort_cols=["trade_date"])
        results["moneyflow_hsgt"] = added
        print(f"     ✅ moneyflow_hsgt 新增 {added} 行")
    else:
        print(f"     ⚠️  {trade_date} 无 moneyflow_hsgt 数据")

    # hsgt_top10 — 沪深港通十大成交股
    for market_type, label in [("1", "沪股通"), ("3", "深股通")]:
        df_top = tc._query("hsgt_top10", trade_date=trade_date, market_type=market_type)
        if not df_top.empty:
            out = NORTH_FLOW_DIR / f"hsgt_top10_{market_type}.csv"
            added = _append_to_csv(out, df_top, dedup_cols=["trade_date", "ts_code"], sort_cols=["trade_date"])
            results[label] = added
        else:
            print(f"     ⚠️  {trade_date} 无 {label} 十大成交")

    return {"status": "ok", "trade_date": trade_date, **results}


def _mx_data_query(question: str) -> dict:
    """调用 mx:data API"""
    import os
    import requests
    api_key = os.environ.get("MX_APIKEY")
    if not api_key:
        return {"error": "MX_APIKEY 未设置"}
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    try:
        resp = requests.post(url, headers={"apikey": api_key, "Content-Type": "application/json"},
                             json={"toolQuery": question}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def incremental_concept_industry() -> dict:
    """刷新概念板块和行业分类（每周一次）。

    旧实现调用了不存在的 ``concept``/``industry`` API 名称，导致每次
    cron 运行都进行三轮重试，随后才进入备用源。统一转发到 canonical
    ``pull_concept_industry_mx``，避免重复实现、错误重试和无来源覆盖。
    """
    result = pull_concept_industry_mx()
    concept = result.get("concept", {})
    industry = result.get("industry", {})
    return {
        "status": "ok" if result.get("status") == "OK" else "partial",
        "concept_list": concept.get("rows", 0),
        "industry": industry.get("rows", 0),
        "concept_source": concept.get("source"),
        "industry_source": industry.get("source"),
        "errors": result.get("errors", []),
        "canonical_result": result,
    }


def incremental_etf_holdings() -> dict:
    """刷新重点 ETF 持仓权重（每周一次）"""
    tc = _get_ts_client()
    print("  📅 ETF 持仓刷新")

    etf_codes = ["588710.SH", "512480.SH", "588290.SH", "561980.SH"]
    results: dict[str, int] = {}
    all_rows: list[pd.DataFrame] = []

    for etf in etf_codes:
        try:
            df = tc._query("fund_portfolio", ts_code=etf)
            if not df.empty:
                df["etf_code"] = etf
                all_rows.append(df)
                results[etf] = len(df)
                print(f"     ✅ {etf}: {len(df)} 条持仓")
        except Exception as e:
            print(f"     ⚠️  {etf}: {e}")
            results[etf] = 0

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        successful_etfs = sum(1 for etf in etf_codes if results.get(etf, 0) > 0)
        out = NORMALIZED_DIR / "etf_holdings" / "holdings.csv"
        content_hash = atomic_write_frame(combined, out)
        _atomic_write_json(
            out.with_suffix(".manifest.json"),
            {
                "status": "OK" if successful_etfs == len(etf_codes) else "PARTIAL",
                "dataset": "normalized/etf_holdings",
                "generated_at": datetime.now(CST).isoformat(),
                "rows": len(combined),
                "etf_count": successful_etfs,
                "path": out.name,
                "sha256": content_hash,
                "source": "tushare:fund_portfolio",
            },
        )
        results["total"] = len(combined)
        print(f"     ✅ ETF 持仓汇总: {len(combined)} 条 → {out.name}")

    results["status"] = (
        "OK"
        if all_rows and sum(1 for etf in etf_codes if results.get(etf, 0) > 0) == len(etf_codes)
        else ("PARTIAL" if all_rows else "MISSING")
    )
    return results


def incremental_fina_latest() -> dict:
    """增量更新财务指标（全A拉最新一个报告期，逐股写文件）

    财务数据更新频率低（季度发布），增量只拉最近半年。
    """
    tc = _get_ts_client()
    print("  📅 财务指标增量")

    today = datetime.now(CST)
    end_date = today.strftime("%Y%m%d")
    # 拉近6个月数据
    start = (today - timedelta(days=185)).strftime("%Y%m%d")

    # 全A股票列表
    stocks = tc._query("stock_basic", fields="ts_code", list_status="L")
    if stocks.empty:
        return {"status": "empty", "message": "无法获取股票列表"}
    ts_codes = stocks["ts_code"].tolist()

    total_added = 0
    stocks_ok = 0
    errors: list[str] = []
    empty_count = 0
    error_count = 0
    processed_count = 0
    upstream_unavailable = False
    _ensure_dirs()

    # 分批处理 (fina 只能逐股查询)
    batches = [ts_codes[i:i + BATCH_SIZE] for i in range(0, len(ts_codes), BATCH_SIZE)]
    for batch_idx, batch in enumerate(batches):
        for ts_code in batch:
            try:
                df = tc._query("fina_indicator", ts_code=ts_code, start_date=start, end_date=end_date)
                processed_count += 1
                if df.empty:
                    empty_count += 1
                    if empty_count >= FUNDAMENTAL_EMPTY_STREAK_LIMIT:
                        upstream_unavailable = True
                        print(
                            "     ⛔ 财务接口连续返回空结果，停止本轮逐股请求；"
                            "保留已有文件并记录为上游缺口"
                        )
                        break
                    continue
                empty_count = 0
                error_count = 0
                df = df.reset_index(drop=True)
                out = FINA_DIR / f"{ts_code}.csv"
                added = _append_to_csv(out, df, dedup_cols=["end_date"], sort_cols=["end_date"])
                if added > 0:
                    total_added += added
                    stocks_ok += 1
            except Exception as e:
                processed_count += 1
                errors.append(f"{ts_code}: {e}")
                error_count += 1
                if error_count >= FUNDAMENTAL_EMPTY_STREAK_LIMIT:
                    upstream_unavailable = True
                    print(
                        "     ⛔ 财务接口连续失败，停止本轮逐股请求；"
                        "保留已有文件并记录为上游缺口"
                    )
                    break
        if upstream_unavailable:
            break
        if batch_idx % 50 == 0 and batch_idx > 0:
            print(f"     ... {batch_idx * BATCH_SIZE}/{len(ts_codes)} ({stocks_ok} stocks ok)")

    err_info = f" ⚠️ {len(errors)} 错误" if errors else ""
    skipped_count = max(len(ts_codes) - processed_count, 0)
    status = "upstream_unavailable" if upstream_unavailable else "ok"
    if upstream_unavailable:
        print(
            f"     ⚠️ 财务增量提前结束: 已检查 {processed_count}/{len(ts_codes)}，"
            f"剩余 {skipped_count} 只保留为待补缺口"
        )
    else:
        print(f"     ✅ {stocks_ok} 只股票, 新增 {total_added} 行{err_info}")
    return {
        "status": status,
        "stocks": stocks_ok,
        "rows_added": total_added,
        "errors": errors[:10],
        "empty_results": empty_count,
        "processed": processed_count,
        "skipped_due_to_upstream": skipped_count,
    }


# ══════════════════════════════════════════════════════════════════════
# 组合入口
# ══════════════════════════════════════════════════════════════════════


def daily_incremental_update(trade_date: str = "") -> dict:
    """每日增量更新：日线+估值+资金流+北向

    在收盘后（约 15:05）调用，一次拉齐全A当天数据。
    """
    if not trade_date:
        trade_date = datetime.now(CST).strftime("%Y%m%d")

    print(f"{'='*50}")
    print(f"🚀 DataHub 每日增量更新 — {trade_date}")
    print(f"{'='*50}")
    print()

    results = {
        "daily": incremental_daily(trade_date),
        "valuation": incremental_valuation(trade_date),
        "fund_flow": incremental_fund_flow(trade_date),
        "north_flow": incremental_north_flow(trade_date),
    }

    print()
    print(f"{'='*50}")
    print("📋 汇总")
    print(f"{'='*50}")
    ok = all(r.get("status") == "ok" for r in results.values())
    for name, r in results.items():
        icon = "✅" if r.get("status") == "ok" else "⚠️"
        stocks = r.get("stocks", r.get("moneyflow_hsgt", "-"))
        rows = r.get("rows_added", "-")
        print(f"  {icon} {name:12s}  stocks={stocks}  rows_added={rows}")

    print(f"\n  总体: {'✅ 全部正常' if ok else '⚠️ 部分异常'}")

    # === 更新注册表状态 ===
    _update_registry_after_daily(results, trade_date)

    return results


def _update_registry_after_daily(results: dict, trade_date: str) -> None:
    """更新 data_source_registry.json 状态 (日增量管线完成后)"""
    try:
        from factor_lab.data_source_registry import update_source_status

        ok = results.get("daily", {}).get("status") == "ok"
        north_ok = results.get("north_flow", {}).get("status") == "ok"
        total_rows = sum(
            r.get("rows_added", 0) for r in results.values()
            if isinstance(r, dict) and isinstance(r.get("rows_added", 0), int)
        )

        status = "active" if ok else "pending"
        last_refresh = f"{datetime.now(CST).isoformat()}"
        extra = {
            "last_trade_date": trade_date,
            "pipeline": "daily_incremental",
        }

        # tushare_pro 主数据源
        result = update_source_status(
            "tushare_pro", status,
            last_refresh=last_refresh,
            record_count=total_rows,
            extra=extra,
        )
        if result.get("status") == "ok":
            print(f"  📋 注册表: tushare_pro → {status} ✅")
        else:
            print(f"  📋 注册表: {result.get('error', 'unknown')} ⚠️")

        # northbound_data 北向资金 (north_flow 子管线)
        nf_status = "active" if north_ok else "pending"
        nf_rows = results.get("north_flow", {}).get("rows_added", 0)
        if isinstance(nf_rows, str):
            nf_rows = 0
        update_source_status(
            "northbound_data", nf_status,
            last_refresh=last_refresh,
            record_count=int(nf_rows),
            extra={"pipeline": "daily_incremental", "sub_pipeline": "north_flow"},
        )
        print(f"  📋 注册表: northbound_data → {nf_status} ✅")
    except Exception as e:
        print(f"  ⚠️ 注册表状态更新失败: {e}")


def weekly_maintenance() -> dict:
    """每周维护：概念/行业/ETF持仓+财务增量"""
    print(f"{'='*50}")
    print("🔄 DataHub 每周维护")
    print(f"{'='*50}")
    print()

    results = {
        "concept_industry": incremental_concept_industry(),
        "etf_holdings": incremental_etf_holdings(),
        "fina_latest": incremental_fina_latest(),
    }

    print()
    print(f"{'='*50}")
    print("📋 周维护汇总")
    print(f"{'='*50}")
    all_ok = True
    for name, r in results.items():
        component_ok = str(r.get("status", "")).lower() in {"ok", "success"}
        icon = "✅" if component_ok else "⚠️"
        all_ok = all_ok and component_ok
        print(f"  {icon} {name:18s}  status={r.get('status')}")

    print(f"  总体: {'✅ 全部正常' if all_ok else '⚠️ 部分异常'}")
    results["status"] = "ok" if all_ok else "partial"

    # === 更新注册表状态 ===
    _update_registry_after_weekly(results)

    return results


def _update_registry_after_weekly(results: dict) -> None:
    """更新 data_source_registry.json 状态 (周维护管线完成后)"""
    try:
        from factor_lab.data_source_registry import update_source_status

        ok = results.get("status") == "ok"
        status = "active" if ok else "pending"
        last_refresh = f"{datetime.now(CST).isoformat()}"
        extra = {"pipeline": "weekly_maintenance"}
        result = update_source_status(
            "tushare_pro", status,
            last_refresh=last_refresh,
            extra=extra,
        )
        if result.get("status") == "ok":
            print(f"  📋 注册表: tushare_pro → {status} ✅")
        else:
            print(f"  📋 注册表: {result.get('error', 'unknown')} ⚠️")
    except Exception as e:
        print(f"  ⚠️ 注册表状态更新失败: {e}")


def run_data_audit() -> dict:
    """读取 DataHub 已生成的健康清单，不重复扫描 CSV 数据目录。

    数据审计由受控 DataHub ingestion 任务负责生成 coverage/freshness/
    missing/integrity；cron 只读取这些 durable manifests，避免每次状态查询
    再次遍历数千个分区文件或调用旧的第二套 ``data_audit`` 实现。
    """
    print(f"{'='*50}")
    print("🔍 DataHub 新鲜度检查")
    print(f"{'='*50}")

    try:
        health_root = BASE / "data" / "audit" / "health"

        def read_health(name: str) -> dict[str, Any]:
            path = health_root / name
            if not path.is_file():
                return {"status": "MISSING", "path": str(path), "error": "manifest_missing"}
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                return {"status": "INVALID", "path": str(path), "error": type(exc).__name__}
            return payload if isinstance(payload, dict) else {"status": "INVALID", "path": str(path)}

        canonical_freshness = read_health("freshness.json")
        canonical_integrity = read_health("integrity.json")
        missing = read_health("missing.json")
        projection_path = BASE / "data" / "audit" / "manifests" / "factor_input_projection.json"
        try:
            projection = json.loads(projection_path.read_text(encoding="utf-8")) if projection_path.is_file() else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            projection = {}

        auxiliary_statuses = {
            name: str((item or {}).get("status", "MISSING")).upper()
            for name, item in (projection.get("datasets") or {}).items()
        }
        fresh = {
            "check_time": canonical_freshness.get("generated_at", ""),
            "overall_status": "ok" if auxiliary_statuses and all(status in {"OK", "COMPLETE"} for status in auxiliary_statuses.values()) else "partial",
            "source": "datahub:audit/health/freshness.json+factor_input_projection.json",
            "datasets": auxiliary_statuses,
            "blocking": False,
        }
        gaps = {
            "report_time": missing.get("generated_at", ""),
            "source": "datahub:audit/health/missing.json+factor_input_projection.json",
            "gaps": [],
            "summary": {"total_gaps": 0, "blocking_gaps": 0, "partial_gaps": 0, "blocking_codex": False},
        }
        missing_count = int(missing.get("missing_stocks", 0) or 0)
        if missing_count:
            gaps["gaps"].append({
                "name": "canonical_market",
                "description": f"{missing_count} 个 U0 标的缺少 canonical 行情",
                "category": "market",
                "gap_type": "missing_canonical_data",
                "impact": "blocking",
                "blocking_codex": True,
                "affected_stocks": missing.get("missing_codes_sample", []),
            })
        for name, status in auxiliary_statuses.items():
            if status not in {"OK", "COMPLETE"}:
                gaps["gaps"].append({
                    "name": name,
                    "description": f"DataHub projection status={status}",
                    "category": "auxiliary",
                    "gap_type": "manifest_status",
                    "impact": "partial",
                    "blocking_codex": False,
                    "status": status,
                })
        if not auxiliary_statuses:
            gaps["gaps"].append({
                "name": "factor_input_projection",
                "description": "DataHub factor input projection manifest missing or invalid",
                "category": "auxiliary",
                "gap_type": "manifest_missing",
                "impact": "partial",
                "blocking_codex": False,
                "status": "MISSING",
            })
        gaps["summary"] = {
            "total_gaps": len(gaps["gaps"]),
            "blocking_gaps": sum(1 for item in gaps["gaps"] if item.get("blocking_codex")),
            "partial_gaps": sum(1 for item in gaps["gaps"] if not item.get("blocking_codex")),
            "blocking_codex": any(item.get("blocking_codex") for item in gaps["gaps"]),
        }
        health_reports = {
            name.removesuffix(".json"): str(health_root / name)
            for name in ("coverage.json", "freshness.json", "missing.json", "integrity.json", "survivorship.json")
        }
        core_status = canonical_freshness.get("status", "UNKNOWN")
        integrity_status = canonical_integrity.get("status", "UNKNOWN")
        overall_status = (
            "ok"
            if core_status == "OK"
            and integrity_status == "OK"
            and fresh["overall_status"] == "ok"
            and gaps["summary"].get("partial_gaps", 0) == 0
            and not gaps["summary"].get("blocking_codex", False)
            else "partial"
        )
        print(f"\n  核心新鲜度: {core_status}")
        print(f"  行级完整性: {integrity_status}")
        print(f"  辅助快照:   {fresh.get('overall_status', 'unknown')}")
        print(f"  缺口:   {gaps['summary']['total_gaps']} 总, {gaps['summary']['blocking_gaps']} 阻塞")

        return {
            "status": overall_status,
            "canonical_freshness": canonical_freshness,
            "canonical_integrity": canonical_integrity,
            "auxiliary_freshness": fresh,
            "gaps": gaps,
            "health_reports": health_reports,
        }
    except Exception as e:
        print(f"  ❌ 审计失败: {e}")
        return {"status": "error", "error": str(e)}


def full_init_pipeline() -> dict:
    """首次全量填充 normalized/ 目录（日线+财务+估值）

    注意：全A 5,529 只，分批限流，预计运行约 1-2 小时。
    """
    print(f"{'='*50}")
    print("🔥 DataHub 首次全量初始化")
    print(f"{'='*50}")
    print("  预计运行 1-2 小时，请耐心等待")
    print()

    tc = _get_ts_client()

    # 从股票池获取全A代码
    try:
        from universes import get_universe
        u = get_universe("U0")
        stocks = u.get("stocks", [])
        ts_codes = [s["ts_code"] for s in stocks if s.get("ts_code")]
    except Exception:
        print("⚠️ 无法从 U0 获取股票列表，直接从 stock_basic 拉取")
        sb = tc._query("stock_basic", fields="ts_code", list_status="L")
        ts_codes = sb["ts_code"].tolist() if not sb.empty else []

    print(f"📋 全A共 {len(ts_codes)} 只股票")

    results = {}

    # 日线全量
    print(f"\n{'='*30}\n📊 日线全量\n{'='*30}")
    results["daily"] = batch_daily(ts_codes, start="20210101")

    # 估值全量
    print(f"\n{'='*30}\n📈 估值全量\n{'='*30}")
    results["valuation"] = batch_valuation(ts_codes, start="20210101")

    # 财务全量（5年）
    print(f"\n{'='*30}\n📑 财务全量\n{'='*30}")
    results["fina"] = batch_fina(ts_codes, start="20200101")

    print(f"\n{'='*50}")
    print("📋 全量初始化汇总")
    print(f"{'='*50}")
    ok = 0
    for name, r in results.items():
        ok_count = sum(1 for v in r.values() if isinstance(v, int) and v > 0)
        print(f"  ✅ {name:10s}  {ok_count} 只成功")
        ok += ok_count
    print(f"\n  完成: {ok} 只股票")

    results["status"] = "ok"
    return results


# ══════════════════════════════════════════════════════════════════════
# 按交易日遍历全量初始化（推荐方案）
# ══════════════════════════════════════════════════════════════════════


def _get_trade_days(start_date: str = "20210101") -> list[str]:
    """获取交易日列表，返回 YYYYMMDD 字符串列表"""
    tc = _get_ts_client()
    end = datetime.now(CST).strftime("%Y%m%d")
    cal = tc._query("trade_cal", start_date=start_date, end_date=end)
    if cal.empty or "cal_date" not in cal.columns:
        return []
    calendar_path = NORMALIZED_DIR / "calendar" / "trade_calendar.csv"
    _append_to_csv(calendar_path, cal.copy(), ["cal_date"], ["cal_date"])
    cal["cal_date"] = pd.to_datetime(cal["cal_date"], format="%Y%m%d", errors="coerce")
    days = cal[cal["is_open"] == 1]["cal_date"].dropna().sort_values()
    return [d.strftime("%Y%m%d") for d in days]


# ─── 批量配置（交易日遍历）───
BATCH_TRADE_DAYS = 50  # 每批处理的交易日数（50天/批控制每批内存~25MB）


def full_init_by_trade_date() -> dict:
    """按交易日遍历全量初始化 — 推荐方案（批处理优化版）

    效率核心：daily(trade_date=YYYYMMDD) 一次 API 调用返回全A当天数据。
    将 N 个交易日的数据集中后一次写入，避免每交易日 5,500 次文件 I/O。

    日线+估值+资金流各 ~1,400 次 API 调用 → 写入 ~28 批（每批 50 天）。
    """
    print(f"{'='*50}")
    print("🔥 DataHub 按交易日全量初始化（批处理优化版）")
    print(f"{'='*50}")
    print()
    tc = _get_ts_client()

    # 获取交易日历
    print("📅 获取交易日历...")
    days = _get_trade_days("20210101")
    if not days:
        print("❌ 无法获取交易日历")
        return {"status": "error"}
    print(f"   {len(days)} 个交易日 (2021-01-01 ~ {days[-1]})")
    print(f"   批大小: {BATCH_TRADE_DAYS} 天, 共 { (len(days) + BATCH_TRADE_DAYS - 1) // BATCH_TRADE_DAYS} 批")
    print()

    results: dict[str, dict] = {}
    errors: list[str] = []
    _ensure_dirs()

    staging_root = RECOVERY_AUDIT_DIR / "full_init_staging"
    checkpoint_path = staging_root / "checkpoint.json"
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        checkpoint = {"version": 1, "datasets": {}}

    def _process_dataset(
        name: str,
        api_name: str,
        fields: str,
        out_dir: Path,
        file_prefix: str = "",
    ) -> tuple[int, int]:
        """先持久化所有 API 批次，再对每个 symbol 仅归并一次。"""
        dataset_dir = staging_root / name
        dataset_dir.mkdir(parents=True, exist_ok=True)
        state = checkpoint.setdefault("datasets", {}).setdefault(
            name, {"completed_batches": [], "merged": False}
        )
        completed = set(state.get("completed_batches", []))
        batch_paths: list[Path] = []

        for offset in range(0, len(days), BATCH_TRADE_DAYS):
            batch_days = days[offset:offset + BATCH_TRADE_DAYS]
            batch_id = f"{batch_days[0]}-{batch_days[-1]}"
            batch_path = dataset_dir / f"{batch_id}.csv"
            batch_paths.append(batch_path)
            valid_staged = False
            if batch_id in completed and batch_path.exists():
                try:
                    staged = pd.read_csv(batch_path, encoding="utf-8-sig")
                    valid_staged = {"ts_code", "trade_date"}.issubset(staged.columns)
                except Exception:
                    valid_staged = False
            if valid_staged:
                continue

            all_parts: list[pd.DataFrame] = []
            for day in batch_days:
                kwargs = {"trade_date": day}
                if fields:
                    kwargs["fields"] = fields
                try:
                    frame = tc._query(api_name, **kwargs)
                except Exception as exc:
                    state["merged"] = False
                    _atomic_write_json(checkpoint_path, checkpoint)
                    raise RuntimeError(f"{api_name} {day}: {exc}") from exc
                if frame is not None and not frame.empty:
                    all_parts.append(frame)
            staged = pd.concat(all_parts, ignore_index=True) if all_parts else pd.DataFrame(
                columns=["ts_code", "trade_date"]
            )
            # staging 可随时重建；损坏批次必须整体替换，不能与坏内容拼接。
            batch_path.unlink(missing_ok=True)
            _append_to_csv(batch_path, staged, ["ts_code", "trade_date"], ["ts_code", "trade_date"])
            completed.add(batch_id)
            state["completed_batches"] = sorted(completed)
            state["merged"] = False
            _atomic_write_json(checkpoint_path, checkpoint)

        # API 阶段完成不等于正式成功；只有所有 staging 完整且逐股归并结束才标记 merged。
        state["merged"] = False
        _atomic_write_json(checkpoint_path, checkpoint)
        staged_frames = [pd.read_csv(path, encoding="utf-8-sig") for path in batch_paths]
        combined = pd.concat(staged_frames, ignore_index=True) if staged_frames else pd.DataFrame()
        rows_added = 0
        if not combined.empty:
            for ts_code, group in combined.groupby("ts_code"):
                fname = f"{file_prefix}{ts_code}.csv"
                rows_added += _append_to_csv(
                    out_dir / fname,
                    group.reset_index(drop=True),
                    dedup_cols=["trade_date"],
                    sort_cols=["trade_date"],
                )
        state["merged"] = True
        state["merged_at"] = datetime.now(CST).isoformat()
        _atomic_write_json(checkpoint_path, checkpoint)
        files = len(list(out_dir.glob(f"{file_prefix}*.csv")))
        return rows_added, files

    # ─── 日线 ──────────────────────────────────────────────
    print(f"{'='*40}")
    print("📊 日线 — 按交易日遍历（批处理）")
    print(f"{'='*40}")
    daily_start = time.time()
    try:
        daily_rows, daily_files = _process_dataset(
            "daily", "daily",
            "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            DAILY_DIR,
        )
    except RuntimeError as exc:
        return {"status": "error", "errors": [str(exc)], "checkpoint": str(checkpoint_path)}
    results["daily"] = {"status": "ok", "files": daily_files, "rows": daily_rows}
    elapsed_daily = time.time() - daily_start
    print(f"   ✅ 日线完成: {daily_files} 只 / {daily_rows} 行 / {elapsed_daily:.0f}s")

    # ─── 估值 ──────────────────────────────────────────────
    print()
    print(f"{'='*40}")
    print("📈 估值 — 按交易日遍历（批处理）")
    print(f"{'='*40}")
    val_start = time.time()
    try:
        val_rows, val_files = _process_dataset(
            "valuation", "daily_basic",
            "ts_code,trade_date,pe,pe_ttm,pb,total_mv,circ_mv,turnover_rate,volume_ratio",
            VALUATION_DIR, file_prefix="valuation_",
        )
    except RuntimeError as exc:
        return {"status": "error", "errors": [str(exc)], "checkpoint": str(checkpoint_path)}
    results["valuation"] = {"status": "ok", "files": val_files, "rows": val_rows}
    elapsed_val = time.time() - val_start
    print(f"   ✅ 估值完成: {val_files} 只 / {val_rows} 行 / {elapsed_val:.0f}s")

    # ─── 资金流向 ──────────────────────────────────────────
    print()
    print(f"{'='*40}")
    print("💰 资金流向 — 按交易日遍历（批处理）")
    print(f"{'='*40}")
    ff_start = time.time()
    try:
        ff_rows, ff_files = _process_dataset(
            "fund_flow", "moneyflow", "", FUND_FLOW_DIR
        )
    except RuntimeError as exc:
        return {"status": "error", "errors": [str(exc)], "checkpoint": str(checkpoint_path)}
    results["fund_flow"] = {"status": "ok", "files": ff_files, "rows": ff_rows}
    elapsed_ff = time.time() - ff_start
    print(f"   ✅ 资金流完成: {ff_files} 只 / {ff_rows} 行 / {elapsed_ff:.0f}s")

    # ─── 汇总 ──────────────────────────────────────────────
    print()
    print(f"{'='*50}")
    print("📋 全量初始化汇总")
    print(f"{'='*50}")
    for name, r in results.items():
        print(f"  ✅ {name:12s}  {r['files']:>5d} 只  {r['rows']:>8d} 行")
    total_time = elapsed_daily + elapsed_val + elapsed_ff
    print(f"\n  总耗时: {total_time:.0f}s ({total_time/60:.0f}min)")
    print(f"  总错误: {len(errors)}")
    if errors:
        print(f"  首批错误: {errors[:5]}")

    disk = sum(f.stat().st_size for f in DAILY_DIR.glob("*.csv")) + \
           sum(f.stat().st_size for f in VALUATION_DIR.glob("*.csv")) + \
           sum(f.stat().st_size for f in FUND_FLOW_DIR.glob("*.csv"))
    print(f"  磁盘占用: {disk / 1024 / 1024:.0f} MB")

    results["status"] = "ok"
    results["errors"] = errors
    return results


def backfill_timeseries() -> dict:
    """回填北向资金和两融时序数据，对齐日线范围（2021-01-01 至今）

    moneyflow_hsgt / margin 都支持按 trade_date 单日查询。
    用批处理方式遍历交易日，减少文件 I/O。
    """
    print(f"{'='*50}")
    print("⏪ 时序数据回填 — 北向资金 + 两融")
    print(f"{'='*50}")
    print()

    tc = _get_ts_client()
    days = _get_trade_days("20210101")
    if not days:
        print("❌ 无法获取交易日历")
        return {"status": "error"}

    print(f"📅 {len(days)} 个交易日 (2021-01-01 ~ {days[-1]})")
    print(f"   批大小: {BATCH_TRADE_DAYS} 天\n")

    errors: list[str] = []
    results: dict = {}
    _ensure_dirs()

    def _process_ts_batch(
        batch_days: list[str],
        api_name: str,
        out_path: Path,
        dedup_cols: list[str],
        fields: str = "",
    ) -> int:
        """处理一批交易日的时序数据：集中查询 → 合并 → 去重写入"""
        all_rows: list[pd.DataFrame] = []
        for day in batch_days:
            try:
                kwargs = {"trade_date": day}
                if fields:
                    kwargs["fields"] = fields
                df = tc._query(api_name, **kwargs)
                if df is not None and not df.empty:
                    all_rows.append(df)
            except Exception as e:
                errors.append(f"{api_name} {day}: {e}")
        if not all_rows:
            return 0
        combined = pd.concat(all_rows, ignore_index=True)
        existing = _read_csv_safe(out_path)
        if existing.empty:
            final = combined
        else:
            final = pd.concat([existing, combined], ignore_index=True)
            final = final.drop_duplicates(subset=dedup_cols, keep="last")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        final.to_csv(out_path, index=False, encoding="utf-8-sig")
        added = len(final) - len(existing)
        return max(added, 0)

    # ─── 北向资金 ──────────────────────────────────────
    print("💰 北向资金 (moneyflow_hsgt) ...")
    north_out = NORTH_FLOW_DIR / "north_flow_timeseries.csv"
    north_rows = 0
    for b in range(0, len(days), BATCH_TRADE_DAYS):
        batch = days[b:b + BATCH_TRADE_DAYS]
        r = _process_ts_batch(batch, "moneyflow_hsgt", north_out, ["trade_date"],
                              fields="trade_date,ggt_ss,ggt_sz,hgt,sgt,north_money,south_money")
        north_rows += r
    print(f"   ✅ 北向资金: {north_rows} 行新增 (共{_read_csv_safe(north_out).__len__() - 1}行)")
    results["north_flow"] = north_rows

    # ─── 两融 ──────────────────────────────────────────
    print("📊 两融 (margin) ...")
    margin_out = NORTH_FLOW_DIR / "margin_timeseries.csv"
    margin_rows = 0
    for b in range(0, len(days), BATCH_TRADE_DAYS):
        batch = days[b:b + BATCH_TRADE_DAYS]
        r = _process_ts_batch(batch, "margin", margin_out,
                              ["trade_date", "exchange_id"],
                              fields="trade_date,exchange_id,rzye,rzmre,rzche,rqye,rqmcl,rzrqye,rqyl")
        margin_rows += r
    print(f"   ✅ 两融: {margin_rows} 行新增 (共{_read_csv_safe(margin_out).__len__() - 1}行)")
    results["margin"] = margin_rows

    print(f"\n{'='*50}")
    print("📋 回填汇总")
    print(f"{'='*50}")
    for name, rows in results.items():
        print(f"  {'✅' if rows > 0 else '⚠️'} {name}: +{rows} 行")
    results["status"] = "ok"
    results["errors"] = errors
    return results


def pull_remaining_market_data() -> dict:
    """P0: 补齐复权因子 + 涨跌停 + 停复牌

    按交易日遍历 adj_factor / stk_limit（效率同 daily_basic），
    suspend_d 季度级拉取（稀疏数据）。
    """
    print(f"{'='*50}")
    print("📡 P0: 复权因子 + 涨跌停 + 停复牌")
    print(f"{'='*50}")
    print()

    tc = _get_ts_client()
    days = _get_trade_days("20210101")
    if not days:
        print("❌ 无法获取交易日历")
        return {"status": "error"}
    print(f"📅 {len(days)} 个交易日 (2021-01-01 ~ {days[-1]})")
    print(f"   批大小: {BATCH_TRADE_DAYS} 天\n")

    LIMITS_DIR = BASE / "data" / "normalized" / "limits"
    SUSPEND_DIR = BASE / "data" / "normalized" / "suspend"
    LIMITS_DIR.mkdir(parents=True, exist_ok=True)
    SUSPEND_DIR.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    results: dict = {}
    num_batches = (len(days) + BATCH_TRADE_DAYS - 1) // BATCH_TRADE_DAYS

    def _batch_pull(batch_days, api_name, out_dir, file_prefix="", fields=""):
        total_rows = 0
        for day in batch_days:
            try:
                kwargs = {"trade_date": day}
                if fields:
                    kwargs["fields"] = fields
                df = tc._query(api_name, **kwargs)
                if df is None or df.empty:
                    continue
                for ts_code, group in df.groupby("ts_code"):
                    group = group.reset_index(drop=True)
                    fname = f"{file_prefix}{ts_code}.csv" if file_prefix else f"{ts_code}.csv"
                    out = out_dir / fname
                    _append_to_csv(out, group, dedup_cols=["trade_date"], sort_cols=["trade_date"])
                    total_rows += len(group)
            except Exception as e:
                errors.append(f"{api_name} {day}: {e}")
        return total_rows

    # ─── 复权因子 ──────────────────────────────────────
    print("📊 复权因子 (adj_factor) ...")
    adj_total = 0
    for b in range(0, len(days), BATCH_TRADE_DAYS):
        batch = days[b:b + BATCH_TRADE_DAYS]
        r = _batch_pull(batch, "adj_factor", LIMITS_DIR, "adj_",
                        fields="ts_code,trade_date,adj_factor")
        adj_total += r
        print(f"    复权: 批 {b//BATCH_TRADE_DAYS+1}/{num_batches} +{r}行")
    adj_files = len(list(LIMITS_DIR.glob("adj_*.csv")))
    results["adj_factor"] = {"files": adj_files, "rows": adj_total}
    print(f"   ✅ 复权因子: {adj_files} 只 / {adj_total} 行")

    # ─── 涨跌停 ────────────────────────────────────────
    print("\n📊 涨跌停 (stk_limit) ...")
    stk_total = 0
    for b in range(0, len(days), BATCH_TRADE_DAYS):
        batch = days[b:b + BATCH_TRADE_DAYS]
        r = _batch_pull(batch, "stk_limit", LIMITS_DIR, "stk_limit_",
                        fields="trade_date,ts_code,up_limit,down_limit")
        stk_total += r
        print(f"    涨跌停: 批 {b//BATCH_TRADE_DAYS+1}/{num_batches} +{r}行")
    stk_files = len(list(LIMITS_DIR.glob("stk_limit_*.csv")))
    results["stk_limit"] = {"files": stk_files, "rows": stk_total}
    print(f"   ✅ 涨跌停: {stk_files} 只 / {stk_total} 行")

    # ─── 停复牌（季度级）───
    print("\n📊 停复牌 (suspend_d) ...")
    sus_total = 0
    for year in range(2021, 2027):
        for quarter in [1, 2, 3, 4]:
            start_q = f"{year}{quarter*3-2:02d}01"
            end_q = f"{year}{quarter*3:02d}30" if quarter < 4 else f"{year}1231"
            if start_q > days[-1]:
                break
            try:
                df = tc._query("suspend_d", start_date=start_q, end_date=end_q)
                if df is not None and not df.empty:
                    out = SUSPEND_DIR / f"suspend_{year}Q{quarter}.csv"
                    existing = _read_csv_safe(out)
                    if existing.empty:
                        final = df
                    else:
                        final = pd.concat([existing, df], ignore_index=True)
                        final = final.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
                    final.to_csv(out, index=False, encoding="utf-8-sig")
                    added = len(final) - len(existing)
                    sus_total += max(added, 0)
            except Exception as e:
                errors.append(f"suspend_d {year}Q{quarter}: {e}")
    results["suspend_d"] = {"rows": sus_total}
    print(f"   ✅ 停复牌: {sus_total} 条记录 (按季度)")

    # ─── 汇总 ──────────────────────────────────────────
    print(f"\n{'='*50}")
    print("📋 P0 拉取汇总")
    print(f"{'='*50}")
    for name, r in results.items():
        files = r.get("files", "-")
        rows = r.get("rows", r.get("files", "-"))
        print(f"  ✅ {name:12s}  files={files}  rows={rows}")
    results["status"] = "ok"
    results["errors"] = errors
    return results


def pull_concept_industry_mx() -> dict:
    """Pull complete concept/industry catalogs with explicit source provenance.

    Tushare ``ths_index`` and SW2021 ``index_classify`` are the primary
    sources.  mx-data is queried only when a primary dataset is empty, and
    any such observation is persisted as ``PARTIAL`` with its source named;
    it is never silently promoted to a successful Tushare result.
    """
    print(f"{'='*50}")
    print("📡 P1: 概念板块+行业分类 (Tushare primary, mx-data explicit alternative)")
    print(f"{'='*50}")

    errors: list[str] = []
    tc = _get_ts_client()

    def _query_primary(api_name: str, **kwargs: str) -> pd.DataFrame:
        try:
            frame = tc._query(api_name, **kwargs)
            return frame if frame is not None else pd.DataFrame()
        except Exception as exc:
            errors.append(f"{api_name}: {type(exc).__name__}: {exc}")
            return pd.DataFrame()

    def _query_mx_alternative(queries: list[str], name_column: str) -> pd.DataFrame:
        best = pd.DataFrame()
        for query in queries:
            response = _mx_data_query(query)
            if "error" in response:
                errors.append(f"mx_data: {response['error']}")
                continue
            try:
                tables = (
                    response.get("data", {})
                    .get("data", {})
                    .get("searchDataResultDTO", {})
                    .get("dataTableDTOList", [])
                )
                rows: list[dict[str, Any]] = []
                for table in tables:
                    raw = table.get("table") or table.get("rawTable") or {}
                    name_map = table.get("nameMap") or {}
                    headings = raw.get("headName", [])
                    if headings and len(headings) > 2:
                        candidate = pd.DataFrame({name_column: headings})
                        if len(candidate) > len(best):
                            best = candidate
                        continue
                    for key, values in raw.items():
                        if key in {"headName", "headNameSub"}:
                            continue
                        for index, value in enumerate(values):
                            while len(rows) <= index:
                                rows.append({})
                            rows[index][name_map.get(key, key)] = value
                    for index, heading in enumerate(headings):
                        if index < len(rows):
                            rows[index][name_column] = heading
                candidate = pd.DataFrame(rows)
                if len(candidate) > len(best):
                    best = candidate
            except (AttributeError, TypeError, ValueError) as exc:
                errors.append(f"mx_data_parse: {type(exc).__name__}: {exc}")
        return best

    concept = _query_primary("ths_index", exchange="A", type="N")
    concept_source = "tushare:ths_index"
    concept_quality = "OK"
    if concept.empty:
        print("   ⚠️ Tushare ths_index 为空；查询 mx-data 备选观察")
        concept = _query_mx_alternative(
            [
                "A股全部概念板块列表 代码 名称",
                "东方财富概念板块列表 板块代码 板块名称",
                "概念板块 板块代码 板块名称 成分股数量",
            ],
            "板块名称",
        )
        concept_source = "mx_data:search"
        concept_quality = "PARTIAL" if not concept.empty else "MISSING"

    industry_parts = [
        _query_primary("index_classify", level=level, src="SW2021")
        for level in ("L1", "L2", "L3")
    ]
    populated_parts = [frame for frame in industry_parts if not frame.empty]
    industry = pd.concat(populated_parts, ignore_index=True) if populated_parts else pd.DataFrame()
    if not industry.empty and "index_code" in industry.columns:
        industry = industry.drop_duplicates(subset=["index_code"], keep="last")
    industry_source = "tushare:index_classify:SW2021"
    industry_quality = "OK"
    if industry.empty:
        print("   ⚠️ Tushare index_classify 为空；查询 mx-data 备选观察")
        industry = _query_mx_alternative(
            [
                "申万行业分类 行业代码 行业名称",
                "A股行业分类列表 行业代码 行业名称",
                "行业板块 板块代码 板块名称",
            ],
            "行业名称",
        )
        industry_source = "mx_data:search"
        industry_quality = "PARTIAL" if not industry.empty else "MISSING"

    results: dict[str, Any] = {"errors": errors}
    for label, frame, source, quality, relative_path in (
        ("concept", concept, concept_source, concept_quality, Path("concept/concept_list.csv")),
        ("industry", industry, industry_source, industry_quality, Path("industry/industry_list.csv")),
    ):
        if frame.empty:
            print(f"   ⚠️ {label}: 所有明确来源均未返回有效数据")
            results[label] = {"rows": 0, "source": source, "quality_status": "MISSING", "sha256": None}
            continue
        durable = frame.copy()
        durable["source_provider"] = source
        durable["quality_status"] = quality
        durable["observed_at"] = datetime.now(CST).isoformat()
        output_path = ETC_DIR / relative_path
        content_hash = atomic_write_frame(durable, output_path)
        print(f"   {'✅' if quality == 'OK' else '⚠️'} {label}_list: {len(durable)} 条 ({source}, {quality})")
        results[label] = {
            "rows": len(durable),
            "source": source,
            "quality_status": quality,
            "sha256": content_hash,
        }

    qualities = {results[name]["quality_status"] for name in ("concept", "industry")}
    results["status"] = "OK" if qualities == {"OK"} else "PARTIAL"
    results["silent_fallback_used"] = False
    return results


def gap_report_and_plan() -> dict:
    """Return the durable DataHub gap report; never query or scan inputs."""
    return run_data_audit().get("gaps", {})


def _recoverable_batch_pull(
    *,
    dataset: str,
    api_name: str,
    ts_codes: list[str],
    start: str,
    end: str,
    fetch: Callable[..., pd.DataFrame],
    output_path: Callable[[str], Path],
    label: str,
) -> dict[str, int]:
    """Execute a provider pull with durable per-symbol resume state."""
    total = len(ts_codes)
    results: dict[str, int] = {}
    total_rows = 0
    failed: list[str] = []
    missing: list[str] = []
    resumed: list[str] = []
    recovery = RecoveryManifest(
        RECOVERY_AUDIT_DIR,
        dataset=dataset,
        provider="tushare",
        api_name=api_name,
        start=start,
        end=end,
        symbols=ts_codes,
        batch_size=BATCH_SIZE,
        batch_sleep_seconds=BATCH_SLEEP,
    )

    print(f"🚀 批量{label}拉取: {total} 只股票, {start} ~ {end}")
    print(f"   checkpoint: {recovery.checkpoint_path}")
    print(f"   manifest:   {recovery.manifest_path}")
    print()

    batches = [ts_codes[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    for batch_idx, batch in enumerate(batches):
        print(f"  ── 批次 {batch_idx + 1}/{len(batches)} ({len(batch)} 只) ──")
        for ts_code in batch:
            out_path = output_path(ts_code)
            resume = recovery.resume_record(ts_code, out_path)
            if resume.reusable:
                results[ts_code] = resume.rows
                total_rows += resume.rows
                resumed.append(ts_code)
                print(f"     ↪️  {ts_code:12s}  {resume.rows:>5d} 行（hash 校验后恢复）")
                continue

            started_at = datetime.now(timezone.utc).isoformat()
            try:
                frame = fetch(ts_code=ts_code, start_date=start, end_date=end)
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(f"{api_name} returned {type(frame).__name__}, expected DataFrame")
                if frame.empty:
                    logger.warning("%s %s无数据", ts_code, label)
                    results[ts_code] = 0
                    missing.append(ts_code)
                    recovery.record_missing(ts_code, started_at=started_at)
                    continue

                min_date, max_date = frame_date_range(frame)
                durable_frame = (
                    frame.copy()
                    if resume.reason == "output_hash_changed"
                    else merge_without_data_loss(frame, out_path)
                )
                content_hash = atomic_write_frame(durable_frame, out_path)
                row_count = len(frame)
                recovery.record_success(
                    ts_code,
                    output_path=out_path,
                    rows=row_count,
                    persisted_rows=len(durable_frame),
                    min_date=min_date,
                    max_date=max_date,
                    content_hash=content_hash,
                    started_at=started_at,
                )
                results[ts_code] = row_count
                total_rows += row_count
                print(f"     ✅ {ts_code:12s}  {row_count:>5d} 行 → {out_path.name}")
            except Exception as error:
                logger.error("%s %s拉取失败: %s", ts_code, label, error)
                results[ts_code] = -1
                failed.append(ts_code)
                recovery.record_error(ts_code, error, started_at=started_at)
                print(f"     ❌ {ts_code:12s}  失败: {error}")

        if batch_idx < len(batches) - 1:
            print(f"     💤 休眠 {BATCH_SLEEP}s ...")
            time.sleep(BATCH_SLEEP)

    manifest_path = recovery.finish()
    print()
    print(f"📋 {label}批量拉取完成")
    print(f"   总股票: {total}")
    print(f"   成功:   {sum(1 for value in results.values() if value > 0)} ({total_rows} 行)")
    print(f"   恢复:   {len(resumed)}")
    print(f"   无数据: {len(missing)}")
    print(f"   失败:   {len(failed)}")
    print(f"   清单:   {manifest_path}")
    if failed:
        suffix = "..." if len(failed) > 10 else ""
        print(f"   失败列表: {', '.join(failed[:10])}{suffix}")
    return results


def batch_daily(
    ts_codes: list[str],
    start: str = "20190101",
    end: str = "",
) -> dict[str, int]:
    """批量拉取全A日线，写出到 data/normalized/market/{ts_code}.csv

    Args:
        ts_codes: 股票代码列表 (如 ['688012.SH', '000001.SZ'])
        start:    起始日期 YYYYMMDD
        end:      截止日期 YYYYMMDD (默认当天)

    Returns:
        dict: {ts_code: row_count, ...} 每只股票写入的行数
    """
    _ensure_dirs()
    provider = _get_market_provider()
    if not end:
        end = datetime.now(CST).strftime("%Y%m%d")
    return _recoverable_batch_pull(
        dataset="daily",
        api_name="daily",
        ts_codes=ts_codes,
        start=start,
        end=end,
        fetch=provider.daily,
        output_path=lambda symbol: DAILY_DIR / f"{symbol}.csv",
        label="日线",
    )


# ══════════════════════════════════════════════════════════════════════
# 批量拉取 — 财务指标
# ══════════════════════════════════════════════════════════════════════


def batch_fina(
    ts_codes: list[str],
    start: str = "20190101",
    end: str = "",
) -> dict[str, int]:
    """批量拉取财务指标数据，写出到 data/normalized/fundamentals/{ts_code}.csv

    Args:
        ts_codes: 股票代码列表
        start:    起始报告期 YYYYMMDD
        end:      截止报告期 YYYYMMDD (默认当天)

    Returns:
        dict: {ts_code: row_count, ...}
    """
    _ensure_dirs()
    provider = _get_fina_provider()
    if not end:
        end = datetime.now(CST).strftime("%Y%m%d")
    return _recoverable_batch_pull(
        dataset="fina_indicator",
        api_name="fina_indicator",
        ts_codes=ts_codes,
        start=start,
        end=end,
        fetch=provider.fina_indicator,
        output_path=lambda symbol: FINA_DIR / f"{symbol}.csv",
        label="财务指标",
    )


# ══════════════════════════════════════════════════════════════════════
# 批量拉取 — 估值数据 (daily_basic)
# ══════════════════════════════════════════════════════════════════════


def batch_valuation(
    ts_codes: list[str],
    start: str = "20190101",
    end: str = "",
) -> dict[str, int]:
    """批量拉取估值数据 (PE/PB/市值/换手率)，写出到 data/normalized/market/valuation_{ts_code}.csv

    Args:
        ts_codes: 股票代码列表
        start:    起始日期 YYYYMMDD
        end:      截止日期 YYYYMMDD (默认当天)

    Returns:
        dict: {ts_code: row_count, ...}
    """
    _ensure_dirs()
    provider = _get_market_provider()
    if not end:
        end = datetime.now(CST).strftime("%Y%m%d")
    return _recoverable_batch_pull(
        dataset="daily_basic",
        api_name="daily_basic",
        ts_codes=ts_codes,
        start=start,
        end=end,
        fetch=provider.daily_basic,
        output_path=lambda symbol: VALUATION_DIR / f"valuation_{symbol}.csv",
        label="估值数据",
    )


# ══════════════════════════════════════════════════════════════════════
# CLI Handler Functions
# ══════════════════════════════════════════════════════════════════════


def cmd_pull_daily(args: list[str]) -> None:
    """处理 data:pull-daily 命令"""
    start = "20190101"
    end = ""
    source_universe = "U0"

    for i, a in enumerate(args):
        if a == "--start" and i + 1 < len(args):
            start = args[i + 1]
        elif a == "--end" and i + 1 < len(args):
            end = args[i + 1]
        elif a == "--universe" and i + 1 < len(args):
            source_universe = args[i + 1]

    # 从股票池获取 ts_codes
    try:
        from universes import get_universe
        u = get_universe(source_universe)
        stocks = u.get("stocks", [])
        ts_codes = [s["ts_code"] for s in stocks if s.get("ts_code")]
    except Exception as e:
        print(f"❌ 无法从 {source_universe} 获取股票列表: {e}")
        print("   将使用 --codes 手动传入逗号分隔的 ts_codes")
        # 尝试从参数读取手动代码列表
        codes_str = ""
        for i, a in enumerate(args):
            if a == "--codes" and i + 1 < len(args):
                codes_str = args[i + 1]
        if codes_str:
            ts_codes = [c.strip() for c in codes_str.split(",") if c.strip()]
        else:
            print("❌ 未提供股票代码。使用 --codes ts_code1,ts_code2,...")
            return

    if not ts_codes:
        print(f"❌ 股票池 {source_universe} 为空")
        return

    print(f"📋 从 {source_universe} 加载 {len(ts_codes)} 只股票")
    batch_daily(ts_codes, start=start, end=end)


def cmd_pull_fina(args: list[str]) -> None:
    """处理 data:pull-fina 命令"""
    start = "20190101"
    end = ""
    source_universe = "U0"

    for i, a in enumerate(args):
        if a == "--start" and i + 1 < len(args):
            start = args[i + 1]
        elif a == "--end" and i + 1 < len(args):
            end = args[i + 1]
        elif a == "--universe" and i + 1 < len(args):
            source_universe = args[i + 1]

    try:
        from universes import get_universe
        u = get_universe(source_universe)
        stocks = u.get("stocks", [])
        ts_codes = [s["ts_code"] for s in stocks if s.get("ts_code")]
    except Exception as e:
        print(f"❌ 无法从 {source_universe} 获取股票列表: {e}")
        codes_str = ""
        for i, a in enumerate(args):
            if a == "--codes" and i + 1 < len(args):
                codes_str = args[i + 1]
        if codes_str:
            ts_codes = [c.strip() for c in codes_str.split(",") if c.strip()]
        else:
            print("❌ 未提供股票代码。使用 --codes ts_code1,ts_code2,...")
            return

    if not ts_codes:
        print(f"❌ 股票池 {source_universe} 为空")
        return

    print(f"📋 从 {source_universe} 加载 {len(ts_codes)} 只股票")
    batch_fina(ts_codes, start=start, end=end)


def cmd_pull_valuation(args: list[str]) -> None:
    """处理 data:pull-valuation 命令"""
    start = "20190101"
    end = ""
    source_universe = "U0"

    for i, a in enumerate(args):
        if a == "--start" and i + 1 < len(args):
            start = args[i + 1]
        elif a == "--end" and i + 1 < len(args):
            end = args[i + 1]
        elif a == "--universe" and i + 1 < len(args):
            source_universe = args[i + 1]

    try:
        from universes import get_universe
        u = get_universe(source_universe)
        stocks = u.get("stocks", [])
        ts_codes = [s["ts_code"] for s in stocks if s.get("ts_code")]
    except Exception as e:
        print(f"❌ 无法从 {source_universe} 获取股票列表: {e}")
        codes_str = ""
        for i, a in enumerate(args):
            if a == "--codes" and i + 1 < len(args):
                codes_str = args[i + 1]
        if codes_str:
            ts_codes = [c.strip() for c in codes_str.split(",") if c.strip()]
        else:
            print("❌ 未提供股票代码。使用 --codes ts_code1,ts_code2,...")
            return

    if not ts_codes:
        print(f"❌ 股票池 {source_universe} 为空")
        return

    print(f"📋 从 {source_universe} 加载 {len(ts_codes)} 只股票")
    batch_valuation(ts_codes, start=start, end=end)


def cmd_incremental_update(args: list[str]) -> None:
    """处理 data:incremental-update 命令"""
    trade_date = ""
    for i, a in enumerate(args):
        if a == "--date" and i + 1 < len(args):
            trade_date = args[i + 1]
    daily_incremental_update(trade_date)


def cmd_weekly_refresh(args: list[str]) -> None:
    """处理 data:weekly-refresh 命令"""
    weekly_maintenance()


def cmd_data_audit(args: list[str]) -> None:
    """处理 data:audit 命令"""
    result = run_data_audit()
    if result.get("status") == "error" or result.get("canonical_integrity", {}).get("status") != "OK":
        raise SystemExit(2)


def _print_health_manifest(name: str) -> None:
    """Print one existing DataHub health report without recomputing it."""
    path = BASE / "data" / "audit" / "health" / name
    if not path.is_file():
        print(json.dumps({"status": "MISSING", "path": str(path)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "path": str(path), "error": type(exc).__name__}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_data_coverage(args: list[str]) -> None:
    """处理 data:coverage：只读取 DataHub 已生成的 coverage manifest。"""
    del args
    _print_health_manifest("coverage.json")


def cmd_data_survivorship(args: list[str]) -> None:
    """处理 data:survivorship：只读取 DataHub 已生成的 survivorship manifest。"""
    del args
    _print_health_manifest("survivorship.json")


def cmd_full_init(args: list[str]) -> None:
    """处理 data:full-init 命令"""
    full_init_pipeline()


def cmd_registry_update_status(args: list[str]) -> None:
    """处理 data:registry-update-status 命令

    用法: data:registry-update-status --source source_id --status active [--last-refresh TS] [--rows N]
    """
    source_id = ""
    status = ""
    last_refresh = ""
    record_count = 0

    for i, a in enumerate(args):
        if a == "--source" and i + 1 < len(args):
            source_id = args[i + 1]
        elif a == "--status" and i + 1 < len(args):
            status = args[i + 1]
        elif a == "--last-refresh" and i + 1 < len(args):
            last_refresh = args[i + 1]
        elif a == "--rows" and i + 1 < len(args):
            try:
                record_count = int(args[i + 1])
            except ValueError:
                pass

    if not source_id or not status:
        print("用法: data:registry-update-status --source <id> --status <active|pending|degraded|inactive> [--last-refresh TS] [--rows N]")
        print("示例: data:registry-update-status --source mx_data --status active --rows 15000")
        return

    from factor_lab.data_source_registry import update_source_status

    result = update_source_status(
        source_id, status,
        last_refresh=last_refresh or datetime.now(CST).isoformat(),
        record_count=record_count,
        extra={"pipeline_update": True},
    )
    if result.get("status") == "ok":
        print(f"✅ 注册表更新: {source_id} → {status}")
    else:
        print(f"⚠️ 注册表更新失败: {result.get('error', 'unknown')}")


def cmd_full_init_by_date(args: list[str]) -> None:
    """处理 data:full-init-by-date 命令"""
    full_init_by_trade_date()


def cmd_gap_report(args: list[str]) -> None:
    """处理 data:gap-plan 命令"""
    del args
    result = run_data_audit()
    print(json.dumps(result.get("gaps", {}), ensure_ascii=False, indent=2))


def cmd_backfill_timeseries(args: list[str]) -> None:
    """处理 data:backfill-timeseries 命令"""
    backfill_timeseries()


def cmd_pull_remaining(args: list[str]) -> None:
    """处理 data:pull-remaining 命令"""
    pull_remaining_market_data()


def cmd_concept_industry(args: list[str]) -> None:
    """处理 data:pull-concept-industry 命令"""
    pull_concept_industry_mx()
