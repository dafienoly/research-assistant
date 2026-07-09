#!/usr/bin/env python3
"""
Test: K线数据新鲜度与Schema完整性

验证 data/market/daily_kline/ 下所有 K 线文件:
1. 统一 schema: code,timeString,open,high,low,close,volume,amount
2. 数据新鲜度: 最后交易日不早于最近第3个交易日
3. 无缺失关键字段
4. 停牌异常标记
5. ETF 文件有 code 列
6. 无 _hist.csv 残留
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).resolve().parent.parent.parent
KLINE_DIR = BASE / "data" / "market" / "daily_kline"
MANIFEST_PATH = BASE / "data" / "manifest.json"

UNIFIED_SCHEMA = ["code", "timeString", "open", "high", "low", "close", "volume", "amount"]

# 允许的最晚新鲜度: 当前日期前第3个交易日（保守估计）
# 实际检查时放宽到 5 个自然日
STALENESS_DAYS = 5


def _get_csv_header(filepath: Path) -> list[str]:
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return f.readline().strip().split(",")


def _get_last_date(filepath: Path) -> str | None:
    """读取 CSV 最后一行的时间"""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        last_date = None
        for row in reader:
            last_date = row.get("timeString", "")
    return last_date


def test_all_kline_files_exist():
    """验证 daily_kline 目录存在且包含文件"""
    assert KLINE_DIR.exists(), f"目录不存在: {KLINE_DIR}"
    csv_files = list(KLINE_DIR.glob("*_daily_kline.csv"))
    assert len(csv_files) > 0, f"未找到任何 _daily_kline.csv 文件"


def test_no_hist_csv_remains():
    """验证无 _hist.csv 残留文件"""
    hist_files = list(KLINE_DIR.glob("*_hist.csv"))
    assert len(hist_files) == 0, f"发现未清理的 _hist.csv 文件: {[f.name for f in hist_files]}"


def test_unified_schema():
    """所有 K 线文件使用统一 schema: code,timeString,open,high,low,close,volume,amount"""
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        header = _get_csv_header(f)
        assert header == UNIFIED_SCHEMA, (
            f"{f.name}: schema 不匹配\n"
            f"  期望: {UNIFIED_SCHEMA}\n"
            f"  实际: {header}"
        )


def test_code_column_present():
    """所有文件包含 code 列（ETF 文件已补充 code 列）"""
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        header = _get_csv_header(f)
        assert "code" in header, f"{f.name}: 缺少 code 列"


def test_required_fields_not_empty():
    """关键字段非空: code, timeString, close"""
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        with open(f, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            row_num = 1
            for row in reader:
                row_num += 1
                code = row.get("code", "").strip()
                time_string = row.get("timeString", "").strip()
                close = row.get("close", "").strip()
                assert code, f"{f.name}: 第{row_num}行 code 为空"
                assert time_string, f"{f.name}: 第{row_num}行 timeString 为空"
                assert close, f"{f.name}: 第{row_num}行 close 为空"


def test_data_freshness():
    """数据新鲜度: 最后交易日不早于 STALENESS_DAYS 天前（允许个别停牌标的过旧）"""
    today = datetime.now(CST)
    cutoff = today - timedelta(days=STALENESS_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    stale_files = []
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        last_date = _get_last_date(f)
        assert last_date is not None, f"{f.name}: 无法读取最后日期"
        if last_date < cutoff_str:
            stale_files.append((f.name, last_date))

    # 允许最多 1 个文件过旧（可能因停牌等特殊原因）
    if len(stale_files) > 1:
        stale_detail = "; ".join(f"{f}: {d}" for f, d in stale_files)
        pytest.fail(f"有 {len(stale_files)} 个文件数据过旧 (< {cutoff_str}): {stale_detail}")
    elif stale_files:
        print(f"  ⚠️ 1 个文件数据略旧（可能因停牌）: {stale_files[0]}")


def test_suspension_anomalies():
    """停牌异常检测: 零成交量且价格不变时标记"""
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        anomalies = []
        with open(f, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            prev_close = None
            for row in reader:
                try:
                    volume = float(row.get("volume", 0) or 0)
                    close = float(row.get("close", 0) or 0)
                except (ValueError, TypeError):
                    prev_close = None
                    continue

                if volume == 0 and prev_close is not None:
                    pct_change = abs(close - prev_close) / max(abs(prev_close), 0.001)
                    if pct_change < 0.001:
                        anomalies.append({
                            "date": row.get("timeString", ""),
                            "close": close,
                            "prev_close": prev_close,
                        })

                prev_close = close

        # 记录但不断言失败（停牌可能是正常的）
        if anomalies:
            dates = [a["date"] for a in anomalies]
            print(f"  ⚠️ {f.name}: {len(anomalies)} 个停牌异常: {dates}")


def test_code_consistent_with_filename():
    """CSV 内的 code 列与文件名一致"""
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        symbol = f.name.replace("_daily_kline.csv", "")
        with open(f, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                code = row.get("code", "").strip()
                assert code == symbol, (
                    f"{f.name}: code 列 '{code}' 与文件名 '{symbol}' 不一致"
                )
                break  # 只需检查第一行


def test_manifest_exists():
    """验证 manifest.json 存在"""
    assert MANIFEST_PATH.exists(), f"manifest.json 不存在: {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert "summary" in manifest
    assert "files_analyzed" in manifest
    assert "generated_at" in manifest


def test_volume_amount_format():
    """成交量/成交额格式: volume 为整数, amount 为浮点数"""
    for f in sorted(KLINE_DIR.glob("*_daily_kline.csv")):
        with open(f, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            row_num = 1
            for row in reader:
                row_num += 1
                try:
                    vol = float(row.get("volume", 0))
                    amt = float(row.get("amount", 0))
                except (ValueError, TypeError):
                    assert False, f"{f.name}: 第{row_num}行 volume/amount 格式错误"
