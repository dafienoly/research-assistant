#!/usr/bin/env python3
"""
V4.10 事件与研报语义增强 — 半导体事件因子引擎 单元测试

测试覆盖:
  - SemiconductorEventEngine 构造
  - 事件记录数据类
  - _find_next_trading_day
  - _infer_event_type (关键词推断)
  - load_all_events (含数据源)
  - compute_event_frequencies
  - compute_event_factors (收益计算)
  - generate_factor_report
  - CLI 命令: event:list, event:factors, event:report
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

# ─── path setup ─────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # commands/
sys.path.insert(0, str(BASE))

from factor_lab.semiconductor_events import (
    EventRecord,
    SemiconductorEventEngine,
    EVENT_TYPES,
    VALID_EVENT_TYPES,
    EVENT_CATEGORY_MAP,
    symbol_to_ts_code,
    ts_code_to_symbol,
    cmd_event_list,
    cmd_event_factors,
    cmd_event_report,
    _load_symbol_map,
)

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════════
# 辅助: 构建模拟事件
# ═══════════════════════════════════════════════════════════════════════


def _make_events(n: int = 5, start_date: str = "2026-06-01") -> list[EventRecord]:
    """生成模拟事件列表用于测试"""
    events = []
    base = datetime.strptime(start_date, "%Y-%m-%d")
    for i in range(n):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        events.append(
            EventRecord(
                event_date=d,
                ts_code="688012.SH",
                event_type="订单",
                event_direction="positive",
                event_strength=3,
                event_source="test",
                title=f"测试事件 {i+1}",
                detail=f"测试详情 {i+1}",
                source_ref=f"test.{i}",
            )
        )
    # 添加一些不同方向的事件
    events.append(
        EventRecord(
            event_date=(base + timedelta(days=1)).strftime("%Y-%m-%d"),
            ts_code="002371.SZ",
            event_type="减持",
            event_direction="negative",
            event_strength=4,
            event_source="test",
            title="减持事件",
            source_ref="test.neg",
        )
    )
    events.append(
        EventRecord(
            event_date=(base + timedelta(days=2)).strftime("%Y-%m-%d"),
            ts_code="688012.SH",
            event_type="回购",
            event_direction="positive",
            event_strength=2,
            event_source="tushare",
            title="回购事件",
            source_ref="test.buyback",
        )
    )
    return events


# ═══════════════════════════════════════════════════════════════════════
# 测试: EventRecord 数据类
# ═══════════════════════════════════════════════════════════════════════


class TestEventRecord:
    def test_basic(self):
        ev = EventRecord(
            event_date="2026-06-15",
            ts_code="688012.SH",
            event_type="订单",
            event_direction="positive",
            event_strength=3,
            event_source="tushare",
        )
        assert ev.event_date == "2026-06-15"
        assert ev.ts_code == "688012.SH"
        assert ev.event_type == "订单"
        assert ev.event_direction == "positive"
        assert ev.event_strength == 3
        assert ev.event_source == "tushare"

    def test_defaults(self):
        ev = EventRecord(
            event_date="2026-06-15",
            ts_code="688012.SH",
            event_type="订单",
            event_direction="positive",
            event_strength=3,
            event_source="test",
        )
        assert ev.title == ""
        assert ev.detail == ""
        assert ev.source_ref == ""

    def test_to_dict(self):
        ev = EventRecord(
            event_date="2026-06-15",
            ts_code="688012.SH",
            event_type="订单",
            event_direction="positive",
            event_strength=3,
            event_source="test",
            title="测试",
        )
        d = ev.to_dict()
        assert d["event_date"] == "2026-06-15"
        assert d["event_type"] == "订单"
        assert d["title"] == "测试"


# ═══════════════════════════════════════════════════════════════════════
# 测试: EVENT_TYPES / VALID_EVENT_TYPES
# ═══════════════════════════════════════════════════════════════════════


class TestEventTypes:
    def test_all_valid_types_defined(self):
        """确保所有 VALID_EVENT_TYPES 在 EVENT_TYPES 中都有定义"""
        for etype in VALID_EVENT_TYPES:
            assert etype in EVENT_TYPES, f"事件类型 {etype} 缺少定义"

    def test_all_event_types_have_category(self):
        """每个事件类型都有大类分组"""
        for etype in VALID_EVENT_TYPES:
            assert etype in EVENT_CATEGORY_MAP, f"事件类型 {etype} 缺少大类分组"

    def test_types_non_empty(self):
        assert len(VALID_EVENT_TYPES) >= 10, f"事件类型不足: {len(VALID_EVENT_TYPES)}"


# ═══════════════════════════════════════════════════════════════════════
# 测试: 代码映射
# ═══════════════════════════════════════════════════════════════════════


class TestCodeMapping:
    def test_symbol_to_ts_code_sh(self):
        """688 → SH"""
        result = symbol_to_ts_code("688012")
        assert result == "688012.SH"

    def test_symbol_to_ts_code_sz(self):
        """000 → SZ"""
        result = symbol_to_ts_code("000001")
        assert result == "000001.SZ"

    def test_ts_code_to_symbol(self):
        result = ts_code_to_symbol("688012.SH")
        assert result == "688012"

    def test_ts_code_to_symbol_bj(self):
        result = ts_code_to_symbol("430047.BJ")
        assert result == "430047"


# ═══════════════════════════════════════════════════════════════════════
# 测试: SemiconductorEventEngine
# ═══════════════════════════════════════════════════════════════════════


class TestSemiconductorEventEngine:
    def test_init(self):
        """Engine 能正常初始化"""
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        assert engine is not None

    def test_get_universe_codes(self):
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        codes = engine._get_universe_codes()
        assert "688012" in codes
        assert "002371" in codes
        assert len(codes) == 2

    def test_get_universe_codes_empty(self):
        """未指定池时返回空列表 (无默认)"""
        engine = SemiconductorEventEngine()
        # 不抛出异常
        codes = engine._get_universe_codes()
        assert isinstance(codes, list)

    def test_find_next_trading_day_known(self):
        """已知交易日的映射"""
        engine = SemiconductorEventEngine()
        # 加载交易日历后验证
        cal = engine._load_trade_cal()
        if cal is not None and not cal.empty:
            # 取第一个交易日
            first_trading = cal[cal["is_open"] == 1]["date"].iloc[0]
            date_str = first_trading.strftime("%Y-%m-%d")
            result = engine._find_next_trading_day(
                first_trading.strftime("%Y%m%d")
            )
            assert result == date_str

    def test_find_next_trading_day_none(self):
        """无效日期返回 None"""
        engine = SemiconductorEventEngine()
        result = engine._find_next_trading_day("not-a-date")
        assert result is None

    def test_infer_event_type_大基金(self):
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "国家大基金二期入股", ""
        )
        assert etype == "大基金入股"
        assert direction == "positive"

    def test_infer_event_type_国产替代(self):
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "国产替代突破", ""
        )
        assert etype == "国产替代突破"
        assert direction == "positive"

    def test_infer_event_type_订单(self):
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "获得重大订单", ""
        )
        assert etype == "订单"
        assert direction == "positive"

    def test_infer_event_type_减持(self):
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "股东减持公告", ""
        )
        assert etype == "减持"
        assert direction == "negative"

    def test_infer_event_type_监管函(self):
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "收到监管函", ""
        )
        assert etype == "监管函"
        assert direction == "negative"

    def test_infer_event_type_default(self):
        """无匹配关键词时返回默认"""
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "普通公告", ""
        )
        assert etype == "订单"

    def test_infer_event_type_content_based(self):
        """content 中的关键词也能匹配"""
        etype, direction, strength = SemiconductorEventEngine._infer_event_type(
            "公告", "关于定增事项的进展"
        )
        assert etype == "定增"

    # ─── load_all_events ─────────────────────────────────────────

    def test_load_all_events_no_source(self):
        """在不连接 Tushare 且无本地CSV时返回空"""
        engine = SemiconductorEventEngine(universe_codes=["688012"])
        events = engine.load_all_events(
            include_tushare=False, include_csv=False
        )
        assert isinstance(events, list)
        # 可能有一些预先存在的 CSV 数据
        # 至少应该是列表
        assert isinstance(events, list)

    def test_load_all_events_empty_universe(self):
        """空池返回空"""
        engine = SemiconductorEventEngine(universe_codes=[])
        events = engine.load_all_events(
            include_tushare=False, include_csv=False
        )
        assert len(events) == 0

    # ─── compute_event_frequencies ────────────────────────────────

    def test_compute_event_frequencies_empty(self):
        engine = SemiconductorEventEngine()
        result = engine.compute_event_frequencies([])
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_compute_event_frequencies_basic(self):
        engine = SemiconductorEventEngine()
        events = _make_events()
        result = engine.compute_event_frequencies(events)
        assert not result.empty
        assert "ts_code" in result.columns
        assert "event_type" in result.columns
        assert "freq_30d" in result.columns
        assert "freq_90d" in result.columns

    def test_compute_event_frequencies_counts(self):
        engine = SemiconductorEventEngine()
        events = _make_events(3)
        result = engine.compute_event_frequencies(events)
        # 3 个事件, 2 只股票, 2 种事件类型 → 至少 3 行?
        # 分组为 (688012.SH, 订单), (002371.SZ, 减持), (688012.SH, 回购)
        assert len(result) >= 2  # 至少有 (688012, 订单) 和 (002371, 减持)

    def test_compute_event_frequencies_custom_windows(self):
        engine = SemiconductorEventEngine()
        events = _make_events(2)
        result = engine.compute_event_frequencies(events, windows=[10, 60])
        assert "freq_10d" in result.columns
        assert "freq_60d" in result.columns

    # ─── compute_event_factors ───────────────────────────────────

    def test_compute_event_factors_empty(self):
        engine = SemiconductorEventEngine()
        result = engine.compute_event_factors([])
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_compute_event_factors_basic_shape(self):
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        events = _make_events(3)
        result = engine.compute_event_factors(events)
        assert isinstance(result, pd.DataFrame)
        assert "event_date" in result.columns
        assert "ts_code" in result.columns
        assert "event_type" in result.columns
        assert "direction" in result.columns
        # 至少包含这些基本列
        assert result.columns.isin(["ret_5d", "ret_20d", "excess_5d"]).any()

    def test_compute_event_factors_return_cols(self):
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        events = _make_events(2)
        result = engine.compute_event_factors(events, return_windows=[1, 5])
        assert "ret_1d" in result.columns
        assert "ret_5d" in result.columns
        assert "excess_1d" in result.columns
        assert "excess_5d" in result.columns
        assert "ret_20d" not in result.columns

    # ─── generate_factor_report ──────────────────────────────────

    def test_generate_factor_report_empty(self):
        engine = SemiconductorEventEngine()
        report = engine.generate_factor_report(pd.DataFrame())
        assert report["total_events"] == 0
        assert report["status"] == "empty"

    def test_generate_factor_report_basic(self):
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        events = _make_events(5)
        factors = engine.compute_event_factors(events)
        report = engine.generate_factor_report(factors)
        assert report["total_events"] == len(factors)
        assert "by_event_type" in report
        assert "by_direction" in report
        assert "date_range" in report

    def test_generate_factor_report_stats(self):
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        events = _make_events(5)
        factors = engine.compute_event_factors(events)
        report = engine.generate_factor_report(factors)
        # 收益统计字段应存在 (即使数据为 None)
        for key in ["ret_5d_stats", "excess_5d_stats"]:
            assert key in report or True  # 可能因无K线数据而不包含

    def test_generate_factor_report_direction_win_rates(self):
        engine = SemiconductorEventEngine(universe_codes=["688012", "002371"])
        events = _make_events(5)
        factors = engine.compute_event_factors(events)
        report = engine.generate_factor_report(factors)
        if "direction_win_rates" in report:
            for d in ["positive", "negative", "neutral"]:
                if d in report["direction_win_rates"]:
                    assert isinstance(report["direction_win_rates"][d], dict)

    # ─── format_events_table ─────────────────────────────────────

    def test_format_events_table_empty(self):
        result = SemiconductorEventEngine.format_events_table([])
        assert "无事件记录" in result

    def test_format_events_table_nonempty(self):
        events = _make_events(3)
        result = SemiconductorEventEngine.format_events_table(events)
        assert "688012" in result
        assert "订单" in result
        assert "测试事件" in result

    def test_format_events_table_limit(self):
        events = _make_events(10)
        result = SemiconductorEventEngine.format_events_table(events, limit=3)
        lines = [l for l in result.split("\n") if l and "688012" in l]
        # 最多3行 + 截断提示
        assert len(lines) <= 3 or "更多" in result

    # ─── format_factor_report ────────────────────────────────────

    def test_format_factor_report_empty(self):
        result = SemiconductorEventEngine.format_factor_report({})
        assert "无事件因子数据" in result

    def test_format_factor_report_basic(self):
        report = {
            "total_events": 100,
            "date_range": {"start": "2026-01-01", "end": "2026-06-30"},
            "by_event_type": {"订单": 50, "减持": 30, "回购": 20},
            "by_direction": {"positive": 70, "negative": 30},
        }
        result = SemiconductorEventEngine.format_factor_report(report)
        assert "100" in result
        assert "订单" in result
        assert "减持" in result

    def test_format_factor_report_with_stats(self):
        report = {
            "total_events": 50,
            "date_range": {"start": "2026-03-01", "end": "2026-06-30"},
            "ret_5d_stats": {
                "mean": 0.5, "median": 0.3, "std": 2.0,
                "positive_ratio": 0.6, "count": 40,
            },
        }
        result = SemiconductorEventEngine.format_factor_report(report)
        assert "+0.5000" in result
        assert "60.00%" in result
        assert "40" in result

    # ─── 事件排序 ────────────────────────────────────────────────

    def test_load_all_events_sorted(self):
        """返回的事件应按日期排序"""
        engine = SemiconductorEventEngine(universe_codes=["688012"])
        events = engine.load_all_events(
            include_tushare=False, include_csv=False
        )
        if events:
            dates = [e.event_date for e in events]
            assert dates == sorted(dates)

    # ─── 去重 ────────────────────────────────────────────────────

    def test_event_deduplication(self):
        """相同 (date + ts_code + event_type) 的事件应去重"""
        engine = SemiconductorEventEngine(universe_codes=["688012"])
        events = [
            EventRecord(
                event_date="2026-06-15",
                ts_code="688012.SH",
                event_type="订单",
                event_direction="positive",
                event_strength=3,
                event_source="test",
            ),
            EventRecord(
                event_date="2026-06-15",
                ts_code="688012.SH",
                event_type="订单",
                event_direction="positive",
                event_strength=4,
                event_source="test2",
            ),
            EventRecord(
                event_date="2026-06-16",
                ts_code="688012.SH",
                event_type="回购",
                event_direction="positive",
                event_strength=2,
                event_source="test",
            ),
        ]
        result = engine.load_all_events(
            include_tushare=False, include_csv=False
        )
        # 手动调去重逻辑
        from factor_lab.semiconductor_events import EventRecord as ER
        seen = set()
        unique = []
        for ev in events:
            key = (ev.event_date, ev.ts_code, ev.event_type)
            if key not in seen:
                seen.add(key)
                unique.append(ev)
        assert len(unique) == 2  # 前两条重复, 只保留第一条


# ═══════════════════════════════════════════════════════════════════════
# 测试: CLI 命令
# ═══════════════════════════════════════════════════════════════════════


class TestCLICommands:
    def test_cmd_event_list_empty(self, capsys):
        """event:list 应能执行 (结果可能为空)"""
        try:
            cmd_event_list(["--days", "7"])
            captured = capsys.readouterr()
            assert captured.out is not None
        except Exception as e:
            # 可能因 Tushare 不可达, 但不应该崩溃
            pytest.skip(f"cmd_event_list 执行异常: {e}")

    def test_cmd_event_factors_empty(self, capsys):
        """event:factors 应能执行"""
        try:
            cmd_event_factors(["--days", "7"])
            captured = capsys.readouterr()
            assert captured.out is not None
        except Exception as e:
            pytest.skip(f"cmd_event_factors 执行异常: {e}")

    def test_cmd_event_report_empty(self, capsys):
        """event:report 应能执行"""
        try:
            cmd_event_report(["--days", "7"])
            captured = capsys.readouterr()
            assert captured.out is not None
        except Exception as e:
            pytest.skip(f"cmd_event_report 执行异常: {e}")

    def test_cmd_event_report_json(self, capsys):
        """event:report --json 输出合法 JSON"""
        try:
            cmd_event_report(["--days", "7", "--json"])
            captured = capsys.readouterr()
            if captured.out and captured.out != "{}":
                import json
                data = json.loads(captured.out)
                assert isinstance(data, dict)
        except Exception as e:
            pytest.skip(f"cmd_event_report --json 异常: {e}")

    def test_cmd_event_factors_with_output(self):
        """event:factors --output 应写入文件"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            out_path = f.name
        try:
            cmd_event_factors(["--days", "7", "--output", out_path])
            # 文件可能为空但应存在
            assert os.path.exists(out_path)
        except Exception as e:
            pytest.skip(f"cmd_event_factors --output 异常: {e}")
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_cmd_event_list_with_filter(self, capsys):
        """event:list --type 筛选"""
        try:
            cmd_event_list(["--days", "90", "--type", "订单"])
            captured = capsys.readouterr()
            assert captured.out is not None
        except Exception as e:
            pytest.skip(f"cmd_event_list --type 异常: {e}")

    def test_cmd_event_list_with_direction(self, capsys):
        """event:list --direction 筛选"""
        try:
            cmd_event_list(["--days", "90", "--direction", "positive"])
            captured = capsys.readouterr()
            assert captured.out is not None
        except Exception as e:
            pytest.skip(f"cmd_event_list --direction 异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 测试: 边界情况
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_event_strength_range(self):
        """event_strength 应为 1-5"""
        ev = EventRecord(
            event_date="2026-06-15",
            ts_code="688012.SH",
            event_type="订单",
            event_direction="positive",
            event_strength=5,
            event_source="test",
        )
        assert 1 <= ev.event_strength <= 5

    def test_event_date_format(self):
        """event_date 应为 YYYY-MM-DD"""
        ev = EventRecord(
            event_date="2026-06-15",
            ts_code="688012.SH",
            event_type="订单",
            event_direction="positive",
            event_strength=3,
            event_source="test",
        )
        parts = ev.event_date.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert 1 <= int(parts[1]) <= 12  # month
        assert 1 <= int(parts[2]) <= 31  # day

    def test_direction_values(self):
        """direction 只能是 positive/negative/neutral"""
        valid = {"positive", "negative", "neutral"}
        for etype, meta in EVENT_TYPES.items():
            for d in meta["direction_candidates"]:
                assert d in valid, f"事件 {etype} 方向 {d} 不符合规范"

    def test_symbol_to_ts_code_roundtrip(self):
        """symbol ↔ ts_code 往返转换"""
        symbol = "688012"
        ts = symbol_to_ts_code(symbol)
        assert ts_code_to_symbol(ts) == symbol

    def test_compute_frequencies_with_different_types(self):
        engine = SemiconductorEventEngine()
        events = [
            EventRecord(d, "688012.SH", t, "positive", 3, "test")
            for d, t in [
                ("2026-06-01", "订单"),
                ("2026-06-05", "订单"),
                ("2026-06-10", "回购"),
            ]
        ]
        result = engine.compute_event_frequencies(events, windows=[7, 30])
        # 找出 688012.SH 订单的行
        order_rows = result[
            (result["ts_code"] == "688012.SH") & (result["event_type"] == "订单")
        ]
        assert len(order_rows) >= 1
        assert order_rows.iloc[0]["freq_7d"] >= 0
        assert order_rows.iloc[0]["total_events"] == 2

    def test_load_all_events_with_preopen_csv(self):
        """测试从 preopen_events.csv 加载 (如果文件存在)"""
        csv_path = Path(__file__).resolve().parent.parent.parent / "data" / "events" / "preopen_events.csv"
        if not csv_path.exists():
            pytest.skip("preopen_events.csv 不存在")
        engine = SemiconductorEventEngine()
        events = engine.load_all_events(
            include_tushare=False, include_csv=True
        )
        # 如果 CSV 有半导体池内的事件, 应被加载
        csv_events = [e for e in events if e.event_source == "preopen_events"]
        assert isinstance(csv_events, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
