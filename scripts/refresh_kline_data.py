#!/usr/bin/env python3
"""
P1-1: K线数据恢复 + 数据刷新
═══════════════════════════════════════════════════════════
1. 备份旧数据 ✅ (已完成)
2. 找到 data/market/daily_kline/ 下的 K 线文件
3. 使用 Tushare 拉取 2026-04-03 之后至最近的日线
4. 统一 schema: code,timeString,open,high,low,close,volume,amount
5. ETF 文件补充 code 列
6. 停牌（零成交量价格不变）标记异常
7. 清理重复 _hist.csv，保留备份
8. 生成 data_refresh_report.md 和 manifest.json
"""

import csv
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands.factor_lab.data.tushare_client import get_ts_client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CST = timezone(timedelta(hours=8))

KLINE_DIR = Path("/home/ly/.hermes/research-assistant/data/market/daily_kline")
BACKUP_DIR = Path("/mnt/d/HermesReports/v5_1_remediation/backups")
REPORT_DIR = Path("/home/ly/.hermes/research-assistant/data")

# ─── 统一 schema ─────────────────────────────────────────────
UNIFIED_SCHEMA = ["code", "timeString", "open", "high", "low", "close", "volume", "amount"]


def now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def analyze_kline_files() -> list[dict]:
    """分析所有K线文件的状态"""
    files_info = []
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        symbol = f.name.replace("_daily_kline.csv", "")
        # 判断是否ETF (6位代码且非6开头=A股)
        is_etf = symbol.startswith(("5", "1")) and not symbol.startswith(("0", "3", "6", "8"))

        with open(f, "r", encoding="utf-8-sig") as fh:
            header = fh.readline().strip()

        columns = header.split(",")
        has_code = "code" in columns
        schema_ok = columns == UNIFIED_SCHEMA
        missing_code = not has_code

        # 读取最后一行
        with open(f, "r", encoding="utf-8-sig") as fh:
            lines = fh.readlines()
        last_line = lines[-1].strip() if lines else ""
        last_date = ""
        if last_line:
            parts = next(csv.reader([last_line]))
            if has_code:
                last_date = parts[1] if len(parts) > 1 else ""
            else:
                last_date = parts[0] if parts else ""

        # 对应的 _hist.csv 是否存在
        hist_file = KLINE_DIR / f"{symbol}_hist.csv"
        has_hist = hist_file.exists()

        files_info.append({
            "file": f.name,
            "symbol": symbol,
            "is_etf": is_etf,
            "columns": columns,
            "has_code_col": has_code,
            "schema_ok": schema_ok,
            "missing_code_col": missing_code,
            "row_count": len(lines),
            "last_date": last_date,
            "has_hist_file": has_hist,
            "size_bytes": f.stat().st_size,
        })
        logger.info(f"  {f.name}: rows={len(lines)}, schema_ok={schema_ok}, "
                    f"has_code={has_code}, last_date={last_date}")
    return files_info


def get_ts_code(symbol: str) -> str:
    """Symbol to ts_code"""
    if symbol.startswith(("6", "5")):
        return f"{symbol}.SH"
    elif symbol.startswith(("0", "3", "1")):
        return f"{symbol}.SZ"
    elif symbol.startswith("8"):
        return f"{symbol}.BJ"
    return f"{symbol}.SH"


def pull_daily_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """拉取股票日线数据 (Tushare daily API)"""
    tc = get_ts_client()
    ts_code = get_ts_code(symbol)
    df = tc.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        return df

    # 排序
    df = df.sort_values("trade_date").reset_index(drop=True)
    # 构建统一格式
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "code": symbol,
            "timeString": row["trade_date"].strftime("%Y-%m-%d") if hasattr(row["trade_date"], "strftime") else str(row["trade_date"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(float(row["vol"])) if "vol" in row and pd.notna(row["vol"]) else 0,
            "amount": float(row["amount"]) if "amount" in row and pd.notna(row["amount"]) else 0.0,
        })
    return pd.DataFrame(rows)


