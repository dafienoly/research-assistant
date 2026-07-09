#!/usr/bin/env python3
"""
V4.10 事件与研报语义增强 — 半导体事件因子引擎

SemiconductorEventEngine:
  从多源 (Tushare + 本地CSV) 获取半导体产业链事件数据，
  构建标准化 Event 记录，统计事件频率，生成事件驱动因子。

事件类型:
  订单/中标, 扩产/投资, 定增, 回购, 减持,
  业绩预告, 业绩快报, 资产重组, 监管函,
  大基金入股, 国产替代突破, 客户认证

使用方式:
  from factor_lab.semiconductor_events import SemiconductorEventEngine

  engine = SemiconductorEventEngine()
  events = engine.load_all_events()
  factors = engine.compute_event_factors(events)
  report = engine.generate_factor_report(factors)

数据源:
  - data/events/policy_events.csv (政策事件)
  - data/events/preopen_events.csv (盘前事件)
  - Tushare: forecast (业绩预告), stk_holdertrade (增减持),
    repurchase (回购), share_float (解禁), dividend (分红)
  - Tushare: trade_cal (交易日历)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.data.tushare_client import get_ts_client

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ─── 路径 ────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # commands/
PROJECT_ROOT = BASE.parent  # research-assistant/
DATA_DIR = PROJECT_ROOT / "data"

# ─── 事件类型定义 ────────────────────────────────────────────────────────

EVENT_TYPES = {
    # 经营事件 (positive / negative)
    "订单": {"direction_candidates": ["positive", "neutral"]},
    "中标": {"direction_candidates": ["positive"]},
    "扩产": {"direction_candidates": ["positive", "neutral"]},
    "定增": {"direction_candidates": ["neutral", "positive", "negative"]},
    "回购": {"direction_candidates": ["positive"]},
    "减持": {"direction_candidates": ["negative"]},
    "业绩预告": {"direction_candidates": ["positive", "negative", "neutral"]},
    "业绩快报": {"direction_candidates": ["positive", "negative", "neutral"]},
    "资产重组": {"direction_candidates": ["neutral", "positive", "negative"]},
    "监管函": {"direction_candidates": ["negative"]},
    "大基金入股": {"direction_candidates": ["positive"]},
    "国产替代突破": {"direction_candidates": ["positive"]},
    "客户认证": {"direction_candidates": ["positive"]},
    "限售解禁": {"direction_candidates": ["negative", "neutral"]},
    "分红": {"direction_candidates": ["neutral", "positive"]},
}

VALID_EVENT_TYPES = set(EVENT_TYPES.keys())

# 事件类型 → 大类分组
EVENT_CATEGORY_MAP: dict[str, str] = {
    "订单": "经营",
    "中标": "经营",
    "扩产": "投资",
    "定增": "融资",
    "回购": "公司行为",
    "减持": "股东行为",
    "业绩预告": "业绩",
    "业绩快报": "业绩",
    "资产重组": "资本运作",
    "监管函": "合规",
    "大基金入股": "政策",
    "国产替代突破": "产业趋势",
    "客户认证": "经营",
    "限售解禁": "公司行为",
    "分红": "公司行为",
}

# Tushare code → event type mapping
TUSHARE_EVENT_SOURCE = "tushare"

# ─── 股票代码映射缓存 ─────────────────────────────────────────────────
_symbol_to_ts_code: dict[str, str] = {}
_ts_code_to_symbol: dict[str, str] = {}


def _load_symbol_map():
    """从 Tushare stock_basic 加载 symbol ↔ ts_code 映射"""
    if _symbol_to_ts_code:
        return
    try:
        tc = get_ts_client()
        df = tc.stock_basic()
        if not df.empty:
            for _, row in df.iterrows():
                ts = str(row.get("ts_code", "")).strip()
                if ts:
                    sym = ts.split(".")[0]  # "688012.SH" → "688012"
                    _symbol_to_ts_code[sym] = ts
                    _ts_code_to_symbol[ts] = sym
    except Exception as e:
        logger.warning(f"加载股票代码映射失败: {e}")


def symbol_to_ts_code(symbol: str) -> str:
    """6位数字代码 → Tushare ts_code (如 688012 → 688012.SH)"""
    if not _symbol_to_ts_code:
        _load_symbol_map()
    symbol = symbol.strip().split(".")[0]
    if symbol in _symbol_to_ts_code:
        return _symbol_to_ts_code[symbol]
    # 猜测: 688/689 → SH, 000/001/002/300/301 → SZ, 8 → BJ
    if symbol.startswith("6"):
        return f"{symbol}.SH"
    elif symbol.startswith("8") or symbol.startswith("4"):
        return f"{symbol}.BJ"
    else:
        return f"{symbol}.SZ"


def ts_code_to_symbol(ts_code: str) -> str:
    """Tushare ts_code → 6位数字代码"""
    return ts_code.split(".")[0]


# ─── 数据类 ───────────────────────────────────────────────────────────────


@dataclass
class EventRecord:
    """标准化事件记录"""
    event_date: str            # YYYY-MM-DD
    ts_code: str               # 股票代码 (Tushare 格式)
    event_type: str            # 事件类型 (见 EVENT_TYPES)
    event_direction: str       # positive / negative / neutral
    event_strength: int        # 1-5 强度评分
    event_source: str          # 来源 (announcement / tushare / csv)
    title: str = ""            # 事件标题
    detail: str = ""           # 事件详情
    source_ref: str = ""       # 原始证据路径/引用

    def to_dict(self) -> dict:
        return asdict(self)


# ─── 事件引擎 ─────────────────────────────────────────────────────────────


class SemiconductorEventEngine:
    """半导体事件因子引擎

    支持:
      - 从多数据源加载事件
      - 事件标准化 (方向/强度推断)
      - 事件频率统计 (近N日)
      - 事件后N日收益计算
      - 同池等权验证
    """

    def __init__(self, universe_codes: Optional[list[str]] = None):
        """
        Args:
            universe_codes: U3 半导体核心池 6位数字代码列表 (默认自动加载)
        """
        self._universe_codes = universe_codes
        self._trade_cal: Optional[pd.DataFrame] = None
        # 确保代码映射已加载
        _load_symbol_map()

    # ─── 半导体池 ─────────────────────────────────────────────────

    def _get_universe_codes(self) -> list[str]:
        """获取 U3 半导体核心池股票代码 (6位数字)"""
        if self._universe_codes:
            return self._universe_codes
        try:
            # 从 universes.json 读取 U3
            from benchmarks_v4 import _get_universe_codes as _b4_codes
            return _b4_codes("U3")
        except Exception as e:
            logger.warning(f"从 universes.json 获取 U3 失败: {e}")
            # 回退: 从 semiconductor_chain_tags.csv 读取
            csv_path = DATA_DIR / "tags" / "semiconductor_chain_tags.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                codes = df["code"].astype(str).str.strip().tolist()
                logger.info(f"从 semiconductor_chain_tags.csv 读取 {len(codes)} 只半导体标的")
                return codes
            logger.warning("无可用半导体池, 返回空列表")
            return []

    # ─── 交易日历 ─────────────────────────────────────────────────

    def _load_trade_cal(self) -> pd.DataFrame:
        """加载交易日历

        Returns:
            DataFrame: date (datetime), is_open (bool)
        """
        if self._trade_cal is not None:
            return self._trade_cal

        try:
            tc = get_ts_client()
            df = tc.trade_cal(start_date="20200101", end_date="20261231")
            if not df.empty:
                df["date"] = pd.to_datetime(df["cal_date"], format="%Y%m%d", errors="coerce")
                self._trade_cal = df[["date", "is_open"]].sort_values("date").reset_index(drop=True)
                return self._trade_cal
        except Exception as e:
            logger.warning(f"加载交易日历失败: {e}")

        # 回退: 本地缓存
        cal_path = DATA_DIR / "cache" / "tushare" / "trade_cal.parquet"
        if cal_path.exists():
            self._trade_cal = pd.read_parquet(cal_path)
            return self._trade_cal

        # 兜底: 识别所有K线文件中的日期作为交易日
        logger.warning("无交易日历, 使用全部自然日")
        dates = pd.date_range("2020-01-01", "2026-12-31", freq="D")
        self._trade_cal = pd.DataFrame({"date": dates, "is_open": 1})
        return self._trade_cal

    def _get_trading_days(self) -> pd.Series:
        """获取交易日序列 (sorted DatetimeIndex)"""
        cal = self._load_trade_cal()
        trading = cal[cal["is_open"] == 1]["date"].sort_values()
        return trading

    def _find_next_trading_day(self, date_str: str) -> Optional[str]:
        """将事件日期映射到最近交易日 (向后, 含当天)

        Args:
            date_str: YYYY-MM-DD or YYYYMMDD

        Returns:
            YYYY-MM-DD 格式的交易日, 或 None
        """
        trading_days = self._get_trading_days()

        if len(date_str) == 8:
            dt = pd.to_datetime(date_str, format="%Y%m%d", errors="coerce")
        else:
            dt = pd.to_datetime(date_str, errors="coerce")

        if pd.isna(dt):
            return None

        # 如果当天是交易日则用当天, 否则用下一个交易日
        mask = trading_days >= dt
        if mask.any():
            next_day = trading_days[mask].iloc[0]
            return next_day.strftime("%Y-%m-%d")
        return None

    # ─── 从 Tushare 拉取事件 ─────────────────────────────────────

    def _fetch_forecast_events(self, start_date: str = "20250101",
                               end_date: str = "") -> list[EventRecord]:
        """从 Tushare forecast 获取业绩预告/业绩快报事件"""
        records: list[EventRecord] = []
        try:
            tc = get_ts_client()
            codes = self._get_universe_codes()
            ts_codes = [symbol_to_ts_code(c) for c in codes]

            for batch_start in range(0, len(ts_codes), 10):
                batch = ts_codes[batch_start:batch_start + 10]
                for ts_code in batch:
                    try:
                        df = tc._query("forecast", ts_code=ts_code,
                                       start_date=start_date,
                                       end_date=end_date)
                        if df is None or df.empty:
                            continue
                        cols = df.columns.tolist()
                        # forecast 包含: ts_code, ann_date, end_date, type, p_change_min, p_change_max, ...
                        date_col = "ann_date" if "ann_date" in cols else "end_date"
                        for _, row in df.iterrows():
                            ann = str(row.get(date_col, "")).strip()
                            if not ann or ann == "nan":
                                continue
                            event_date = self._find_next_trading_day(ann)
                            if event_date is None:
                                continue

                            f_type = str(row.get("type", ""))
                            # type: 1=预增, 2=预减, 3=略增, 4=略减, 5=续盈, 6=续亏, 7=首亏, 8=扭亏
                            positive_types = {"1", "3", "5", "8"}
                            negative_types = {"2", "4", "6", "7"}
                            if f_type in positive_types:
                                direction = "positive"
                                strength = 3
                            elif f_type in negative_types:
                                direction = "negative"
                                strength = 3
                            else:
                                direction = "neutral"
                                strength = 2

                            # 推断是业绩预告还是业绩快报
                            event_type = "业绩预告"
                            if "f_ann_date" in cols or "f_type" in cols:
                                event_type = "业绩快报"

                            records.append(EventRecord(
                                event_date=event_date,
                                ts_code=ts_code,
                                event_type=event_type,
                                event_direction=direction,
                                event_strength=strength,
                                event_source=TUSHARE_EVENT_SOURCE,
                                title=f"业绩{f_type}",
                                detail=str(row.to_dict()),
                                source_ref=f"tushare.forecast.{ts_code}.{ann}",
                            ))
                    except Exception as e:
                        logger.debug(f"forecast {ts_code} 失败: {e}")
                        continue
            logger.info(f"从 Tushare forecast 获取 {len(records)} 条事件")
        except Exception as e:
            logger.warning(f"forecast 批量拉取失败: {e}")
        return records

    def _fetch_holdertrade_events(self, start_date: str = "20250101",
                                  end_date: str = "") -> list[EventRecord]:
        """从 Tushare stk_holdertrade 获取增减持事件"""
        records: list[EventRecord] = []
        try:
            from commands.data_providers.tushare import TushareEventProvider
            provider = TushareEventProvider()
            codes = self._get_universe_codes()
            ts_codes = [symbol_to_ts_code(c) for c in codes]

            for batch_start in range(0, len(ts_codes), 10):
                batch = ts_codes[batch_start:batch_start + 10]
                for ts_code in batch:
                    try:
                        df = provider.stk_holdertrade(
                            ts_code=ts_code,
                            start_date=start_date,
                            end_date=end_date or datetime.now(CST).strftime("%Y%m%d"),
                        )
                        if df.empty:
                            continue
                        for _, row in df.iterrows():
                            change_date = row.get("change_date")
                            if pd.isna(change_date):
                                continue
                            event_date = self._find_next_trading_day(
                                change_date.strftime("%Y%m%d")
                            )
                            if event_date is None:
                                continue

                            # trade_type: 0=减持, 1=增持
                            trade_type = str(row.get("trade_type", "0"))
                            vol = float(row.get("vol", 0) or 0)
                            is_reduce = (trade_type == "0")
                            is_large = abs(vol) > 1000000  # > 100万股

                            direction = "negative" if is_reduce else "positive"
                            strength = 4 if is_large else 2
                            event_type = "减持" if is_reduce else "回购"  # 增持归入回购类

                            records.append(EventRecord(
                                event_date=event_date,
                                ts_code=ts_code,
                                event_type=event_type,
                                event_direction=direction,
                                event_strength=strength,
                                event_source=TUSHARE_EVENT_SOURCE,
                                title=f"{'减持' if is_reduce else '增持'} {abs(vol):.0f}股",
                                detail=str(row.to_dict()),
                                source_ref=f"tushare.stk_holdertrade.{ts_code}",
                            ))
                    except Exception as e:
                        logger.debug(f"stk_holdertrade {ts_code} 失败: {e}")
                        continue
            logger.info(f"从 Tushare stk_holdertrade 获取 {len(records)} 条事件")
        except Exception as e:
            logger.warning(f"stk_holdertrade 批量拉取失败: {e}")
        return records

    def _fetch_repurchase_events(self, start_date: str = "20250101") -> list[EventRecord]:
        """从 Tushare repurchase 获取回购事件"""
        records: list[EventRecord] = []
        try:
            from commands.data_providers.tushare import TushareEventProvider
            provider = TushareEventProvider()
            codes = self._get_universe_codes()
            ts_codes = [symbol_to_ts_code(c) for c in codes]

            for batch_start in range(0, len(ts_codes), 10):
                batch = ts_codes[batch_start:batch_start + 10]
                for ts_code in batch:
                    try:
                        df = provider.repurchase(ts_code=ts_code, ann_date=start_date)
                        if df.empty:
                            continue
                        for _, row in df.iterrows():
                            ann_date = row.get("ann_date")
                            if pd.isna(ann_date):
                                continue
                            event_date = self._find_next_trading_day(
                                ann_date.strftime("%Y%m%d")
                            )
                            if event_date is None:
                                continue

                            amount = float(row.get("amount", 0) or 0)
                            strength = 3 if amount > 50000000 else 2  # 5000万以上强

                            records.append(EventRecord(
                                event_date=event_date,
                                ts_code=ts_code,
                                event_type="回购",
                                event_direction="positive",
                                event_strength=strength,
                                event_source=TUSHARE_EVENT_SOURCE,
                                title=f"回购 {amount:.0f}元",
                                detail=str(row.to_dict()),
                                source_ref=f"tushare.repurchase.{ts_code}",
                            ))
                    except Exception as e:
                        logger.debug(f"repurchase {ts_code} 失败: {e}")
                        continue
            logger.info(f"从 Tushare repurchase 获取 {len(records)} 条事件")
        except Exception as e:
            logger.warning(f"repurchase 批量拉取失败: {e}")
        return records

    def _fetch_share_float_events(self, start_date: str = "20250101",
                                  end_date: str = "") -> list[EventRecord]:
        """从 Tushare share_float 获取限售解禁事件"""
        records: list[EventRecord] = []
        try:
            from commands.data_providers.tushare import TushareEventProvider
            provider = TushareEventProvider()
            codes = self._get_universe_codes()
            ts_codes = [symbol_to_ts_code(c) for c in codes]

            for batch_start in range(0, len(ts_codes), 10):
                batch = ts_codes[batch_start:batch_start + 10]
                for ts_code in batch:
                    try:
                        df = provider.share_float(
                            ts_code=ts_code,
                            start_date=start_date,
                            end_date=end_date or datetime.now(CST).strftime("%Y%m%d"),
                        )
                        if df.empty:
                            continue
                        for _, row in df.iterrows():
                            float_date = row.get("float_date")
                            if pd.isna(float_date):
                                continue
                            event_date = self._find_next_trading_day(
                                float_date.strftime("%Y%m%d")
                            )
                            if event_date is None:
                                continue

                            ratio = float(row.get("ratio", 0) or 0)
                            strength = 4 if ratio > 10 else (3 if ratio > 5 else 2)

                            records.append(EventRecord(
                                event_date=event_date,
                                ts_code=ts_code,
                                event_type="限售解禁",
                                event_direction="negative",
                                event_strength=strength,
                                event_source=TUSHARE_EVENT_SOURCE,
                                title=f"解禁 {ratio:.1f}%",
                                detail=str(row.to_dict()),
                                source_ref=f"tushare.share_float.{ts_code}",
                            ))
                    except Exception as e:
                        logger.debug(f"share_float {ts_code} 失败: {e}")
                        continue
            logger.info(f"从 Tushare share_float 获取 {len(records)} 条事件")
        except Exception as e:
            logger.warning(f"share_float 批量拉取失败: {e}")
        return records

    def _fetch_dividend_events(self, start_date: str = "20250101",
                               end_date: str = "") -> list[EventRecord]:
        """从 Tushare dividend 获取分红事件"""
        records: list[EventRecord] = []
        try:
            from commands.data_providers.tushare import TushareEventProvider
            provider = TushareEventProvider()
            codes = self._get_universe_codes()
            ts_codes = [symbol_to_ts_code(c) for c in codes]

            for batch_start in range(0, len(ts_codes), 10):
                batch = ts_codes[batch_start:batch_start + 10]
                for ts_code in batch:
                    try:
                        df = provider.dividend(
                            ts_code=ts_code,
                            start_date=start_date,
                            end_date=end_date or datetime.now(CST).strftime("%Y%m%d"),
                        )
                        if df.empty:
                            continue
                        for _, row in df.iterrows():
                            ann_date = row.get("ann_date")
                            if pd.isna(ann_date):
                                continue
                            event_date = self._find_next_trading_day(
                                ann_date.strftime("%Y%m%d")
                            )
                            if event_date is None:
                                continue

                            cash_div = float(row.get("cash_div", 0) or 0)
                            strength = 3 if cash_div > 1 else 2  # 每股派现>1元

                            records.append(EventRecord(
                                event_date=event_date,
                                ts_code=ts_code,
                                event_type="分红",
                                event_direction="positive" if cash_div > 0 else "neutral",
                                event_strength=strength,
                                event_source=TUSHARE_EVENT_SOURCE,
                                title=f"分红 {cash_div:.2f}元/股",
                                detail=str(row.to_dict()),
                                source_ref=f"tushare.dividend.{ts_code}",
                            ))
                    except Exception as e:
                        logger.debug(f"dividend {ts_code} 失败: {e}")
                        continue
            logger.info(f"从 Tushare dividend 获取 {len(records)} 条事件")
        except Exception as e:
            logger.warning(f"dividend 批量拉取失败: {e}")
        return records

    # ─── 从本地 CSV 加载事件 ──────────────────────────────────────

    def _load_csv_events(self) -> list[EventRecord]:
        """从本地 CSV 加载政策事件和盘前事件

        源文件:
          - data/events/policy_events.csv
          - data/events/preopen_events.csv
        """
        records: list[EventRecord] = []
        csv_files = [
            ("policy_events", DATA_DIR / "events" / "policy_events.csv"),
            ("preopen_events", DATA_DIR / "events" / "preopen_events.csv"),
        ]

        for source_name, csv_path in csv_files:
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                if df.empty:
                    continue

                for _, row in df.iterrows():
                    title = str(row.get("title", "") or "")
                    content = str(row.get("content", "") or "")
                    symbols = str(row.get("related_symbols", "") or "")
                    event_id = str(row.get("event_id", "") or "")
                    pub_time = str(row.get("publish_time", "") or "")

                    if not symbols:
                        continue

                    # 解析股票代码列表
                    raw_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
                    for sym in raw_symbols:
                        ts = symbol_to_ts_code(sym)

                        # 仅保留半导体池内的事件
                        universe = self._get_universe_codes()
                        semis = set(universe)
                        sym_clean = sym.split(".")[0]
                        if sym_clean not in semis and sym_clean not in [
                            ts_code_to_symbol(s) for s in semis
                        ]:
                            continue

                        # 日期
                        event_date_str = pub_time[:10] if len(pub_time) >= 10 else ""
                        if not event_date_str:
                            event_date_str = datetime.now(CST).strftime("%Y-%m-%d")
                        event_date = self._find_next_trading_day(event_date_str)
                        if event_date is None:
                            continue

                        # 推断事件类型和方向
                        event_type, direction, strength = self._infer_event_type(
                            title, content
                        )

                        records.append(EventRecord(
                            event_date=event_date,
                            ts_code=ts,
                            event_type=event_type,
                            event_direction=direction,
                            event_strength=strength,
                            event_source=source_name,
                            title=title[:200],
                            detail=content[:500],
                            source_ref=event_id or f"{source_name}.{sym}.{event_date}",
                        ))
            except Exception as e:
                logger.warning(f"加载 {csv_path} 失败: {e}")
                continue

        logger.info(f"从本地 CSV 加载 {len(records)} 条事件")
        return records

    # ─── 事件类型推断 ─────────────────────────────────────────────

    @staticmethod
    def _infer_event_type(title: str, content: str) -> tuple[str, str, int]:
        """根据标题和内容推断事件类型、方向和强度

        Returns:
            (event_type, direction, strength)
        """
        text = (title + " " + content).lower()

        # 关键词 → (event_type, direction, strength)
        patterns: list[tuple[str, str, str, int]] = [
            # (keyword, event_type, direction, strength)
            ("大基金", "大基金入股", "positive", 4),
            ("国产替代", "国产替代突破", "positive", 4),
            ("订单", "订单", "positive", 3),
            ("中标", "中标", "positive", 3),
            ("扩产", "扩产", "positive", 3),
            ("定增", "定增", "neutral", 2),
            ("回购", "回购", "positive", 3),
            ("减持", "减持", "negative", 3),
            ("业绩预告", "业绩预告", "neutral", 2),
            ("业绩快报", "业绩快报", "neutral", 2),
            ("资产重组", "资产重组", "neutral", 3),
            ("监管函", "监管函", "negative", 4),
            ("解禁", "限售解禁", "negative", 3),
            ("分红", "分红", "positive", 2),
            ("客户认证", "客户认证", "positive", 3),
        ]

        for keyword, etype, direction, strength in patterns:
            if keyword in text:
                return etype, direction, strength

        return "订单", "neutral", 1  # 默认

    # ─── 加载全部事件 ─────────────────────────────────────────────

    def load_all_events(self, start_date: str = "20250101",
                        end_date: str = "",
                        include_tushare: bool = True,
                        include_csv: bool = True) -> list[EventRecord]:
        """从所有可用数据源加载事件

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 截止日期 YYYYMMDD
            include_tushare: 是否从 Tushare 拉取
            include_csv: 是否从本地 CSV 加载

        Returns:
            合并去重后的事件列表 (按日期排序)
        """
        all_records: list[EventRecord] = []

        if include_tushare:
            all_records.extend(self._fetch_forecast_events(start_date, end_date))
            all_records.extend(self._fetch_holdertrade_events(start_date, end_date))
            all_records.extend(self._fetch_repurchase_events(start_date))
            all_records.extend(self._fetch_share_float_events(start_date, end_date))
            all_records.extend(self._fetch_dividend_events(start_date, end_date))

        if include_csv:
            all_records.extend(self._load_csv_events())

        # 去重: (date + ts_code + event_type) 去重
        seen: set[tuple[str, str, str]] = set()
        unique: list[EventRecord] = []
        for rec in sorted(all_records, key=lambda r: r.event_date):
            key = (rec.event_date, rec.ts_code, rec.event_type)
            if key not in seen:
                seen.add(key)
                unique.append(rec)

        logger.info(f"半导体事件引擎: 共加载 {len(unique)} 条事件 (去重前 {len(all_records)})")
        return unique

    # ─── 事件频率统计 ─────────────────────────────────────────────

    def compute_event_frequencies(self, events: list[EventRecord],
                                  windows: Optional[list[int]] = None) -> pd.DataFrame:
        """计算各标的各类型事件在近N日内的发生次数

        Args:
            events: 事件列表
            windows: 时间窗口 (默认 [30, 90] 天)

        Returns:
            DataFrame: [ts_code, event_type, freq_30d, freq_90d, ...]
        """
        if windows is None:
            windows = [30, 90]

        if not events:
            return pd.DataFrame()

        now = datetime.now(CST)
        rows = []

        # 按 (ts_code, event_type) 分组
        grouped: dict[tuple[str, str], list[EventRecord]] = defaultdict(list)
        for e in events:
            grouped[(e.ts_code, e.event_type)].append(e)

        for (ts_code, event_type), recs in grouped.items():
            row: dict = {"ts_code": ts_code, "event_type": event_type,
                         "event_type_cn": EVENT_CATEGORY_MAP.get(event_type, "其他")}
            for w in windows:
                cutoff = now - timedelta(days=w)
                count = sum(
                    1 for r in recs
                    if datetime.strptime(r.event_date, "%Y-%m-%d").replace(tzinfo=None) >= cutoff.replace(tzinfo=None)
                )
                row[f"freq_{w}d"] = count
            # 最近事件日期
            dates = sorted([r.event_date for r in recs])
            row["last_event_date"] = dates[-1] if dates else ""
            row["total_events"] = len(recs)
            rows.append(row)

        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values(["ts_code", "event_type"]).reset_index(drop=True)
        return result

    # ─── 事件因子计算 ─────────────────────────────────────────────

    def compute_event_factors(self, events: list[EventRecord],
                              return_windows: Optional[list[int]] = None) -> pd.DataFrame:
        """计算事件后 N 日收益因子

        方法:
          - 将事件日期映射到交易日
          - 计算事件后 1/5/20 日的个股收益
          - 相对于同池等权基准计算超额收益

        Args:
            events: 事件列表
            return_windows: 收益窗口 [1, 5, 20] (交易日)

        Returns:
            DataFrame: [event_date, ts_code, event_type, direction, strength,
                        ret_1d, ret_5d, ret_20d, excess_1d, excess_5d, excess_20d]
        """
        if return_windows is None:
            return_windows = [1, 5, 20]

        if not events:
            return pd.DataFrame()

        # 1. 获取所有涉及的股票 + 交易日序列
        symbols = list(set(ts_code_to_symbol(e.ts_code) for e in events))
        trading_days = self._get_trading_days().tolist()
        trading_dates = [d.strftime("%Y-%m-%d") for d in trading_days]
        date_to_idx = {d: i for i, d in enumerate(trading_dates)}

        # 2. 获取基准收益
        try:
            from benchmarks_v4 import get_benchmark_returns
            bench_rets = get_benchmark_returns("semiconductor_ew")
            # 转换为 dict: date → return
            bench_dict: dict[str, float] = {}
            if not bench_rets.empty:
                for dt, ret in bench_rets.items():
                    if isinstance(dt, datetime):
                        date_str = dt.strftime("%Y-%m-%d")
                    else:
                        date_str = str(dt)[:10]
                    bench_dict[date_str] = float(ret)
        except Exception as e:
            logger.warning(f"加载基准收益失败: {e}")
            bench_dict = {}

        # 3. 获取K线数据
        try:
            from benchmarks_v4 import _load_kline_for_codes
            kline = _load_kline_for_codes(symbols)
        except Exception as e:
            logger.warning(f"加载K线数据失败: {e}")
            kline = pd.DataFrame()

        # 4. 计算 pct_change 收益
        if not kline.empty:
            kline = kline.sort_values(["symbol", "date"]).copy()
            kline["date_str"] = kline["date"].dt.strftime("%Y-%m-%d")
            pivot = kline.pivot_table(index="date_str", columns="symbol", values="close")
            # 日后N日收益
            future_returns: dict[str, dict[str, float]] = {}
            for col in pivot.columns:
                vals = pivot[col].dropna()
                future_returns[col] = {}
                for i, (dt_str, price) in enumerate(vals.items()):
                    for w in return_windows:
                        if i + w < len(vals):
                            future_ret = (vals.iloc[i + w] - price) / price
                        else:
                            future_ret = np.nan
                        future_returns[col][dt_str] = future_ret
        else:
            future_returns = {}

        # 5. 构建结果
        rows = []
        for ev in events:
            sym = ts_code_to_symbol(ev.ts_code)
            dt_str = ev.event_date

            row: dict = {
                "event_date": dt_str,
                "ts_code": ev.ts_code,
                "symbol": sym,
                "event_type": ev.event_type,
                "event_category": EVENT_CATEGORY_MAP.get(ev.event_type, "其他"),
                "direction": ev.event_direction,
                "strength": ev.event_strength,
                "source": ev.event_source,
                "title": ev.title,
            }

            # 事件后收益
            if sym in future_returns and dt_str in future_returns[sym]:
                for w in return_windows:
                    ret_val = future_returns[sym][dt_str]
                    row[f"ret_{w}d"] = round(float(ret_val) * 100, 4) if not np.isnan(ret_val) else None

                    # 超额收益
                    bench_ret = bench_dict.get(dt_str, 0)
                    excess = (float(ret_val) - bench_ret) * 100 if not np.isnan(ret_val) else None
                    row[f"excess_{w}d"] = round(float(excess), 4) if excess is not None else None
            else:
                for w in return_windows:
                    row[f"ret_{w}d"] = None
                    row[f"excess_{w}d"] = None

            rows.append(row)

        result = pd.DataFrame(rows)
        return result

    # ─── 因子报告 ─────────────────────────────────────────────────

    def generate_factor_report(self, factors: pd.DataFrame) -> dict:
        """生成事件因子汇总报告

        Args:
            factors: compute_event_factors 的返回结果

        Returns:
            包含各维度统计的 dict
        """
        if factors.empty:
            return {"total_events": 0, "status": "empty"}

        report: dict = {
            "total_events": len(factors),
            "date_range": {
                "start": factors["event_date"].min() if "event_date" in factors else "",
                "end": factors["event_date"].max() if "event_date" in factors else "",
            },
        }

        # 按事件类型统计
        if "event_type" in factors:
            type_stats = factors["event_type"].value_counts().to_dict()
            report["by_event_type"] = {k: int(v) for k, v in type_stats.items()}

        # 按方向统计
        if "direction" in factors:
            dir_stats = factors["direction"].value_counts().to_dict()
            report["by_direction"] = {k: int(v) for k, v in dir_stats.items()}

        # 按来源统计
        if "source" in factors:
            src_stats = factors["source"].value_counts().to_dict()
            report["by_source"] = {k: int(v) for k, v in src_stats.items()}

        # 收益统计 (ret_5d, ret_20d)
        for col in ["ret_5d", "ret_20d", "excess_5d", "excess_20d"]:
            if col in factors.columns:
                series = factors[col].dropna()
                if len(series) > 0:
                    report[f"{col}_stats"] = {
                        "mean": round(float(series.mean()), 4),
                        "median": round(float(series.median()), 4),
                        "std": round(float(series.std()), 4),
                        "positive_ratio": round(float((series > 0).mean()), 4),
                        "count": int(len(series)),
                    }

        # 按方向 × 事件类型汇总
        if "direction" in factors.columns and "event_type" in factors.columns:
            cross = factors.groupby(["direction", "event_type"]).agg(
                count=("ret_5d", "count"),
                mean_ret_5d=("ret_5d", "mean"),
                mean_excess_5d=("excess_5d", "mean"),
            ).reset_index()
            # JSON 友好的输出
            cross_list = []
            for _, row in cross.iterrows():
                item = {
                    "direction": row["direction"],
                    "event_type": row["event_type"],
                    "count": int(row["count"]),
                }
                if pd.notna(row["mean_ret_5d"]):
                    item["mean_ret_5d_pct"] = round(float(row["mean_ret_5d"]), 4)
                if pd.notna(row["mean_excess_5d"]):
                    item["mean_excess_5d_pct"] = round(float(row["mean_excess_5d"]), 4)
                cross_list.append(item)
            report["direction_event_type_cross"] = cross_list

        # 方向上胜率
        if "direction" in factors.columns:
            dir_win = {}
            for d in ["positive", "negative", "neutral"]:
                sub = factors[factors["direction"] == d]
                if len(sub) == 0:
                    continue
                dir_win[d] = {}
                for col in ["ret_5d", "ret_20d"]:
                    if col in sub.columns:
                        s = sub[col].dropna()
                        if len(s) > 0:
                            dir_win[d][f"{col}_positive_ratio"] = round(
                                float((s > 0).mean()), 4
                            )
                            dir_win[d][f"{col}_mean"] = round(float(s.mean()), 4)
            report["direction_win_rates"] = dir_win

        return report

    # ─── 事件列表输出 ─────────────────────────────────────────────

    @staticmethod
    def format_events_table(events: list[EventRecord], limit: int = 50) -> str:
        """将事件列表格式化为可读表格

        Args:
            events: 事件列表
            limit: 最大显示行数

        Returns:
            str: 格式化的表格文本
        """
        if not events:
            return "无事件记录"

        lines = [
            f"📋 半导体事件列表 ({len(events)} 条, 显示前 {min(limit, len(events))})",
            f"{'日期':12s} {'代码':12s} {'类型':10s} {'方向':10s} {'强度':6s} {'来源':12s} {'标题'}",
            "-" * 120,
        ]

        for ev in events[:limit]:
            d_icon = {"positive": "📈", "negative": "📉", "neutral": "➡️"}.get(
                ev.event_direction, "❓"
            )
            lines.append(
                f"{ev.event_date:12s} {ev.ts_code:12s} {ev.event_type:10s} "
                f"{d_icon} {ev.event_direction:8s} {ev.event_strength:^6d} "
                f"{ev.event_source:12s} {ev.title[:50]}"
            )

        if len(events) > limit:
            lines.append(f"... 及另外 {len(events) - limit} 条")
        return "\n".join(lines)

    @staticmethod
    def format_factor_report(report: dict) -> str:
        """将因子报告格式化为可读文本"""
        if not report or report.get("total_events", 0) == 0:
            return "无事件因子数据"

        lines = [
            "📊 半导体事件因子报告",
            f"{'=' * 60}",
            f"总事件数: {report['total_events']}",
            f"日期范围: {report.get('date_range', {}).get('start', '?')} ~ "
            f"{report.get('date_range', {}).get('end', '?')}",
            "",
        ]

        # 事件类型分布
        if "by_event_type" in report:
            lines.append("📂 事件类型分布:")
            for etype, count in sorted(
                report["by_event_type"].items(), key=lambda x: -x[1]
            ):
                lines.append(f"  {etype:12s}: {count} 条")
            lines.append("")

        # 方向分布
        if "by_direction" in report:
            lines.append("📈 方向分布:")
            for direction, count in sorted(
                report["by_direction"].items(), key=lambda x: -x[1]
            ):
                icon = {"positive": "📈", "negative": "📉", "neutral": "➡️"}.get(direction, "❓")
                lines.append(f"  {icon} {direction:10s}: {count} 条")
            lines.append("")

        # 收益统计
        for label, col in [("事件后5日收益 (%)", "ret_5d_stats"),
                           ("事件后20日收益 (%)", "ret_20d_stats"),
                           ("事件后5日超额收益 (%)", "excess_5d_stats"),
                           ("事件后20日超额收益 (%)", "excess_20d_stats")]:
            stats = report.get(col)
            if stats:
                lines.append(f"📊 {label}:")
                lines.append(f"  均值: {stats['mean']:+.4f}  |  中位数: {stats['median']:+.4f}")
                lines.append(f"  标准差: {stats['std']:.4f}  |  上涨比例: {stats['positive_ratio']:.2%}")
                lines.append(f"  样本量: {stats['count']}")
                lines.append("")

        # 方向胜率
        if "direction_win_rates" in report:
            lines.append("🎯 方向胜率:")
            for direction, stats in report["direction_win_rates"].items():
                icon = {"positive": "📈", "negative": "📉", "neutral": "➡️"}.get(direction, "❓")
                lines.append(f"  {icon} {direction}:")
                for col_name, val in stats.items():
                    lines.append(f"    {col_name}: {val}")
            lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# CLI 命令函数
# ═══════════════════════════════════════════════════════════════════════════


def cmd_event_list(args: list[str]) -> None:
    """event:list — 列出近期半导体事件

    用法: python3 hermes_cli.py event:list [--days 90] [--type 业绩预告] [--direction positive]
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="回溯天数 (默认90)")
    parser.add_argument("--type", default="", help="按事件类型筛选")
    parser.add_argument("--direction", default="", help="按方向筛选 (positive/negative/neutral)")
    parser.add_argument("--limit", type=int, default=50, help="最大显示条数")
    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return

    engine = SemiconductorEventEngine()
    start = (datetime.now(CST) - timedelta(days=parsed.days)).strftime("%Y%m%d")
    events = engine.load_all_events(start_date=start)

    # 筛选
    if parsed.type:
        events = [e for e in events if e.event_type == parsed.type]
    if parsed.direction:
        events = [e for e in events if e.event_direction == parsed.direction]

    events.sort(key=lambda e: e.event_date, reverse=True)
    print(engine.format_events_table(events, limit=parsed.limit))


