#!/usr/bin/env python3
"""
V4.1 分层股票池 U0-U4 + ETF替代池

用法:
    python3 hermes_cli.py universe:build         构建所有分层股票池
    python3 hermes_cli.py universe:list          列出所有股票池
    python3 hermes_cli.py universe:show U0       显示指定股票池详情
    python3 hermes_cli.py universe:audit         审计所有股票池

模块内部:
    build_all()       → 构建 U0-U4 + ETF, 写入 data/universes.json
    get_universe(u)   → 返回指定池的 dict
    list_universes()  → 返回所有池名称列表
    audit()           → 返回审计 dict

数据来源:
    - Tushare Pro (stock_basic, daily_basic, stk_limit, suspend_d, namechange)
    - pool.csv (315 只 AI 图谱候选)
    - ai_chainmap_watchlist_tags.csv (AI 产业链标签)
    - 硬编码 ETF 清单 (半导体/AI 主题)
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import numpy as np

from factor_lab.data import tushare_client as _ts_client_mod

logger = logging.getLogger(__name__)

# 使用函数封装 get_ts_client 以便测试可以 patch 模块级别
def _get_ts_client():
    """获取 TushareClient 单例"""
    return _ts_client_mod.get_ts_client()

# ─── 路径 ────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # research-assistant/
DATA_DIR = BASE / "data"
OUTPUT_FILE = DATA_DIR / "universes.json"

# Windows Data Hub (只读)
CODEX_DATA = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub")
POOL_CSV = CODEX_DATA / "market" / "pool.csv"
AI_CHAINMAP_CSV = CODEX_DATA / "tags" / "ai_chainmap_watchlist_tags.csv"
SEMICONDUCTOR_CHAIN_CSV = CODEX_DATA / "tags" / "semiconductor_chain_tags.csv"

# 时区
CST = timezone(timedelta(hours=8))

# ─── ETF 替代池 ──────────────────────────────────────────────────────
ETF_REPLACEMENT_POOL: list[dict[str, Any]] = [
    {"ts_code": "512480.SH", "name": "半导体ETF",        "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证全指半导体产品与设备指数"},
    {"ts_code": "512760.SH", "name": "芯片ETF",          "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中华交易服务芯片产业指数"},
    {"ts_code": "159813.SZ", "name": "半导体ETF",        "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "国证半导体芯片指数"},
    {"ts_code": "159995.SZ", "name": "芯片ETF",          "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "国证芯片指数"},
    {"ts_code": "588000.SH", "name": "科创50ETF",        "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "上证科创板50成份指数"},
    {"ts_code": "588050.SH", "name": "科创芯片ETF",      "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "上证科创板芯片指数"},
    {"ts_code": "159859.SZ", "name": "科创芯片ETF",      "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "国证半导体芯片指数"},
    {"ts_code": "515050.SH", "name": "AI算力ETF",        "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证人工智能主题指数"},
    {"ts_code": "517050.SH", "name": "5G通信ETF",        "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证5G通信主题指数"},
    {"ts_code": "159865.SZ", "name": "消费电子ETF",      "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证消费电子主题指数"},
    {"ts_code": "159997.SZ", "name": "电子ETF",          "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证电子指数"},
    {"ts_code": "512480.SH", "name": "半导体设备材料ETF", "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证半导体材料设备指数"},
    {"ts_code": "159801.SZ", "name": "芯片龙头ETF",      "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "国证芯片指数"},
    {"ts_code": "159967.SZ", "name": "科创创业50ETF",    "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "中证科创创业50指数"},
    {"ts_code": "588060.SH", "name": "科创信息技术ETF",  "fund_type": "ETF", "mgmt_fee": 0.50, "track_index": "上证科创板新一代信息技术指数"},
]


# ─── 辅助函数 ─────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _read_csv_safe(path: Path) -> list[dict[str, str]]:
    """安全读取 CSV，返回 list[dict]"""
    if not path.exists():
        logger.warning(f"文件不存在: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        logger.error(f"读取 {path} 失败: {e}")
        return []


def _ts_code_to_symbol(ts_code: str) -> str:
    """ts_code (688012.SH) → symbol (688012)"""
    return ts_code.split(".")[0]


def _symbol_to_ts_code(symbol: str, exchange: str = "") -> str:
    """symbol → ts_code，按交易所补充后缀"""
    s = str(symbol).strip()
    if "." in s and s.split(".")[1] in ("SH", "SZ", "BJ"):
        return s
    if exchange:
        if exchange in ("SSE", "上交所", "上海"):
            return f"{s}.SH"
        elif exchange in ("SZSE", "深交所", "深圳"):
            return f"{s}.SZ"
        elif exchange in ("BSE", "北交所", "北京"):
            return f"{s}.BJ"
    # 按代码前缀推断
    if s.startswith("6"):
        return f"{s}.SH"
    elif s.startswith(("0", "3")):
        return f"{s}.SZ"
    elif s.startswith("8"):
        return f"{s}.BJ"
    return s


def _parse_board(market: str) -> str:
    """解析板块"""
    m = str(market).lower()
    if "主板" in m or m == "main":
        return "主板"
    if "创业板" in m or m == "chinext":
        return "创业板"
    if "科创板" in m or m == "star":
        return "科创板"
    if "北交所" in m or m == "bse":
        return "北交所"
    return m


def _is_st_from_name(name: str) -> bool:
    """根据股票名称判断是否 ST/*ST"""
    name = str(name).strip().upper()
    return name.startswith("ST") or name.startswith("*ST") or name.startswith("SST")


# ══════════════════════════════════════════════════════════════════════
# U0 全 A 基础池
# ══════════════════════════════════════════════════════════════════════

def build_u0() -> dict[str, Any]:
    """构建 U0 全 A 基础池

    数据来源: Tushare stock_basic + daily_basic + concept
    字段:
        ts_code, symbol, name, exchange, board, list_date, delist_date,
        is_listed, industry, concepts, total_mv, float_mv
    """
    tc = _get_ts_client()

    # 1) stock_basic — 全 A 上市股票
    stocks = tc.stock_basic(list_status="L")
    if stocks.empty:
        raise RuntimeError("Tushare stock_basic 返回空，无法构建 U0")

    # 获取退市/暂停股票
    stocks_delist = tc.stock_basic(list_status="D")
    stocks_pause = tc.stock_basic(list_status="P")
    stocks_all = pd.concat([stocks, stocks_delist, stocks_pause], ignore_index=True)

    # 2) 去重保留最新状态
    stocks_all = stocks_all.drop_duplicates(subset=["ts_code"], keep="first")

    # 3) 获取最新交易日 daily_basic (市值)
    latest_trade_date = ""
    try:
        cal = tc.trade_cal(start_date="20260601", end_date=_now_str()[:10].replace("-", ""))
        if not cal.empty:
            open_days = cal[cal["is_open"] == 1].sort_values("cal_date")
            if not open_days.empty:
                latest_trade_date = open_days["cal_date"].iloc[-1].strftime("%Y%m%d")
    except Exception:
        pass

    daily_basic_df = pd.DataFrame()
    if latest_trade_date:
        try:
            daily_basic_df = tc._query(
                "daily_basic",
                trade_date=latest_trade_date,
                fields="ts_code,total_mv,circ_mv",
            )
        except Exception as e:
            logger.warning(f"daily_basic 查询失败: {e}")

    # 4) 概念板块 — 获取所有概念并映射到股票
    concepts_map: dict[str, list[str]] = {}
    try:
        concept_df = tc.concept()
        if not concept_df.empty and "code" in concept_df.columns:
            for _, row in concept_df.iterrows():
                ccode = row.get("code", "")
                cname = row.get("name", "")
                if ccode:
                    detail = tc.concept_detail(concept_code=ccode)
                    if not detail.empty and "ts_code" in detail.columns:
                        concepts_map[cname] = detail["ts_code"].tolist()
    except Exception as e:
        logger.warning(f"概念板块查询失败: {e}")

    # 5) 构建每只股票的信息
    records: list[dict[str, Any]] = []
    for _, row in stocks_all.iterrows():
        ts_code = str(row.get("ts_code", ""))
        if not ts_code:
            continue
        symbol = _ts_code_to_symbol(ts_code)
        name = str(row.get("name", ""))
        market = str(row.get("market", ""))
        board = _parse_board(market)
        list_date = row.get("list_date", pd.NaT)
        delist_date = row.get("delist_date", pd.NaT)
        is_listed = (
            ts_code in stocks["ts_code"].values
            if not stocks.empty
            else True
        )

        # 行业
        industry = str(row.get("industry", ""))

        # 概念
        concepts = [cname for cname, codes in concepts_map.items() if ts_code in codes]

        # 总市值 / 流通市值
        total_mv = None
        float_mv = None
        if not daily_basic_df.empty and ts_code in daily_basic_df["ts_code"].values:
            match = daily_basic_df[daily_basic_df["ts_code"] == ts_code]
            if not match.empty:
                total_mv = float(match.iloc[0].get("total_mv", 0))
                float_mv = float(match.iloc[0].get("circ_mv", 0))

        records.append({
            "ts_code": ts_code,
            "symbol": symbol,
            "name": name,
            "exchange": market,
            "board": board,
            "list_date": str(list_date)[:10] if pd.notna(list_date) else "",
            "delist_date": str(delist_date)[:10] if pd.notna(delist_date) else "",
            "is_listed": is_listed,
            "industry": industry,
            "concepts": concepts,
            "total_mv": total_mv,
            "float_mv": float_mv,
        })

    return {
        "name": "U0",
        "label": "全A基础池",
        "description": "全A所有上市股票（含非上市状态标记）",
        "built_at": _now_str(),
        "data_sources": ["Tushare stock_basic", "Tushare daily_basic", "Tushare concept"],
        "total_stocks": len(records),
        "stocks": records,
    }


# ══════════════════════════════════════════════════════════════════════
# U1 用户可交易池
# ══════════════════════════════════════════════════════════════════════

# 配置: 是否排除科创板/创业板
# 会在 U1 过滤逻辑中使用，可通过环境变量覆盖
EXCLUDE_STAR = os.environ.get("UNIVERSE_EXCLUDE_STAR", "true").lower() in ("true", "1", "yes")
EXCLUDE_CHINEXT = os.environ.get("UNIVERSE_EXCLUDE_CHINEXT", "true").lower() in ("true", "1", "yes")


def _is_delisted_from_name(name: str) -> bool:
    """根据股票名称判断是否退市"""
    name = str(name).strip()
    return "退" in name


def _is_delisted(u0_stock: dict) -> bool:
    """判断股票是否已退市"""
    # is_listed 标志
    if not u0_stock.get("is_listed", True):
        return True
    # delist_date 非空
    delist_date = str(u0_stock.get("delist_date", "") or "")
    if delist_date and delist_date != "NaT" and delist_date != "nan" and delist_date.strip():
        return True
    return False


def build_u1() -> dict[str, Any]:
    """构建 U1 用户可交易池

    U1 是 U0 的严格子集，过滤规则:
      - 退市（is_listed=False 或 delist_date 非空）
      - name 含 "退"
      - ST/*ST（namechange 记录或名称前缀）
      - 停牌（suspend_d 当日停牌）
      - 北交所
      - 科创板（如 EXCLUDE_STAR=True）
      - 创业板（如 EXCLUDE_CHINEXT=True）

    扩展字段:
      - daily_basic: total_mv, float_mv, turnover_rate, amount, pe, pb
      - industry: 有数据填行业，无数据为 null + missing_reason
      - concepts: 空数组（行权限制，见 lineage）
    """
    u0 = build_u0()
    tc = _get_ts_client()
    stocks = u0["stocks"]

    # 获取最新交易日
    latest_trade_date = ""
    try:
        cal = tc.trade_cal(start_date="20260601", end_date=_now_str()[:10].replace("-", ""))
        if not cal.empty:
            open_days = cal[cal["is_open"] == 1].sort_values("cal_date")
            if not open_days.empty:
                latest_trade_date = open_days["cal_date"].iloc[-1].strftime("%Y%m%d")
    except Exception:
        pass

    # 1) suspend_d — 停牌
    suspended_set: set[str] = set()
    if latest_trade_date:
        try:
            suspend_df = tc._query("suspend_d", trade_date=latest_trade_date)
            if not suspend_df.empty and "ts_code" in suspend_df.columns:
                suspended_set = set(suspend_df["ts_code"].tolist())
        except Exception as e:
            logger.warning(f"suspend_d 查询失败: {e}")

    # 2) namechange — ST 判断（取最近一条）
    st_set: set[str] = set()
    try:
        namechange_df = tc._query(
            "namechange",
            start_date="20000101",
            end_date=_now_str()[:10].replace("-", ""),
        )
        if not namechange_df.empty and "ts_code" in namechange_df.columns:
            # 取每只股票最新的 namechange 记录
            namechange_df = namechange_df.sort_values("start_date")
            latest_per_code = namechange_df.groupby("ts_code").last().reset_index()
            for _, r in latest_per_code.iterrows():
                reason = str(r.get("change_reason", ""))
                if "ST" in reason or "st" in reason or "*ST" in reason:
                    st_set.add(r["ts_code"])
    except Exception as e:
        logger.warning(f"namechange 查询失败: {e}")

    # 3) daily_basic — 近 20 日均成交额 + 最新市值/换手率
    amount_20d_map: dict[str, float] = {}
    daily_basic_latest: dict[str, dict] = {}  # ts_code → {total_mv, float_mv, turnover_rate, amount}
    if latest_trade_date:
        try:
            # 起算日期前推40天确保有20个交易日
            dt = datetime.strptime(latest_trade_date, "%Y%m%d")
            past_40 = (dt - timedelta(days=40)).strftime("%Y%m%d")
            basic_df = tc._query(
                "daily_basic",
                start_date=past_40,
                end_date=latest_trade_date,
                fields="ts_code,trade_date,total_mv,circ_mv,turnover_rate,amount,pe,pb",
            )
            if not basic_df.empty and "ts_code" in basic_df.columns:
                basic_df["trade_date"] = pd.to_datetime(
                    basic_df["trade_date"], format="%Y%m%d", errors="coerce"
                )
                # 最新 trading day 数据
                latest_basic = basic_df[basic_df["trade_date"] == basic_df["trade_date"].max()]
                for _, row in latest_basic.iterrows():
                    tc_code = row["ts_code"]
                    daily_basic_latest[tc_code] = {
                        "total_mv": float(row["total_mv"]) if pd.notna(row.get("total_mv")) else None,
                        "float_mv": float(row["circ_mv"]) if pd.notna(row.get("circ_mv")) else None,
                        "turnover_rate": float(row["turnover_rate"]) if pd.notna(row.get("turnover_rate")) else None,
                        "amount": float(row["amount"]) if pd.notna(row.get("amount")) else None,
                        "pe": float(row["pe"]) if pd.notna(row.get("pe")) else None,
                        "pb": float(row["pb"]) if pd.notna(row.get("pb")) else None,
                    }

                # 近 20 日均成交额
                for ts_code in basic_df["ts_code"].unique():
                    sub = basic_df[basic_df["ts_code"] == ts_code].sort_values("trade_date")
                    if len(sub) > 20:
                        sub = sub.tail(20)
                    avg_amount = sub["amount"].mean()
                    amount_20d_map[ts_code] = float(avg_amount) if pd.notna(avg_amount) else 0.0
        except Exception as e:
            logger.warning(f"daily_basic 查询失败: {e}")

    # 4) 过滤 + 构建记录
    records: list[dict[str, Any]] = []
    filtered_counts: dict[str, int] = {
        "退市": 0,
        "名称含退": 0,
        "ST/ST标记": 0,
        "停牌": 0,
        "北交所": 0,
        "科创板(排除)": 0,
        "创业板(排除)": 0,
    }

    for s in stocks:
        ts_code = s["ts_code"]
        board = s.get("board", "")
        name = s.get("name", "")

        # 过滤条件
        skip = False
        block_reasons: list[str] = []

        # 退市
        if _is_delisted(s):
            block_reasons.append("退市")
            filtered_counts["退市"] += 1
            skip = True

        # name 含 "退"
        if _is_delisted_from_name(name):
            block_reasons.append("名称含退")
            filtered_counts["名称含退"] += 1
            skip = True

        # ST/*ST
        is_st = ts_code in st_set or _is_st_from_name(name)
        if is_st:
            block_reasons.append("ST/*ST标记")
            filtered_counts["ST/ST标记"] += 1
            skip = True

        # 停牌
        is_suspended = ts_code in suspended_set
        if is_suspended:
            block_reasons.append("停牌")
            filtered_counts["停牌"] += 1
            skip = True

        # 北交所
        is_bse = board == "北交所"
        if is_bse:
            block_reasons.append("北交所 (权限受限)")
            filtered_counts["北交所"] += 1
            skip = True

        # 科创板
        is_star = board == "科创板"
        if is_star and EXCLUDE_STAR:
            block_reasons.append("科创板 (权限受限)")
            filtered_counts["科创板(排除)"] += 1
            skip = True

        # 创业板
        is_chinext = board == "创业板"
        if is_chinext and EXCLUDE_CHINEXT:
            block_reasons.append("创业板 (权限受限)")
            filtered_counts["创业板(排除)"] += 1
            skip = True

        if skip:
            continue

        is_mainboard = board == "主板"

        avg_amount_20d = amount_20d_map.get(ts_code, 0.0)

        # industry 处理 — 不能是字符串 "nan"
        industry_raw = s.get("industry", "")
        if industry_raw and str(industry_raw).strip().lower() != "nan" and str(industry_raw).strip():
            industry_val = industry_raw
            industry_missing_reason = None
        else:
            industry_val = None
            industry_missing_reason = "Tushare stock_basic 未返回行业信息"

        # concepts — 暂无数据时返回空数组
        concepts_val = s.get("concepts", [])

        # daily_basic 扩展字段
        db = daily_basic_latest.get(ts_code, {})

        # tradable_by_user: 能通过过滤留在 U1 的就是可交易的
        tradable_by_user = True
        restriction_reason = ""

        records.append({
            "ts_code": ts_code,
            "symbol": s["symbol"],
            "name": name,
            "board": board,
            "is_mainboard": is_mainboard,
            "is_chinext": is_chinext,
            "is_star": is_star,
            "is_bse": is_bse,
            "is_st": is_st,
            "is_suspended": is_suspended,
            "tradable_by_user": tradable_by_user,
            "restriction_reason": restriction_reason,
            "industry": industry_val,
            "industry_missing_reason": industry_missing_reason,
            "concepts": concepts_val if concepts_val else [],
            "concepts_lineage": "concepts 从 U0 继承；若 U0 无 concepts 数据，此处为空数组",
            "total_mv": db.get("total_mv"),
            "float_mv": db.get("float_mv"),
            "turnover_rate": db.get("turnover_rate"),
            "amount": db.get("amount"),
            "pe": db.get("pe"),
            "pb": db.get("pb"),
            "avg_amount_20d": round(avg_amount_20d, 2),
        })

    return {
        "name": "U1",
        "label": "用户可交易池",
        "description": "U0 严格子集，过滤退市/ST/*ST/停牌/北交所/科创创业，补充市值/换手/行业",
        "built_at": _now_str(),
        "data_sources": [
            "U0", "Tushare suspend_d", "Tushare namechange",
            "Tushare daily_basic (total_mv, circ_mv, turnover_rate, amount, pe, pb)",
        ],
        "total_stocks": len(records),
        "filtered_counts": filtered_counts,
        "stocks": records,
    }


# ══════════════════════════════════════════════════════════════════════
# U2 AI/半导体广义池
# ══════════════════════════════════════════════════════════════════════

def build_u2() -> dict[str, Any]:
    """构建 U2 AI/半导体广义池

    数据来源: pool.csv (315 只) + ai_chainmap_watchlist_tags.csv
    字段:
        source_atlas, source_concept, source_etf_holding, source_industry,
        source_manual, source_confidence, ai_chain_layer, theme_tags,
        is_broad_ai_semiconductor
    """
    # 从 pool.csv 读取源数据
    pool_rows = _read_csv_safe(POOL_CSV)
    pool_codes: dict[str, dict] = {}
    for r in pool_rows:
        code = str(r.get("code", "")).strip()
        if code:
            tc = _symbol_to_ts_code(code)
            pool_codes[tc] = {
                "source_atlas": True,
                "atlas_sector": str(r.get("sector", "")).strip(),
            }

    # 从 ai_chainmap 读取标签数据
    chain_rows = _read_csv_safe(AI_CHAINMAP_CSV)
    chain_data: dict[str, dict] = {}
    for r in chain_rows:
        ts_code = str(r.get("ticker", "")).strip()
        if ts_code:
            chain_data[ts_code] = {
                "layer": str(r.get("layer", "")).strip(),
                "primary_type": str(r.get("primary_type", "")).strip(),
                "confidence": str(r.get("confidence", "")).strip(),
                "type_tags": str(r.get("type_tags", "")).strip(),
            }

    # 合并所有代码
    all_codes = set(pool_codes.keys()) | set(chain_data.keys())
    # 用 U0 验证是否存在 + 获取名称映射
    u0 = build_u0()
    u0_codes = {s["ts_code"] for s in u0["stocks"]}
    u0_names = {s["ts_code"]: s.get("name", "") for s in u0["stocks"]}

    # 构建记录
    records: list[dict[str, Any]] = []
    for ts_code in sorted(all_codes):
        if ts_code not in u0_codes:
            # pool.csv 和 chain 中的股票可能在已退市等情况，记录但标记
            pass

        symbol = _ts_code_to_symbol(ts_code)
        pool_info = pool_codes.get(ts_code, {})
        chain_info = chain_data.get(ts_code, {})

        # 主题标签
        theme_tags: list[str] = []
        if chain_info.get("type_tags"):
            tags = [t.strip() for t in chain_info["type_tags"].split("/")]
            theme_tags.extend(tags)
        if pool_info.get("atlas_sector"):
            theme_tags.append(pool_info["atlas_sector"])

        # 置信度
        confidence = chain_info.get("confidence", "low")
        if not confidence:
            confidence = "low" if pool_info.get("source_atlas") else "low"

        # 是否广义 AI/半导体
        is_broad = (
            pool_info.get("source_atlas", False)
            or bool(chain_info)
        )

        records.append({
            "ts_code": ts_code,
            "symbol": symbol,
            "name": u0_names.get(ts_code, ""),
            "source_atlas": pool_info.get("source_atlas", False),
            "source_concept": False,  # 暂不使用概念, 后续扩展
            "source_etf_holding": False,  # 暂不使用 ETF 持仓
            "source_industry": False,
            "source_manual": False,
            "source_confidence": confidence,
            "ai_chain_layer": chain_info.get("layer", ""),
            "primary_type": chain_info.get("primary_type", ""),
            "theme_tags": theme_tags,
            "is_broad_ai_semiconductor": is_broad,
        })

    return {
        "name": "U2",
        "label": "AI/半导体广义池",
        "description": "基于 pool.csv (315只) 和 ai_chainmap_watchlist_tags.csv 的广义 AI/半导体候选池",
        "built_at": _now_str(),
        "data_sources": ["pool.csv", "ai_chainmap_watchlist_tags.csv"],
        "total_stocks": len(records),
        "atlas_sourced_count": sum(1 for r in records if r["source_atlas"]),
        "chain_labelled_count": sum(1 for r in records if r.get("ai_chain_layer")),
        "stocks": records,
    }


# ══════════════════════════════════════════════════════════════════════
# U3 半导体核心池
# ══════════════════════════════════════════════════════════════════════

# 半导体细分方向关键词
SEMICONDUCTOR_SUBSECTOR_KEYWORDS: dict[str, list[str]] = {
    "设备": ["设备", "刻蚀", "薄膜", "清洗", "CMP", "涂胶", "显影", "离子注入", "检测设备", "分选机", "探针台"],
    "材料": ["材料", "硅片", "光刻胶", "电子特气", "靶材", "CMP抛光液", "掩模版", "封装基板"],
    "设计": ["设计", "IC设计", "芯片设计", "FPGA", "MCU", "DSP", "SOC", "AI芯片", "GPU", "NPU", "ASIC"],
    "制造": ["制造", "晶圆", "代工", "foundry", "IDM", "特色工艺"],
    "封测": ["封测", "封装", "测试", "OSAT", "先进封装", "SiP", "Chiplet", "3D封装", "TSV"],
    "EDA": ["EDA", "电子设计自动化", "IP授权"],
    "IP": ["IP", "ARM", "RISC-V", "芯原"],
    "存储": ["存储", "DRAM", "NAND", "Flash", "HBM", "SSD", "内存", "硬盘"],
    "功率": ["功率", "IGBT", "MOSFET", "SiC", "GaN", "三代半", "碳化硅", "氮化镓", "功率器件"],
    "PCB": ["PCB", "印制电路板", "HDI", "载板", "IC载板", "封装载板"],
    "CPO": ["CPO", "光互连", "硅光", "相干光学", "光模块", "光通信芯片"],
}

# 国产替代关键词
DOMESTIC_SUBSTITUTION_KEYWORDS = [
    "国产替代", "自主可控", "国产化", "替代", "自主",
    "实体清单", "制裁", "限制", "卡脖子", "突破",
]

# 供应链位置关键词
SUPPLY_CHAIN_POSITION_KEYWORDS: dict[str, list[str]] = {
    "上游": ["材料", "设备", "EDA", "IP", "硅片", "光刻胶", "电子特气", "靶材"],
    "中游": ["设计", "制造", "foundry", "IDM", "晶圆", "封测", "封装", "OSAT"],
    "下游": ["PCB", "模组", "整机", "系统", "应用"],
}


def _classify_semiconductor_subsector(
    name: str, industry: str, concepts: list[str], type_tags: str, primary_type: str
) -> list[str]:
    """根据股票名称+行业+概念+标签判断半导体细分方向"""
    text = f"{name} {industry} {' '.join(concepts)} {type_tags} {primary_type}"
    text_lower = text.lower()

    subsectors: list[str] = []
    for subsector, keywords in SEMICONDUCTOR_SUBSECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                subsectors.append(subsector)
                break

    if not subsectors:
        # 兜底: 行业含"半导体"或"电子"
        if "半导体" in text or "芯片" in text or "集成电路" in text:
            subsectors.append("设计")  # 默认归入设计
        elif "电子" in industry:
            # 电子行业但无明确细分
            pass

    return subsectors


def _compute_core_score(subsectors: list[str], chain_layer: str, confidence: str) -> float:
    """计算核心度评分 (0.0-1.0)"""
    score = 0.0
    if subsectors:
        score += 0.3  # 有明确细分方向
    if chain_layer and chain_layer.startswith("L") and len(chain_layer) > 1:
        try:
            layer_num = int(chain_layer[1:])
            if layer_num <= 2:
                score += 0.3  # L1/L2 更核心
            elif layer_num <= 4:
                score += 0.2
            else:
                score += 0.1
        except ValueError:
            pass
    if confidence == "high":
        score += 0.3
    elif confidence == "medium":
        score += 0.2
    elif confidence == "low":
        score += 0.1
    return min(score, 1.0)


def _compute_domestic_substitution_score(name: str, industry: str, concepts: list[str]) -> float:
    """计算国产替代评分 (0.0-1.0)"""
    text = f"{name} {industry} {' '.join(concepts)}"
    text_lower = text.lower()
    score = 0.0
    for kw in DOMESTIC_SUBSTITUTION_KEYWORDS:
        if kw.lower() in text_lower:
            score += 0.2
    return min(score, 1.0)


def _compute_supply_chain_position(
    subsectors: list[str],
    type_tags: str,
    primary_type: str,
) -> list[str]:
    """根据细分方向+标签推断供应链位置"""
    positions: list[str] = []
    text = f"{' '.join(subsectors)} {type_tags} {primary_type}"
    text_lower = text.lower()

    for position, keywords in SUPPLY_CHAIN_POSITION_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                positions.append(position)
                break

    if not positions:
        positions.append("中游")  # 默认中游

    return list(set(positions))  # 去重


def build_u3() -> dict[str, Any]:
    """构建 U3 半导体核心池

    从 U2 中筛选半导体核心标的，补充细分方向/核心度/国产替代/供应链位置
    """
    u2 = build_u2()
    u0 = build_u0()

    u0_map: dict[str, dict] = {s["ts_code"]: s for s in u0["stocks"]}

    # 从半导体链标签文件补充
    chain_rows = _read_csv_safe(SEMICONDUCTOR_CHAIN_CSV)
    semicon_chain_codes: set[str] = set()
    for r in chain_rows:
        code = str(r.get("code", "") or r.get("symbol", "") or r.get("ticker", "")).strip()
        if code:
            semicon_chain_codes.add(_symbol_to_ts_code(code))

    # 筛选核心标的: 来自 U2 + 有明确半导体特征
    core_stocks: list[dict[str, Any]] = []
    for s in u2["stocks"]:
        ts_code = s["ts_code"]
        u0_info = u0_map.get(ts_code, {})

        name = u0_info.get("name", "")
        industry = u0_info.get("industry", "")
        concepts = u0_info.get("concepts", [])
        type_tags = s.get("theme_tags", [])
        primary_type = s.get("primary_type", "")
        chain_layer = s.get("ai_chain_layer", "")

        # 判断是否为半导体核心
        is_in_semicon_chain = ts_code in semicon_chain_codes
        subsectors = _classify_semiconductor_subsector(
            name, industry, concepts,
            " ".join(type_tags) if isinstance(type_tags, list) else type_tags,
            primary_type,
        )
        is_semiconductor_relevant = (
            is_in_semicon_chain
            or bool(subsectors)
            or "半导体" in industry
            or "芯片" in str(concepts)
        )

        if not is_semiconductor_relevant:
            continue

        core_score = _compute_core_score(subsectors, chain_layer, s.get("source_confidence", "low"))
        domestic_score = _compute_domestic_substitution_score(name, industry, concepts)
        supply_positions = _compute_supply_chain_position(subsectors, " ".join(type_tags) if isinstance(type_tags, list) else type_tags, primary_type)

        core_stocks.append({
            "ts_code": ts_code,
            "symbol": s["symbol"],
            "name": name,
            "industry": industry,
            "semiconductor_subsector": subsectors,
            "core_score": round(core_score, 2),
            "domestic_substitution_score": round(domestic_score, 2),
            "supply_chain_position": supply_positions,
            "from_semiconductor_chain_tags": is_in_semicon_chain,
        })

    # 按核心度排序
    core_stocks.sort(key=lambda x: x["core_score"], reverse=True)

    return {
        "name": "U3",
        "label": "半导体核心池",
        "description": "从 U2 筛选的半导体核心标的，含细分方向/核心度/国产替代/供应链位置",
        "built_at": _now_str(),
        "data_sources": ["U2", "U0", "semiconductor_chain_tags.csv"],
        "total_stocks": len(core_stocks),
        "stocks": core_stocks,
    }


# ══════════════════════════════════════════════════════════════════════
# U4 匹配对照池
# ══════════════════════════════════════════════════════════════════════

def build_u4(min_matches: int = 2, max_matches: int = 5) -> dict[str, Any]:
    """构建 U4 匹配对照池

    对 U3 每只股票按 float_mv ±20%、avg_amount_20d ±30%、volatility_60d ±20% 匹配非半导体标的

    Args:
        min_matches: 每只 U3 股票最少匹配数
        max_matches: 每只 U3 股票最多匹配数
    """
    u3 = build_u3()
    u0 = build_u0()
    u1 = build_u1()

    u0_map: dict[str, dict] = {s["ts_code"]: s for s in u0["stocks"]}
    u1_map: dict[str, dict] = {s["ts_code"]: s for s in u1["stocks"]}
    u2 = build_u2()
    u2_codes = {s["ts_code"] for s in u2["stocks"]}
    u3_codes = {s["ts_code"] for s in u3["stocks"]}

    # 获取 full pool for matching — 排除 U2+U3 (半导体标的)
    candidate_pool: list[dict] = []
    for s in u0["stocks"]:
        ts_code = s["ts_code"]
        if ts_code in u2_codes or ts_code in u3_codes:
            continue
        candidate_pool.append(s)

    # 计算波动率 (60日)
    volatility_map: dict[str, float] = {}
    tc = _get_ts_client()
    try:
        # 用 daily 数据算 60 日波动率
        u3_codes_list = list(u3_codes)
        all_search_codes = list(set(list(u3_codes)[:50] + [cs["ts_code"] for cs in candidate_pool[:200]]))
        # 取最近 120 天数据
        today = _now_str()[:10].replace("-", "")
        dt = datetime.strptime(today, "%Y%m%d")
        past_120 = (dt - timedelta(days=120)).strftime("%Y%m%d")

        if all_search_codes:
            # 批次查询，每次最多 10 只
            for i in range(0, len(all_search_codes), 10):
                batch = all_search_codes[i : i + 10]
                for code in batch:
                    df = tc._query("daily", ts_code=code, start_date=past_120, end_date=today)
                    if not df.empty and "pct_chg" in df.columns:
                        # 取最近 60 个交易日
                        if len(df) > 60:
                            df = df.tail(60)
                        vol = df["pct_chg"].std()
                        volatility_map[code] = float(vol) if pd.notna(vol) else 0.0
    except Exception as e:
        logger.warning(f"波动率计算失败: {e}")

    # 构建匹配
    matches: list[dict] = []
    for u3_stock in u3["stocks"]:
        ts_code = u3_stock["ts_code"]
        u0_info = u0_map.get(ts_code, {})
        u1_info = u1_map.get(ts_code, {})

        # ── 市值：多源降级 ──────────────────────────────────────
        raw_float_mv = (
            u0_info.get("float_mv")
            or u0_info.get("circ_mv")
        )
        mv_source = "float_mv" if raw_float_mv is not None else None
        if raw_float_mv is None:
            raw_float_mv = u0_info.get("total_mv")
            mv_source = "total_mv_fallback" if raw_float_mv is not None else None

        # ── 成交额：多源降级 ──────────────────────────────────────
        target_avg_amount = (
            u0_info.get("avg_amount_20d")
            or u1_info.get("avg_amount_20d")
        )

        # ── 波动率 ────────────────────────────────────────────────
        target_volatility = volatility_map.get(ts_code)

        # ── 特征可用性判定 ────────────────────────────────────────
        matching_features: dict[str, float | None] = {
            "float_mv": raw_float_mv,
            "avg_amount_20d": target_avg_amount,
            "volatility": target_volatility,
        }
        available_features = {
            k: v for k, v in matching_features.items()
            if v is not None
        }
        missing_features = [
            k for k, v in matching_features.items()
            if v is None
        ]
        n_available = len(available_features)

        # ── 跳过条件 ──────────────────────────────────────────
        if n_available == 0:
            matches.append({
                "ts_code": ts_code,
                "symbol": u3_stock.get("symbol", ""),
                "name": u3_stock.get("name", ""),
                "matched": False,
                "match_quality": "failed",
                "match_count": 0,
                "matched_stocks": [],
                "missing_features": missing_features,
                "skip_reason": "insufficient_matching_features",
                "mv_source": mv_source or "",
            })
            continue

        if n_available == 1:
            matches.append({
                "ts_code": ts_code,
                "symbol": u3_stock.get("symbol", ""),
                "name": u3_stock.get("name", ""),
                "matched": False,
                "match_quality": "failed",
                "match_count": 0,
                "matched_stocks": [],
                "missing_features": missing_features,
                "skip_reason": "insufficient_matching_features",
                "mv_source": mv_source or "",
            })
            continue

        # ── 有 ≥2 个可用特征 → 执行匹配 ──────────────────────────
        target_float_mv = available_features.get("float_mv", 0) or 0
        target_avg_amount_final = available_features.get("avg_amount_20d", 0) or 0
        target_volatility_final = available_features.get("volatility", 0) or 0

        float_mv_low = target_float_mv * 0.80
        float_mv_high = target_float_mv * 1.20
        amount_low = target_avg_amount_final * 0.70
        amount_high = target_avg_amount_final * 1.30
        vol_low = target_volatility_final * 0.80 if target_volatility_final > 0 else 0
        vol_high = target_volatility_final * 1.20 if target_volatility_final > 0 else float("inf")

        matched: list[dict] = []
        for cand in candidate_pool:
            if len(matched) >= max_matches:
                break
            cand_code = cand["ts_code"]

            # 候选 stock 的对应字段
            cand_float_mv_raw = cand.get("float_mv") or cand.get("circ_mv") or cand.get("total_mv") or 0
            cand_u1 = u1_map.get(cand_code, {})
            cand_avg_amount_final = (
                cand.get("avg_amount_20d")
                or cand_u1.get("avg_amount_20d")
                or 0
            )
            cand_volatility = volatility_map.get(cand_code) or 0

            # 市值条件
            if cand_float_mv_raw < float_mv_low or cand_float_mv_raw > float_mv_high:
                continue

            # 成交额条件（仅当双方都有该特征）
            if "avg_amount_20d" in available_features:
                if cand_avg_amount_final < amount_low or cand_avg_amount_final > amount_high:
                    continue

            # 波动率条件（仅当双方都有该特征）
            if "volatility" in available_features:
                if cand_volatility:
                    if cand_volatility < vol_low or cand_volatility > vol_high:
                        continue

            matched.append({
                "ts_code": cand_code,
                "symbol": cand.get("symbol", ""),
                "name": cand.get("name", ""),
                "industry": cand.get("industry", ""),
                "board": cand.get("board", ""),
                "float_mv": round(cand_float_mv_raw, 2) if cand_float_mv_raw else 0,
                "avg_amount_20d": round(cand_avg_amount_final, 2) if cand_avg_amount_final else 0,
                "volatility_60d": round(cand_volatility, 4) if cand_volatility else 0,
            })

        matches.append({
            "ts_code": ts_code,
            "symbol": u3_stock.get("symbol", ""),
            "name": u3_stock.get("name", ""),
            "matched": len(matched) > 0,
            "match_quality": "degraded" if missing_features else "normal",
            "match_count": len(matched),
            "matched_stocks": matched,
            "missing_features": missing_features,
            "skip_reason": "" if matched else "未找到符合匹配条件的非半导体标的",
            "mv_source": mv_source or "",
        })

    return {
        "name": "U4",
        "label": "匹配对照池",
        "description": "对 U3 每只股票按大/中/小三种风格匹配非半导体对照标的",
        "built_at": _now_str(),
        "data_sources": ["U3", "U0", "U1", "Tushare daily"],
        "total_stocks": len(matches),
        "matched_total": sum(m["match_count"] for m in matches),
        "stocks": matches,
    }


# ══════════════════════════════════════════════════════════════════════
# ETF 替代池
# ══════════════════════════════════════════════════════════════════════

def build_etf_pool() -> dict[str, Any]:
    """构建 ETF 替代池

    返回硬编码的半导体/AI 相关 ETF 清单，可通过 Tushare fund_daily 补充实时数据
    """
    records: list[dict[str, Any]] = []
    for etf in ETF_REPLACEMENT_POOL:
        records.append({
            "ts_code": etf["ts_code"],
            "name": etf["name"],
            "fund_type": etf["fund_type"],
            "management_fee_pct": etf["mgmt_fee"],
            "track_index": etf["track_index"],
        })

    # 去重 (有的 ts_code 重复)
    seen: set[str] = set()
    unique_records: list[dict] = []
    for r in records:
        if r["ts_code"] not in seen:
            seen.add(r["ts_code"])
            unique_records.append(r)

    return {
        "name": "ETF",
        "label": "ETF替代池",
        "description": "半导体/AI 主题相关 ETF，用于无法直接买入科创/创业板个股时的替代",
        "built_at": _now_str(),
        "data_sources": ["手动维护", "Tushare fund_daily (可选扩展)"],
        "total_stocks": len(unique_records),
        "stocks": unique_records,
    }


# ══════════════════════════════════════════════════════════════════════
# 统一构建与导出
# ══════════════════════════════════════════════════════════════════════

BUILDERS = {
    "U0": build_u0,
    "U1": build_u1,
    "U2": build_u2,
    "U3": build_u3,
    "U4": build_u4,
    "ETF": build_etf_pool,
}


def build_all() -> dict[str, Any]:
    """构建所有分层股票池，写入 data/universes.json"""
    result: dict[str, Any] = {
        "meta": {
            "version": "4.1",
            "built_at": _now_str(),
            "description": "V4.1 分层股票池 U0-U4 + ETF替代池",
        },
        "universes": {},
    }
    for name, builder in BUILDERS.items():
        logger.info(f"构建 {name}...")
        try:
            universe = builder()
            result["universes"][name] = universe
            logger.info(f"  {name}: {universe.get('total_stocks', 0)} 只股票")
        except Exception as e:
            logger.error(f"构建 {name} 失败: {e}")
            result["universes"][name] = {
                "name": name,
                "error": str(e),
                "built_at": _now_str(),
                "stocks": [],
            }

    # 写入文件
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ 所有股票池已写入 {OUTPUT_FILE}")
    return result


def get_universe(name: str) -> dict[str, Any]:
    """返回指定股票池的 dict"""
    if not OUTPUT_FILE.exists():
        build_all()
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    universe = data.get("universes", {}).get(name)
    if not universe:
        raise KeyError(f"未找到股票池: {name}, 可选: {list(data.get('universes', {}).keys())}")
    return universe


def list_universes() -> list[str]:
    """返回所有股票池名称"""
    if not OUTPUT_FILE.exists():
        build_all()
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("universes", {}).keys())


def audit() -> dict[str, Any]:
    """审计所有股票池

    输出: 纯度、覆盖率、权限、流动性、风险标签
    """
    if not OUTPUT_FILE.exists():
        build_all()
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    report: dict[str, Any] = {
        "audited_at": _now_str(),
        "summary": {},
        "details": {},
    }

    for name, universe in data.get("universes", {}).items():
        stocks = universe.get("stocks", [])
        total = universe.get("total_stocks", len(stocks))
        detail: dict[str, Any] = {
            "total": total,
            "label": universe.get("label", ""),
        }

        if name == "U0":
            boards: dict[str, int] = {}
            industries: dict[str, int] = {}
            for s in stocks:
                b = s.get("board", "未知")
                boards[b] = boards.get(b, 0) + 1
                ind = s.get("industry", "未知")
                industries[ind] = industries.get(ind, 0) + 1
            detail["board_distribution"] = boards
            detail["top_industries"] = dict(sorted(industries.items(), key=lambda x: -x[1])[:10])

        elif name == "U1":
            tradable = sum(1 for s in stocks if s.get("tradable_by_user"))
            st_count = sum(1 for s in stocks if s.get("is_st"))
            suspended_count = sum(1 for s in stocks if s.get("is_suspended"))
            limit_up_count = sum(1 for s in stocks if s.get("is_limit_up"))
            detail["tradable_count"] = tradable
            detail["tradable_pct"] = round(tradable / total * 100, 2) if total else 0
            detail["st_count"] = st_count
            detail["suspended_count"] = suspended_count
            detail["limit_up_count"] = limit_up_count

        elif name == "U2":
            atlas_count = sum(1 for s in stocks if s.get("source_atlas"))
            high_conf = sum(1 for s in stocks if s.get("source_confidence") == "high")
            detail["atlas_sourced"] = atlas_count
            detail["high_confidence"] = high_conf
            detail["broad_ai_semiconductor_count"] = sum(
                1 for s in stocks if s.get("is_broad_ai_semiconductor")
            )

        elif name == "U3":
            detail["avg_core_score"] = round(
                sum(s.get("core_score", 0) for s in stocks) / total, 2
            ) if total else 0
            subsector_dist: dict[str, int] = {}
            for s in stocks:
                for sub in s.get("semiconductor_subsector", []):
                    subsector_dist[sub] = subsector_dist.get(sub, 0) + 1
            detail["subsector_distribution"] = dict(
                sorted(subsector_dist.items(), key=lambda x: -x[1])
            )

        elif name == "U4":
            detail["matched_total"] = universe.get("matched_total", 0)
            detail["avg_matches_per_stock"] = round(
                universe.get("matched_total", 0) / total, 2
            ) if total else 0
            failed = sum(1 for s in stocks if s.get("match_fail_reason"))
            detail["match_fail_count"] = failed

        elif name == "ETF":
            detail["etf_count"] = total

        report["details"][name] = detail

    # 汇总
    report["summary"] = {
        "total_universes": len(data.get("universes", {})),
        "total_stocks_all": sum(
            u.get("total_stocks", 0) for u in data.get("universes", {}).values()
        ),
        "version": data.get("meta", {}).get("version", ""),
    }

    return report


# ══════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════

def cmd_build():
    """hermes_cli.py universe:build"""
    result = build_all()
    print(f"✅ 所有股票池已构建")
    for name, universe in result.get("universes", {}).items():
        total = universe.get("total_stocks", 0)
        print(f"  {name} ({universe.get('label', '')}): {total} 只股票")
    print(f"\n📁 输出文件: {OUTPUT_FILE}")


def cmd_list():
    """hermes_cli.py universe:list"""
    names = list_universes()
    print(f"股票池列表 ({len(names)} 个):")
    for n in names:
        print(f"  - {n}")


def cmd_show(universe_name: str):
    """hermes_cli.py universe:show <name>"""
    try:
        universe = get_universe(universe_name)
    except KeyError as e:
        print(f"❌ {e}")
        return

    print(f"\n📊 {universe.get('name')} - {universe.get('label')}")
    print(f"   描述: {universe.get('description', '')}")
    print(f"   构建时间: {universe.get('built_at', '')}")
    print(f"   数据来源: {', '.join(universe.get('data_sources', []))}")
    print(f"   股票数量: {universe.get('total_stocks', 0)}")
    stocks = universe.get("stocks", [])

    if universe_name == "U1":
        tradable = universe.get("tradable_count", 0)
        print(f"   可交易数量: {tradable}")

    if universe_name == "U4":
        matched = universe.get("matched_total", 0)
        print(f"   匹配总数: {matched}")

    # 显示前 20 只
    if stocks:
        print(f"\n  前 20 只股票:")
        for s in stocks[:20]:
            if universe_name == "U3":
                print(f"    {s.get('ts_code', '')} {s.get('name', '')} "
                      f"core={s.get('core_score', '')} subsector={s.get('semiconductor_subsector', [])}")
            elif universe_name == "U4":
                print(f"    {s.get('u3_name', '')} ({s.get('u3_ts_code', '')}) → "
                      f"{s.get('match_count', 0)} matched")
                for m in s.get("matched_stocks", [])[:3]:
                    print(f"      - {m.get('name', '')} ({m.get('ts_code', '')}) {m.get('industry', '')}")
            elif universe_name == "ETF":
                print(f"    {s.get('ts_code', '')} {s.get('name', '')} "
                      f"费率={s.get('management_fee_pct', '')}% 跟踪={s.get('track_index', '')}")
            else:
                print(f"    {s.get('ts_code', '')} {s.get('name', '')} "
                      f"{s.get('board', '')} {s.get('industry', '')}")

        if len(stocks) > 20:
            print(f"   ... 还有 {len(stocks) - 20} 只")


def cmd_audit():
    """hermes_cli.py universe:audit"""
    report = audit()
    print(f"\n🔍 股票池审计报告")
    print(f"   审计时间: {report['audited_at']}")
    print(f"   版本: {report['summary'].get('version', '')}")
    print(f"   总池数: {report['summary'].get('total_universes', 0)}")
    print(f"   总股票数 (含重复): {report['summary'].get('total_stocks_all', 0)}")
    print()

    for name, detail in report["details"].items():
        print(f"  {name} - {detail.get('label', detail.get('name', ''))}:")
        print(f"    总量: {detail.get('total', 0)}")
        if name == "U0":
            print(f"    板块分布: {detail.get('board_distribution', {})}")
            top_ind = detail.get("top_industries", {})
            if top_ind:
                print(f"    前 5 行业: {dict(list(top_ind.items())[:5])}")
        elif name == "U1":
            print(f"    可交易数: {detail.get('tradable_count', 0)} ({detail.get('tradable_pct', 0)}%)")
            print(f"    ST: {detail.get('st_count', 0)}, 停牌: {detail.get('suspended_count', 0)}, 涨停: {detail.get('limit_up_count', 0)}")
        elif name == "U2":
            print(f"    atlas来源: {detail.get('atlas_sourced', 0)}, 高置信度: {detail.get('high_confidence', 0)}")
            print(f"    广义AI/半导体: {detail.get('broad_ai_semiconductor_count', 0)}")
        elif name == "U3":
            print(f"    平均核心度: {detail.get('avg_core_score', 0)}")
            print(f"    细分方向: {detail.get('subsector_distribution', {})}")
        elif name == "U4":
            print(f"    匹配总数: {detail.get('matched_total', 0)}, 平均匹配: {detail.get('avg_matches_per_stock', 0)}")
            print(f"    匹配失败: {detail.get('match_fail_count', 0)}")
        elif name == "ETF":
            print(f"    ETF数量: {detail.get('etf_count', 0)}")
        print()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: universes.py <build|list|show|audit> [name]")
        sys.exit(1)
    action = sys.argv[1]
    if action == "build":
        cmd_build()
    elif action == "list":
        cmd_list()
    elif action == "show":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        cmd_show(name)
    elif action == "audit":
        cmd_audit()
    else:
        print(f"未知命令: {action}")