def pull_fund_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """拉取ETF/基金日线数据 (Tushare fund_daily API)"""
    tc = get_ts_client()
    ts_code = get_ts_code(symbol)
    # fund_daily 的字段: ts_code, trade_date, open, high, low, close, vol, amount
    df = tc._query("fund_daily", ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        return df

    df = df.sort_values("trade_date").reset_index(drop=True)
    rows = []
    for _, row in df.iterrows():
        trade_date = row["trade_date"]
        if hasattr(trade_date, "strftime"):
            date_str = trade_date.strftime("%Y-%m-%d")
        else:
            date_str = str(trade_date)
        rows.append({
            "code": symbol,
            "timeString": date_str,
            "open": float(row["open"]) if pd.notna(row.get("open")) else 0.0,
            "high": float(row["high"]) if pd.notna(row.get("high")) else 0.0,
            "low": float(row["low"]) if pd.notna(row.get("low")) else 0.0,
            "close": float(row["close"]) if pd.notna(row.get("close")) else 0.0,
            "volume": int(float(row["vol"])) if pd.notna(row.get("vol")) else 0,
            "amount": float(row["amount"]) if pd.notna(row.get("amount")) else 0.0,
        })
    return pd.DataFrame(rows)


def merge_new_data(old_csv_path: Path, new_df: pd.DataFrame, symbol: str, is_etf: bool) -> tuple[int, int, int]:
    """合并新旧数据，返回 (old_rows, new_rows, total_rows)"""
    old_rows = 0
    old_data = []

    with open(old_csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old_rows += 1
            old_data.append(row)

    # 获取旧数据最后日期
    old_dates = set()
    last_old_date = ""
    for row in old_data:
        date_key = row.get("timeString", row.get("timeString", ""))
        old_dates.add(date_key)
        if date_key > last_old_date:
            last_old_date = date_key

    logger.info(f"  {symbol}: 旧数据 {old_rows} 行, 最后日期 {last_old_date}")

    # 筛选新数据中旧数据没有的日期
    new_records = []
    for _, row in new_df.iterrows():
        date_str = row["timeString"]
        if date_str not in old_dates:
            new_records.append(row.to_dict())

    logger.info(f"  {symbol}: 新获取 {len(new_df)} 行, 其中有 {len(new_records)} 行是新增")

    if not new_records:
        return old_rows, 0, old_rows

    # 合并: 先把旧数据写入，再写入新数据
    all_rows = old_data + new_records

    # 写入文件 (统一 schema)
    with open(old_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_SCHEMA)
        writer.writeheader()
        writer.writerows(all_rows)

    return old_rows, len(new_records), len(all_rows)


def fix_etf_schema(file_path: Path, symbol: str) -> dict:
    """修复ETF文件的schema: 补充code列 + 统一列顺序"""
    issues = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    lines = content.strip().split("\n")
    header = lines[0].strip()
    columns = header.split(",")

    has_code = "code" in columns

    if has_code and columns == UNIFIED_SCHEMA:
        return {"fixed": False, "reason": "already correct schema"}

    # Read all data rows
    data_rows = []
    reader = csv.DictReader(lines)
    for row in reader:
        data_rows.append(row)

    # Normalize: ensure code column exists
    normalized = []
    for row in data_rows:
        nr = {}
        # Ensure code
        if "code" not in row or not row.get("code", "").strip():
            nr["code"] = symbol
        else:
            nr["code"] = row["code"]
        # Map various column names
        nr["timeString"] = row.get("timeString", row.get("trade_date", row.get("date", "")))
        nr["open"] = row.get("open", "")
        nr["high"] = row.get("high", "")
        nr["low"] = row.get("low", "")
        nr["close"] = row.get("close", "")
        nr["volume"] = row.get("volume", row.get("vol", ""))
        nr["amount"] = row.get("amount", "")
        normalized.append(nr)

    # Write back
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_SCHEMA)
        writer.writeheader()
        writer.writerows(normalized)

    issues_info = []
    if not has_code:
        issues_info.append("added missing code column")
    if columns != UNIFIED_SCHEMA:
        issues_info.append(f"reordered columns: {columns} -> {UNIFIED_SCHEMA}")

    return {"fixed": True, "issues": issues_info, "rows_before": len(data_rows), "rows_after": len(normalized)}


def scan_suspension_anomalies(file_path: Path) -> list[dict]:
    """扫描停牌异常: 零成交量 + 价格不变"""
    anomalies = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        prev_close = None
        prev_date = None
        for row in reader:
            try:
                volume = float(row.get("volume", 0))
                close = float(row.get("close", 0))
                open_p = float(row.get("open", 0))
                date = row.get("timeString", "")
            except (ValueError, TypeError):
                prev_close = None
                continue

            # 零成交量 + 价格几乎不变 = 停牌
            if volume == 0 and prev_close and abs(close - prev_close) / max(prev_close, 0.001) < 0.001:
                anomalies.append({
                    "date": date,
                    "symbol": row.get("code", file_path.stem),
                    "type": "suspect_suspension",
                    "volume": volume,
                    "open": open_p,
                    "close": close,
                    "prev_close": prev_close,
                })

            prev_close = close
            prev_date = date
    return anomalies


def clean_hist_duplicates() -> list[dict]:
    """清理 _hist.csv 重复文件 (移到备份目录)"""
    cleaned = []
    for f in sorted(KLINE_DIR.glob("*_hist.csv")):
        if not f.exists():
            logger.info(f"  {f.name}: 已不存在，跳过")
            continue
        symbol = f.name.replace("_hist.csv", "")
        daily_file = KLINE_DIR / f"{symbol}_daily_kline.csv"

        try:
            file_size = f.stat().st_size
        except FileNotFoundError:
            logger.info(f"  {f.name}: 已不存在，跳过")
            continue

        # 移到备份目录
        backup_subdir = BACKUP_DIR / "hist_backup"
        backup_subdir.mkdir(parents=True, exist_ok=True)
        dest = backup_subdir / f.name

        shutil.move(str(f), str(dest))
        cleaned.append({
            "file": f.name,
            "symbol": symbol,
            "backup_path": str(dest),
            "size_bytes": file_size,
        })
        logger.info(f"  移动 {f.name} → {dest}")
    return cleaned


def generate_manifest(files_info: list[dict], refresh_results: list[dict],
                       fix_results: list[dict], anomalies: list[dict],
                       cleaned_hist: list[dict]) -> dict:
    """生成 manifest.json"""
    total_new_rows = sum(r.get("new_rows", 0) for r in refresh_results)
    total_old_rows = sum(r.get("old_rows", 0) for r in refresh_results)
    total_anomalies = len(anomalies)
    total_files = len(files_info)
    etf_files = sum(1 for f in files_info if f["is_etf"])
    stock_files = sum(1 for f in files_info if not f["is_etf"])

    return {
        "manifest_version": "1.0",
        "generated_at": now_str(),
        "project": "research-assistant K-line data refresh",
        "data_directory": str(KLINE_DIR),
        "summary": {
            "total_kline_files": total_files,
            "stock_files": stock_files,
            "etf_files": etf_files,
            "hist_duplicates_cleaned": len(cleaned_hist),
            "total_new_rows_added": total_new_rows,
            "total_old_rows_before": total_old_rows,
            "suspension_anomalies_found": total_anomalies,
            "etf_schemas_fixed": len(fix_results),
        },
        "files_analyzed": files_info,
        "refresh_results": refresh_results,
        "schema_fixes": fix_results,
        "suspension_anomalies": anomalies[:20],  # 最多20条
        "hist_duplicates_cleaned": cleaned_hist,
        "schema_definition": UNIFIED_SCHEMA,
    }


def main():
    logger.info("=" * 60)
    logger.info("P1-1: K线数据恢复 + 数据刷新")
    logger.info("=" * 60)

    # Step 1: 分析现有的K线文件
    logger.info("\n[Step 1] 分析现有的K线文件...")
    files_info = analyze_kline_files()

    # Step 2: 修复ETF文件schema
    logger.info("\n[Step 2] 修复ETF文件schema...")
    fix_results = []
    for fi in files_info:
        if fi["missing_code_col"] or not fi["schema_ok"]:
            file_path = KLINE_DIR / fi["file"]
            logger.info(f"  修复 {fi['file']}...")
            result = fix_etf_schema(file_path, fi["symbol"])
            fix_results.append({
                "file": fi["file"],
                "symbol": fi["symbol"],
                **result,
            })
            if result.get("fixed"):
                logger.info(f"    ✅ 修复成功: {result.get('issues', [])}")
        else:
            logger.info(f"  {fi['file']}: schema OK, 跳过")

    # Step 3: 重新分析（修复后）
    logger.info("\n[Step 3] 重新分析文件（修复后）...")
    files_info_after = analyze_kline_files()

    # Step 4: 拉取新数据
    logger.info("\n[Step 4] 使用Tushare拉取2026-04-04至今的日线...")

    today_str = datetime.now(CST).strftime("%Y%m%d")
    start_str = "20260404"  # 从2026-04-04开始（04-03已有数据）

    refresh_results = []
    for fi in files_info_after:
        symbol = fi["symbol"]
        is_etf = fi["is_etf"]
        file_path = KLINE_DIR / fi["file"]

        logger.info(f"\n  [{symbol}] {'ETF' if is_etf else 'Stock'} 拉取数据...")

        if is_etf:
            new_df = pull_fund_daily(symbol, start_str, today_str)
        else:
            new_df = pull_daily_data(symbol, start_str, today_str)

        if new_df.empty:
            logger.warning(f"    ⚠️  {symbol}: 未获取到新数据")
            refresh_results.append({
                "symbol": symbol,
                "is_etf": is_etf,
                "status": "no_new_data",
                "new_rows": 0,
            })
            continue

        old_rows, new_rows, total_rows = merge_new_data(file_path, new_df, symbol, is_etf)
        logger.info(f"    ✅ {symbol}: 旧={old_rows}, 新增={new_rows}, 总计={total_rows}")
        refresh_results.append({
            "symbol": symbol,
            "is_etf": is_etf,
            "status": "ok",
            "old_rows": old_rows,
            "new_rows": new_rows,
            "total_rows": total_rows,
        })

    # Step 5: 扫描停牌异常
    logger.info("\n[Step 5] 扫描停牌异常（零成交量+价格不变）...")
    all_anomalies = []
    for fi in files_info_after:
        file_path = KLINE_DIR / fi["file"]
        anomalies = scan_suspension_anomalies(file_path)
        if anomalies:
            logger.info(f"  {fi['file']}: 发现 {len(anomalies)} 个停牌异常")
            all_anomalies.extend(anomalies)

    if not all_anomalies:
        logger.info("  未发现停牌异常 ✅")

    # Step 6: 清理重复 _hist.csv
    logger.info("\n[Step 6] 清理重复 _hist.csv 文件...")
    cleaned_hist = clean_hist_duplicates()

    # Step 7: 生成 data_refresh_report.md
    logger.info("\n[Step 7] 生成 data_refresh_report.md...")
    generate_report(files_info, refresh_results, fix_results, all_anomalies, cleaned_hist)

    # Step 8: 生成 manifest.json
    logger.info("\n[Step 8] 生成 manifest.json...")
    manifest = generate_manifest(files_info, refresh_results, fix_results, all_anomalies, cleaned_hist)

    manifest_path = REPORT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info(f"  ✅ manifest.json → {manifest_path}")

    # 保存一份到 backup
    backup_manifest = BACKUP_DIR / f"manifest_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info(f"  ✅ backup manifest → {backup_manifest}")

    # Summary
    total_new = sum(r.get("new_rows", 0) for r in refresh_results)
    logger.info("\n" + "=" * 60)
    logger.info(f"✅ P1-1 数据刷新完成")
    logger.info(f"   文件数: {len(files_info)}")
    logger.info(f"   ETF schema修复: {len(fix_results)}")
    logger.info(f"   新增行数: {total_new}")
    logger.info(f"   停牌异常: {len(all_anomalies)}")
    logger.info(f"   _hist.csv清理: {len(cleaned_hist)}")
    logger.info(f"   manifest: {manifest_path}")
    logger.info(f"   report: {REPORT_DIR / 'data_refresh_report.md'}")
    logger.info("=" * 60)


def generate_report(files_info, refresh_results, fix_results, anomalies, cleaned_hist):
    """生成 data_refresh_report.md"""
    lines = []
    lines.append(f"# K线数据刷新报告\n")
    lines.append(f"生成时间: {now_str()}\n")

    lines.append("## 1. 数据文件概览\n")
    lines.append(f"| 文件 | 类型 | 行数 | 最后日期 | Schema | 备注 |")
    lines.append(f"|------|------|------|----------|--------|------|")
    for fi in files_info:
        schema_status = "✅" if fi["schema_ok"] else "❌"
        etf_label = "ETF" if fi["is_etf"] else "Stock"
        notes = ""
        if fi["missing_code_col"]:
            notes = "缺少code列(已修复)" if any(f["symbol"] == fi["symbol"] for f in fix_results) else "缺少code列"
        elif fi["has_hist_file"]:
            notes = "有_hist副本(已清理)" if any(f["symbol"] == fi["symbol"] for f in cleaned_hist) else "有_hist副本"
        lines.append(f"| {fi['file']} | {etf_label} | {fi['row_count']} | {fi['last_date']} | {schema_status} | {notes} |")

    lines.append("\n## 2. 数据拉取结果\n")
    lines.append(f"| 股票 | 类型 | 状态 | 旧行数 | 新增行数 | 现总行数 |")
    lines.append(f"|------|------|------|--------|----------|----------|")
    for r in refresh_results:
        old = r.get("old_rows", "-")
        new = r.get("new_rows", "-")
        total = r.get("total_rows", "-")
        status_icon = "✅" if r["status"] == "ok" else "⚠️"
        lines.append(f"| {r['symbol']} | {'ETF' if r['is_etf'] else 'Stock'} | {status_icon} {r['status']} | {old} | {new} | {total} |")

    lines.append("\n## 3. ETF Schema修复\n")
    if fix_results:
        lines.append(f"| 文件 | 修复内容 |")
        lines.append(f"|------|----------|")
        for fr in fix_results:
            if fr.get("fixed"):
                lines.append(f"| {fr['file']} | {'; '.join(fr.get('issues', []))} |")
    else:
        lines.append("无需修复\n")

    lines.append("\n## 4. 停牌异常\n")
    if anomalies:
        anomalies_sorted = sorted(anomalies, key=lambda x: x["date"])
        lines.append(f"| 日期 | 股票 | 类型 | 成交量 | 收盘价 | 前收盘 |")
        lines.append(f"|------|------|------|--------|--------|--------|")
        for a in anomalies_sorted:
            lines.append(f"| {a['date']} | {a['symbol']} | {a['type']} | {a['volume']} | {a['close']} | {a.get('prev_close', 'N/A')} |")
        lines.append(f"\n共发现 {len(anomalies)} 个停牌异常\n")
    else:
        lines.append("未发现停牌异常 ✅\n")

    lines.append("\n## 5. 重复文件清理\n")
    if cleaned_hist:
        lines.append(f"| 原文件 | 备份位置 |")
        lines.append(f"|--------|----------|")
        for ch in cleaned_hist:
            lines.append(f"| {ch['file']} | {ch['backup_path']} |")
    else:
        lines.append("无重复文件\n")

    lines.append("\n## 6. 备份信息\n")
    lines.append(f"- 备份目录: `{BACKUP_DIR}`")
    lines.append(f"- K线备份: `{BACKUP_DIR}/kline_backup_*`")
    lines.append(f"- hist备份: `{BACKUP_DIR}/hist_backup/`")
    lines.append(f"- Manifest: `{REPORT_DIR}/manifest.json`\n")

    lines.append("\n## 7. 统一Schema\n")
    lines.append(f"`{','.join(UNIFIED_SCHEMA)}`\n")
    lines.append("| 字段 | 类型 | 说明 |")
    lines.append("|------|------|------|")
    lines.append("| code | string | 股票代码 (6位数字) |")
    lines.append("| timeString | string | 交易日 YYYY-MM-DD |")
    lines.append("| open | float | 开盘价 |")
    lines.append("| high | float | 最高价 |")
    lines.append("| low | float | 最低价 |")
    lines.append("| close | float | 收盘价 |")
    lines.append("| volume | int | 成交量 (股) |")
    lines.append("| amount | float | 成交额 (元) |")

    report_path = REPORT_DIR / "data_refresh_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"  ✅ Report → {report_path}")


if __name__ == "__main__":
    main()