def cmd_event_factors(args: list[str]) -> None:
    """event:factors — 生成事件因子

    用法: python3 hermes_cli.py event:factors [--days 365] [--output PATH]
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365, help="回溯天数 (默认365)")
    parser.add_argument("--output", default="", help="输出文件路径 (默认打印)")
    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return

    engine = SemiconductorEventEngine()
    start = (datetime.now(CST) - timedelta(days=parsed.days)).strftime("%Y%m%d")
    events = engine.load_all_events(start_date=start)
    factors = engine.compute_event_factors(events)

    if factors.empty:
        print("⚠️ 无事件因子数据")
        return

    print(f"📊 事件因子: {len(factors)} 条记录")
    print(f"   列: {list(factors.columns)}")
    print()
    # 显示前20行摘要
    summary_cols = ["event_date", "ts_code", "event_type", "direction",
                    "strength", "ret_5d", "excess_5d"]
    available = [c for c in summary_cols if c in factors.columns]
    print(factors[available].head(20).to_string(index=False))
    print()

    if parsed.output:
        factors.to_csv(parsed.output, index=False, encoding="utf-8-sig")
        print(f"✅ 已保存到: {parsed.output}")


def cmd_event_report(args: list[str]) -> None:
    """event:report — 事件因子报告

    用法: python3 hermes_cli.py event:report [--days 365] [--json]
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365, help="回溯天数 (默认365)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return

    engine = SemiconductorEventEngine()
    start = (datetime.now(CST) - timedelta(days=parsed.days)).strftime("%Y%m%d")
    events = engine.load_all_events(start_date=start)
    factors = engine.compute_event_factors(events)
    report = engine.generate_factor_report(factors)

    if parsed.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(engine.format_factor_report(report))


if __name__ == "__main__":
    # 快速测试
    engine = SemiconductorEventEngine()
    events = engine.load_all_events()
    print(f"加载 {len(events)} 条事件")
    if events:
        factors = engine.compute_event_factors(events)
        report = engine.generate_factor_report(factors)
        print(engine.format_factor_report(report))
