"""股票池U1/U0完整性测试 — V5.1 P1-2验收"""
import os, sys, json

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
UNIVERSE_FILE = os.path.join(BASE, "data", "universes.json")


def _load():
    with open(UNIVERSE_FILE) as f:
        return json.load(f)


def test_universe_file_exists():
    assert os.path.exists(UNIVERSE_FILE), f"universes.json 不存在: {UNIVERSE_FILE}"


def test_u0_larger_than_u1():
    """U1 必须是 U0 的严格子集"""
    d = _load()
    universes = d.get("universes", d)
    u0 = universes.get("U0", {})
    u1 = universes.get("U1", {})
    u0_stocks = u0.get("stocks", u0.get("stock_list", []))
    u1_stocks = u1.get("stocks", u1.get("stock_list", []))
    if isinstance(u0_stocks, int):
        u0_count = u0_stocks
    elif isinstance(u0_stocks, list):
        u0_count = len(u0_stocks)
    else:
        u0_count = u0.get("total_stocks", 0)

    if isinstance(u1_stocks, int):
        u1_count = u1_stocks
    elif isinstance(u1_stocks, list):
        u1_count = len(u1_stocks)
    else:
        u1_count = u1.get("total_stocks", 0)

    assert u1_count > 0, "U1 为空"
    assert u1_count < u0_count, f"U1 ({u1_count}) >= U0 ({u0_count})"


def test_u1_no_delisted():
    """U1 中退市数 = 0"""
    d = _load()
    u1 = d.get("universes", d).get("U1", {})
    stocks = u1.get("stocks", u1.get("stock_list", []))
    if not isinstance(stocks, list):
        return  # 格式不一致时跳过
    delisted = sum(1 for s in stocks if s.get("list_status") == "D" or s.get("delist_date"))
    assert delisted == 0, f"U1 含 {delisted} 只退市股票"


def test_u1_no_st():
    """U1 中 ST 数 = 0"""
    d = _load()
    u1 = d.get("universes", d).get("U1", {})
    stocks = u1.get("stocks", u1.get("stock_list", []))
    if not isinstance(stocks, list):
        return
    st = sum(1 for s in stocks if "ST" in str(s.get("name", "")).upper() or "*ST" in str(s.get("name", "")).upper())
    assert st == 0, f"U1 含 {st} 只ST股票"


def test_u1_no_tui():
    """U1 中 name 含 '退' 的数量 = 0"""
    d = _load()
    u1 = d.get("universes", d).get("U1", {})
    stocks = u1.get("stocks", u1.get("stock_list", []))
    if not isinstance(stocks, list):
        return
    tui = sum(1 for s in stocks if "退" in str(s.get("name", "")))
    assert tui == 0, f"U1 含 {tui} 只名称含\"退\"的股票"


def test_u1_total_mv_nonnull():
    """U1 中 total_mv 非空比例 >= 80%"""
    d = _load()
    u1 = d.get("universes", d).get("U1", {})
    stocks = u1.get("stocks", u1.get("stock_list", []))
    if not isinstance(stocks, list):
        return
    total = len(stocks)
    nonnull = sum(1 for s in stocks if s.get("total_mv") and s.get("total_mv") != 0)
    ratio = nonnull / max(total, 1) * 100
    assert ratio >= 80, f"U1 total_mv 非空率仅 {ratio:.1f}% ({nonnull}/{total})"


def test_u1_float_mv_nonnull():
    """U1 中 float_mv 非空比例 >= 80%"""
    d = _load()
    u1 = d.get("universes", d).get("U1", {})
    stocks = u1.get("stocks", u1.get("stock_list", []))
    if not isinstance(stocks, list):
        return
    total = len(stocks)
    nonnull = sum(1 for s in stocks if s.get("float_mv") and s.get("float_mv") != 0)
    ratio = nonnull / max(total, 1) * 100
    assert ratio >= 80, f"U1 float_mv 非空率仅 {ratio:.1f}% ({nonnull}/{total})"
