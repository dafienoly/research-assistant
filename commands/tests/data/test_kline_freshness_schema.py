"""Canonical DataHub K 线新鲜度与 schema 一致性测试。"""
import csv
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from factor_lab.datahub_access import STOCK_BASIC_PATH, daily_kline_root

CST = timezone(timedelta(hours=8))
KLINE_DIR = str(daily_kline_root())
TODAY = datetime.now(CST)


def _get_kline_files():
    if not os.path.isdir(KLINE_DIR):
        return []
    with open(STOCK_BASIC_PATH, encoding="utf-8-sig", newline="") as reference:
        canonical_codes = {
            str(row.get("ts_code", "")).strip().upper()
            for row in csv.DictReader(reference)
            if row.get("ts_code")
        }
    return [
        f for f in os.listdir(KLINE_DIR)
        if f.endswith(".csv")
        and not f.startswith("valuation_")
        and not f.startswith(".")
        and f[:-4].upper() in canonical_codes
    ]


def _date_value(row):
    for key in ("trade_date", "date", "timeString"):
        if row.get(key):
            return row[key]
    return ""


def _sample_kline_files(limit: int = 20):
    """Keep unit tests bounded; full-file checks belong to DataHub integrity audit."""
    return _get_kline_files()[:limit]


def test_kline_directory_exists():
    assert os.path.isdir(KLINE_DIR), f"K线目录不存在: {KLINE_DIR}"


def test_kline_files_exist():
    files = _sample_kline_files()
    assert len(files) >= 1, f"K线文件数量不足: {len(files)}"


def test_kline_freshness():
    """最新K线日期距当前交易日 <= 3天"""
    files = _sample_kline_files()
    latest = None
    for fname in files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            dates = [_date_value(r) for r in reader if _date_value(r)]
            if dates:
                fd = max(dates)
                if latest is None or fd > latest:
                    latest = fd
    assert latest is not None, "未找到任何日期数据"
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            ld = datetime.strptime(latest[:10], fmt)
            break
        except ValueError:
            continue
    else:
        ld = datetime.strptime(latest[:8], "%Y%m%d")
    ld = ld.replace(tzinfo=None)
    stale = (TODAY.replace(tzinfo=None) - ld).days
    assert stale <= 3, f"K线数据已过期 {stale} 天 (最新日期: {latest})"


def test_kline_schema_uniform():
    """所有 canonical K 线文件包含统一字段。"""
    files = _sample_kline_files()
    expected = {"ts_code", "trade_date", "open", "high", "low", "close", "amount"}
    for fname in files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            missing = expected - fields
            assert not missing, f"{fname}: 缺少列 {missing}, 实际字段={fields}"
            assert {"vol", "volume"} & fields, f"{fname}: 缺少成交量列"


def test_no_future_dates():
    """无未来日期"""
    files = _sample_kline_files()
    for fname in files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ds = _date_value(r)
                assert ds, f"{fname}: 空日期"
                try:
                    d = datetime.strptime(ds[:10], "%Y-%m-%d")
                except ValueError:
                    d = datetime.strptime(ds[:8], "%Y%m%d")
                assert d.replace(tzinfo=None) <= TODAY.replace(tzinfo=None), f"{fname}: 未来日期 {ds}"


def test_no_duplicate_hist():
    """无旧历史文件与 canonical 文件重复"""
    all_files = os.listdir(KLINE_DIR) if os.path.isdir(KLINE_DIR) else []
    hist = [f for f in all_files if f.endswith("_hist.csv") and not f.startswith(".")]
    kline = _get_kline_files()
    for hf in hist:
        base = hf.replace("_hist.csv", "")
        pair = [k for k in kline if base in k]
        for pk in pair:
            with open(os.path.join(KLINE_DIR, hf), encoding="utf-8-sig") as f1, open(
                os.path.join(KLINE_DIR, pk), encoding="utf-8-sig"
            ) as f2:
                assert f1.read() != f2.read(), f"重复文件: {hf} == {pk}"


def test_ohlc_consistency():
    """OHLC 一致性: high >= max(open,close), low <= min(open,close)"""
    files = _get_kline_files()
    for fname in files[:3]:  # 抽检3个文件
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath) as f:
            reader = csv.DictReader(f)
            for i, r in enumerate(reader):
                try:
                    o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                except (ValueError, KeyError):
                    continue
                assert h >= max(o, c), f"{fname} 行{i}: high={h} < max(open={o},close={c})"
                assert l <= min(o, c), f"{fname} 行{i}: low={l} > min(open={o},close={c})"
