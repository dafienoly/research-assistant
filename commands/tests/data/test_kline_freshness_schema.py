"""K线数据新鲜度与schema一致性测试 — V5.1 P1-1验收"""
import os, csv, sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(BASE, "data")
KLINE_DIR = os.path.join(DATA_DIR, "market", "daily_kline")
TODAY = datetime.now(CST)


def _get_kline_files():
    if not os.path.isdir(KLINE_DIR):
        return []
    return [f for f in os.listdir(KLINE_DIR) if f.endswith("_daily_kline.csv")]


def test_kline_directory_exists():
    assert os.path.isdir(KLINE_DIR), f"K线目录不存在: {KLINE_DIR}"


def test_kline_files_exist():
    files = _get_kline_files()
    assert len(files) >= 1, f"K线文件数量不足: {len(files)}"


def test_kline_freshness():
    """最新K线日期距当前交易日 <= 3天"""
    files = _get_kline_files()
    latest = None
    for fname in files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath) as f:
            reader = csv.DictReader(f)
            dates = [r["timeString"] for r in reader if "timeString" in r]
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
    """所有K线文件必须包含 code, timeString, open, high, low, close, volume, amount"""
    files = _get_kline_files()
    expected = {"code", "timeString", "open", "high", "low", "close", "volume", "amount"}
    for fname in files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath) as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            missing = expected - fields
            assert not missing, f"{fname}: 缺少列 {missing}, 实际字段={fields}"


def test_no_future_dates():
    """无未来日期"""
    files = _get_kline_files()
    for fname in files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath) as f:
            reader = csv.DictReader(f)
            for r in reader:
                ds = r.get("timeString", "")
                assert ds, f"{fname}: 空日期"
                try:
                    d = datetime.strptime(ds[:10], "%Y-%m-%d")
                except ValueError:
                    d = datetime.strptime(ds[:8], "%Y%m%d")
                assert d.replace(tzinfo=None) <= TODAY.replace(tzinfo=None), f"{fname}: 未来日期 {ds}"


def test_no_duplicate_hist():
    """无 _hist.csv 与 _daily_kline.csv 重复"""
    all_files = os.listdir(KLINE_DIR) if os.path.isdir(KLINE_DIR) else []
    hist = [f for f in all_files if f.endswith("_hist.csv") and not f.startswith(".")]
    kline = [f for f in all_files if f.endswith("_daily_kline.csv")]
    for hf in hist:
        base = hf.replace("_hist.csv", "")
        pair = [k for k in kline if base in k]
        for pk in pair:
            with open(os.path.join(KLINE_DIR, hf)) as f1, open(os.path.join(KLINE_DIR, pk)) as f2:
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
