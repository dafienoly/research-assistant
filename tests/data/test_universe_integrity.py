#!/usr/bin/env python3
"""
Test: 股票池 U1 完整性审计

验证 U1 (用户可交易池):
1. U1 ⊆ U0 (严格子集) — 所有 U1 的 ts_code 必须在 U0 中
2. U1 不包含退市/*ST/ST/停牌/北交所标的
3. U1 不含 name 带 "退" 的标的
4. U1 有 daily_basic 扩展字段 (total_mv, float_mv, turnover_rate, amount)
5. industry 不是字符串 "nan"
6. concepts 返回空数组（当无数据时）
"""

import json
import os
import sys
from pathlib import Path

# 添加 commands 到路径
BASE = Path(__file__).resolve().parent.parent  # research-assistant/
COMMANDS_DIR = BASE / "commands"
if str(COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(COMMANDS_DIR))

OUTPUT_FILE = BASE / "data" / "universes.json"

# ─── 在路径设置完成后导入 universes ─────────────────────
from universes import (
    build_u0,
    build_u1,
    EXCLUDE_STAR,
    EXCLUDE_CHINEXT,
)


def _load_or_build() -> dict:
    """读取现有的 universes.json 或重新构建"""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "universes" in data and "U0" in data["universes"] and "U1" in data["universes"]:
            return data["universes"]
    # 构建
    from universes import build_all
    result = build_all()
    return result["universes"]


# ─── U1 ⊆ U0 ─────────────────────────────────────────────


def test_u1_is_strict_subset_of_u0():
    """U1 必须是 U0 的严格子集"""
    universes = _load_or_build()
    u0 = universes.get("U0", {})
    u1 = universes.get("U1", {})

    u0_codes = {s["ts_code"] for s in u0.get("stocks", [])}
    u1_codes = {s["ts_code"] for s in u1.get("stocks", [])}

    # U1 非空
    assert len(u1_codes) > 0, "U1 为空"

    # U1 ⊆ U0
    u1_not_in_u0 = u1_codes - u0_codes
    assert len(u1_not_in_u0) == 0, (
        f"U1 中有 {len(u1_not_in_u0)} 只股票不在 U0 中: {sorted(u1_not_in_u0)[:5]}"
    )

    # U1 ⊂ U0 (严格子集)
    assert u1_codes < u0_codes, "U1 不是 U0 的严格子集"


# ─── 过滤规则 ────────────────────────────────────────────


def test_u1_no_delisted_names():
    """U1 不含 name 带 '退' 的标的"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        name = str(s.get("name", ""))
        assert "退" not in name, f"U1 包含退市名称: {s['ts_code']} - {name}"


def test_u1_no_st_stocks():
    """U1 不含 ST/*ST 标记的标的"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        is_st = s.get("is_st", False)
        assert not is_st, (
            f"U1 包含 ST 标记: {s['ts_code']} - {s.get('name', '')}"
        )


def test_u1_no_suspended():
    """U1 不含停牌标的"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        is_suspended = s.get("is_suspended", False)
        assert not is_suspended, (
            f"U1 包含停牌: {s['ts_code']} - {s.get('name', '')}"
        )


def test_u1_no_bse():
    """U1 不含北交所标的"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        is_bse = s.get("is_bse", False)
        assert not is_bse, (
            f"U1 包含北交所: {s['ts_code']}"
        )


def test_u1_no_star_if_excluded():
    """如果 EXCLUDE_STAR=True, U1 不含科创板标的"""
    if not EXCLUDE_STAR:
        return  # 跳过
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        is_star = s.get("is_star", False)
        assert not is_star, (
            f"U1 包含科创板(已排除): {s['ts_code']}"
        )


def test_u1_no_chinext_if_excluded():
    """如果 EXCLUDE_CHINEXT=True, U1 不含创业板标的"""
    if not EXCLUDE_CHINEXT:
        return  # 跳过
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        is_chinext = s.get("is_chinext", False)
        assert not is_chinext, (
            f"U1 包含创业板(已排除): {s['ts_code']}"
        )


# ─── 扩展字段 ────────────────────────────────────────────


def test_u1_has_daily_basic_fields():
    """U1 包含 daily_basic 扩展字段"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    required_daily_basic = ["total_mv", "float_mv", "turnover_rate", "amount"]
    for s in u1.get("stocks", []):
        for field in required_daily_basic:
            assert field in s, (
                f"U1 {s['ts_code']} 缺少 daily_basic 字段: {field}"
            )


def test_u1_has_pe_pb():
    """U1 包含 pe,pb 估值字段"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        assert "pe" in s, f"U1 {s['ts_code']} 缺少 pe 字段"
        assert "pb" in s, f"U1 {s['ts_code']} 缺少 pb 字段"


def test_u1_industry_not_nan_string():
    """industry 字段不是字符串 'nan'"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        industry = s.get("industry")
        if industry is not None:
            assert str(industry).strip().lower() != "nan", (
                f"U1 {s['ts_code']} industry 是字符串 'nan': {industry}"
            )


def test_u1_industry_missing_reason():
    """当 industry 为 None 时，必须有 industry_missing_reason"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        if s.get("industry") is None:
            reason = s.get("industry_missing_reason")
            assert reason is not None and str(reason).strip(), (
                f"U1 {s['ts_code']} industry=None 但缺少 industry_missing_reason"
            )


def test_u1_concepts_is_list():
    """concepts 字段为数组（可能为空）"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        concepts = s.get("concepts")
        assert isinstance(concepts, list), (
            f"U1 {s['ts_code']} concepts 不是数组: {type(concepts)}"
        )


def test_u1_has_concepts_lineage():
    """U1 包含 concepts_lineage 说明"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        assert "concepts_lineage" in s, (
            f"U1 {s['ts_code']} 缺少 concepts_lineage"
        )
        assert s["concepts_lineage"], "concepts_lineage 不能为空"


# ─── 结构完整性 ──────────────────────────────────────────


def test_u1_has_filtered_counts():
    """U1 包含 filtered_counts 统计"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    assert "filtered_counts" in u1, "U1 缺少 filtered_counts"
    fc = u1["filtered_counts"]
    assert isinstance(fc, dict), "filtered_counts 不是 dict"
    for key in ("退市", "名称含退", "ST/ST标记", "停牌", "北交所", "科创板(排除)", "创业板(排除)"):
        assert key in fc, f"filtered_counts 缺少 {key}"


def test_u1_data_sources():
    """U1 数据来源声明"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    assert "Tushare daily_basic" in " ".join(u1.get("data_sources", [])), \
        "U1 缺少 daily_basic 数据来源声明"


def test_u1_board_matches_ts_code():
    """U1 board 字段与 ts_code 前缀一致"""
    universes = _load_or_build()
    u1 = universes.get("U1", {})
    for s in u1.get("stocks", []):
        ts_code = s["ts_code"]
        board = s.get("board", "")
        symbol = ts_code.split(".")[0]
        if symbol.startswith("6"):
            assert board == "主板" or board == "科创板", (
                f"{ts_code}: 6开头但 board='{board}'"
            )
        elif symbol.startswith("3"):
            assert board == "创业板", (
                f"{ts_code}: 3开头但 board='{board}'"
            )
        elif symbol.startswith("8"):
            assert board == "北交所", (
                f"{ts_code}: 8开头但 board='{board}'"
            )
        elif symbol.startswith(("0", "002", "001")):
            assert board == "主板", (
                f"{ts_code}: 0开头但 board='{board}'"
            )
