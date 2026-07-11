#!/usr/bin/env python3
"""
V4.11 盘中低频监测引擎 — 单元测试

覆盖核心功能:
  - LowFreqMonitor 构造
  - check_etf_dive (ETF 跳水预警)
  - check_u3_diffusion (半导体核心池扩散度)
  - check_sentiment (全A情绪指标)
  - check_index_risk (指数风险)
  - check_volume_anomaly (成交额异常)
  - run_all / LowFreqReport.summary
  - 边界情况: 空数据、极端值、无行情
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import pandas as pd

# ─── path setup ─────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # commands/
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

CST = timezone(timedelta(hours=8))

# ─── 被测试模块 ──────────────────────────────────────────────────────────
from intraday_monitor import (
    LowFreqMonitor,
    LowFreqReport,
    ETF_DIVE_WATCH_CODES,
    INDEX_WATCH_CODES,
    U3_SEMICONDUCTOR_FALLBACK_CODES,
    VOLUME_ANOMALY_THRESHOLD_PCT,
    IntradayMonitor,
    PriceDropRule,
    PriceSurgeRule,
    DataStaleRule,
    Deduplicator,
)


# ═══════════════════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════════════════

def _fake_quote(code: str, change_pct: float = 0.0, price: float = 10.0,
                volume: int = 1_000_000, amount: float = 10_000_000_000) -> dict:
    return {
        "code": code,
        "price": price,
        "change_pct": change_pct,
        "volume": volume,
        "amount": amount,
        "source": "mock",
    }


def _turnover_history(amount: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"trade_date": [f"202606{day:02d}" for day in range(1, 21)], "market_amount": amount}
    )


# ═══════════════════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_paths(tmp_path):
    """替换 PATHS intraday 为临时目录"""
    with patch("intraday_monitor.PATHS") as mock_p:
        mock_p.__getitem__.side_effect = lambda key: {
            "intraday": tmp_path / "intraday",
            "market": tmp_path / "market",
            "tags": tmp_path / "tags",
            "commands": tmp_path / "commands",
        }.get(key, tmp_path)
        yield mock_p


@pytest.fixture
def mock_cst():
    """固定 now_cst 为 2026-07-08 10:30 (盘中)"""
    fake_now = datetime(2026, 7, 8, 10, 30, tzinfo=CST)

    with patch("intraday_monitor.now_cst", return_value=fake_now), \
         patch("intraday_monitor.now_str", return_value="2026-07-08T10:30:00+08:00"):
        yield


@pytest.fixture
def mock_ensure_dirs():
    with patch("intraday_monitor.ensure_dirs"):
        yield


@pytest.fixture
def no_fetch():
    """阻止所有真实行情获取"""
    with patch("intraday_monitor.read_live_snapshot", return_value={}):
        yield


@pytest.fixture
def monitor(mock_paths, mock_ensure_dirs, no_fetch):
    return LowFreqMonitor()


# ═══════════════════════════════════════════════════════════════════════
# LowFreqMonitor 构造
# ═══════════════════════════════════════════════════════════════════════

class TestLowFreqMonitorInit:
    def test_init_defaults(self, mock_paths, mock_ensure_dirs):
        m = LowFreqMonitor()
        assert m.etf_watch_codes == ETF_DIVE_WATCH_CODES
        assert m.index_codes == list(INDEX_WATCH_CODES.keys())
        assert m.events == []
        assert m.etf_alerts == []
        assert m.u3_diffusion == {"rising": 0, "total": 0, "ratio": 0.0}
        assert m.sentiment == {"advance": 0, "decline": 0, "ratio": 0.0}
        assert m.index_risk == []
        assert m.volume_anomaly == {}

    def test_ensure_dirs_creates(self, tmp_path):
        with patch("intraday_monitor.PATHS") as mock_p:
            mock_p.__getitem__.side_effect = lambda k: tmp_path / k
            LowFreqMonitor.ensure_dirs()
            assert (tmp_path / "intraday").exists()


# ═══════════════════════════════════════════════════════════════════════
# ETF 跳水预警
# ═══════════════════════════════════════════════════════════════════════

class TestCheckEtfDive:
    def test_no_dive_when_flat(self, monitor):
        """平盘 → 无预警"""
        with patch.object(monitor, "fetch_quotes", return_value={
            c: _fake_quote(c, change_pct=-0.5) for c in ETF_DIVE_WATCH_CODES
        }):
            alerts = monitor.check_etf_dive()
            assert alerts == []

    def test_warning_at_minus_2pct(self, monitor):
        """跌幅 ≥ 2% → 预警"""
        with patch.object(monitor, "fetch_quotes", return_value={
            "512480": _fake_quote("512480", change_pct=-2.0),
            "588290": _fake_quote("588290", change_pct=-0.3),
            "159516": _fake_quote("159516", change_pct=-1.0),
        }):
            alerts = monitor.check_etf_dive()
            assert len(alerts) == 1
            assert alerts[0]["code"] == "512480"
            assert alerts[0]["alert_level"] == "预警"
            assert alerts[0]["change_pct"] == -2.0

    def test_critical_at_minus_4pct(self, monitor):
        """跌幅 ≥ 4% → 严重"""
        with patch.object(monitor, "fetch_quotes", return_value={
            "588290": _fake_quote("588290", change_pct=-4.5),
        }):
            alerts = monitor.check_etf_dive()
            assert len(alerts) == 1
            assert alerts[0]["code"] == "588290"
            assert alerts[0]["alert_level"] == "严重"

    def test_skip_etf_with_no_data(self, monitor):
        """无行情数据 → 跳过"""
        with patch.object(monitor, "fetch_quotes", return_value={}):
            alerts = monitor.check_etf_dive()
            assert alerts == []

    def test_all_dive(self, monitor):
        """全部跳水"""
        with patch.object(monitor, "fetch_quotes", return_value={
            c: _fake_quote(c, change_pct=-3.0) for c in ETF_DIVE_WATCH_CODES
        }):
            alerts = monitor.check_etf_dive()
            assert len(alerts) == 3
            for a in alerts:
                assert a["alert_level"] == "预警"


# ═══════════════════════════════════════════════════════════════════════
# U3 半导体核心池扩散度
# ═══════════════════════════════════════════════════════════════════════

class TestCheckU3Diffusion:
    def test_all_rising(self, monitor):
        with patch.object(monitor, "fetch_u3_codes",
                          return_value=["688072", "688012"]), \
             patch.object(monitor, "fetch_quotes", return_value={
                 "688072": _fake_quote("688072", change_pct=2.0),
                 "688012": _fake_quote("688012", change_pct=1.5),
             }):
            result = monitor.check_u3_diffusion()
            assert result["rising"] == 2
            assert result["total"] == 2
            assert result["ratio"] == 1.0

    def test_half_rising(self, monitor):
        with patch.object(monitor, "fetch_u3_codes",
                          return_value=["688072", "688012", "688981"]), \
             patch.object(monitor, "fetch_quotes", return_value={
                 "688072": _fake_quote("688072", change_pct=2.0),
                 "688012": _fake_quote("688012", change_pct=-1.0),
                 "688981": _fake_quote("688981", change_pct=-0.5),
             }):
            result = monitor.check_u3_diffusion()
            assert result["rising"] == 1
            assert result["total"] == 3
            # ratio 被 round(ratio, 4) 截断
            assert result["ratio"] == pytest.approx(1 / 3, abs=1e-3)

    def test_empty_u3_codes(self, monitor):
        with patch.object(monitor, "fetch_u3_codes", return_value=[]), \
             patch.object(monitor, "fetch_quotes", return_value={}):
            result = monitor.check_u3_diffusion()
            assert result["rising"] == 0
            assert result["total"] == 0
            assert result["ratio"] == 0.0

    def test_no_quote_data(self, monitor):
        """有代码但无行情 → total=0"""
        with patch.object(monitor, "fetch_u3_codes",
                          return_value=["688072"]), \
             patch.object(monitor, "fetch_quotes", return_value={}):
            result = monitor.check_u3_diffusion()
            assert result["total"] == 0


# ═══════════════════════════════════════════════════════════════════════
# 全A情绪指标
# ═══════════════════════════════════════════════════════════════════════

class TestCheckSentiment:
    def test_fallback_from_quotes(self, monitor):
        """当 akshare 不可用时, fallback 到已有 quotes"""
        monitor.quotes = {
            "600001": _fake_quote("600001", change_pct=1.0),
            "600002": _fake_quote("600002", change_pct=-0.5),
            "600003": _fake_quote("600003", change_pct=0.2),
            "600004": _fake_quote("600004", change_pct=-1.2),
        }
        result = monitor.check_sentiment()
        assert result["advance"] == 2  # 600001, 600003
        assert result["decline"] == 2  # 600002, 600004
        assert result["total"] == 4
        assert result["ratio"] == 1.0

    def test_no_data(self, monitor):
        """无任何数据 → ratio=0.0, status=正常"""
        result = monitor.check_sentiment()
        assert result["advance"] == 0
        assert result["decline"] == 0
        assert result["ratio"] == 0.0
        assert result["status"] == "正常"

    def test_extreme_low_sentiment(self, monitor):
        monitor.quotes = {
            f"s{i}": _fake_quote(f"s{i}", change_pct=-3.0) for i in range(10)
        }
        monitor.quotes["s10"] = _fake_quote("s10", change_pct=-2.0)
        monitor.quotes["s11"] = _fake_quote("s11", change_pct=0.1)
        result = monitor.check_sentiment()
        assert result["advance"] == 1
        assert result["decline"] == 11
        # total=12, ratio=0.09 → 极低迷 (0.3 先于 0.5 判断)
        assert result["status"] == "极低迷"

    def test_overheated_sentiment(self, monitor):
        monitor.quotes = {
            f"s{i}": _fake_quote(f"s{i}", change_pct=3.0) for i in range(5)
        }
        monitor.quotes["s5"] = _fake_quote("s5", change_pct=-0.1)
        result = monitor.check_sentiment()
        assert result["status"] == "过热"


# ═══════════════════════════════════════════════════════════════════════
# 指数风险
# ═══════════════════════════════════════════════════════════════════════

class TestCheckIndexRisk:
    def test_normal(self, monitor):
        with patch.object(monitor, "fetch_quotes", return_value={
            "sh000001": _fake_quote("sh000001", change_pct=0.5),
            "sh000688": _fake_quote("sh000688", change_pct=-0.3),
            "sh000300": _fake_quote("sh000300", change_pct=1.2),
        }):
            results = monitor.check_index_risk()
            assert len(results) == 3
            for r in results:
                assert r["risk_level"] == "正常"

    def test_risk_when_minus_2pct(self, monitor):
        with patch.object(monitor, "fetch_quotes", return_value={
            "sh000001": _fake_quote("sh000001", change_pct=-2.5),
        }):
            results = monitor.check_index_risk()
            assert len(results) == 1
            assert results[0]["code"] == "000001"
            assert results[0]["risk_level"] == "风险"

    def test_watch_when_minus_1pct(self, monitor):
        with patch.object(monitor, "fetch_quotes", return_value={
            "sh000688": _fake_quote("sh000688", change_pct=-1.5),
        }):
            results = monitor.check_index_risk()
            assert results[0]["risk_level"] == "关注"

    def test_no_data(self, monitor):
        with patch.object(monitor, "fetch_quotes", return_value={}):
            results = monitor.check_index_risk()
            assert results == []


# ═══════════════════════════════════════════════════════════════════════
# 成交额异常
# ═══════════════════════════════════════════════════════════════════════

class TestCheckVolumeAnomaly:
    def test_no_data(self, monitor):
        with patch("intraday_monitor.read_market_turnover", side_effect=FileNotFoundError("missing")):
            result = monitor.check_volume_anomaly()
        assert result["today_volume"] == 0.0
        assert result["alert"] is False
        assert result["data_status"] == "MISSING"

    def test_with_quotes_amount(self, monitor):
        monitor.market_snapshot = {
            "600001": _fake_quote("600001", amount=2_000_000_000_000),  # 2000亿
            "600002": _fake_quote("600002", amount=1_000_000_000_000),
        }
        with patch("intraday_monitor.read_market_turnover", return_value=_turnover_history(3_000_000_000_000)):
            result = monitor.check_volume_anomaly()
        # 今日 ≈ 3000亿
        assert result["today_volume"] == pytest.approx(3_000_000_000_000, rel=0.1)
        assert result["avg_20d"] == 3_000_000_000_000
        # 偏离不大 → 不告警
        assert result["alert"] is False
        assert result["data_status"] == "OK"

    def test_volume_too_low(self, monitor):
        """全市场成交额低于5000亿 → alert"""
        monitor.market_snapshot = {
            "600001": _fake_quote("600001", amount=200_000_000_000),  # 200亿
        }
        with patch("intraday_monitor.read_market_turnover", return_value=_turnover_history(600_000_000_000)):
            result = monitor.check_volume_anomaly()
        assert result["alert"] is True  # below VOLUME_ANOMALY_ABS_THRESHOLD

    def test_large_deviation(self, monitor):
        """偏离超过 ±30% → alert"""
        monitor.market_snapshot = {
            "600001": _fake_quote("600001", amount=1_000_000_000_000),
        }
        with patch("intraday_monitor.read_market_turnover", return_value=_turnover_history(500_000_000_000)):
            result = monitor.check_volume_anomaly()
        assert result["pct_deviation"] == 100.0
        assert result["alert"] is True

    def test_volume_label(self, monitor):
        monitor.market_snapshot = {
            "600001": _fake_quote("600001", amount=2_500_000_000_000_000),  # 2.5万亿
        }
        with patch("intraday_monitor.read_market_turnover", return_value=_turnover_history(2_500_000_000_000_000)):
            result = monitor.check_volume_anomaly()
        assert "万亿" in result.get("volume_label", "")

        monitor2 = LowFreqMonitor()
        monitor2.market_snapshot = {"600001": _fake_quote("600001", amount=500_000_000_000)}
        with patch("intraday_monitor.read_market_turnover", return_value=_turnover_history(500_000_000_000)):
            result2 = monitor2.check_volume_anomaly()
            assert "亿" in result2.get("volume_label", "")


# ═══════════════════════════════════════════════════════════════════════
# run_all 集成
# ═══════════════════════════════════════════════════════════════════════

class TestRunAll:
    def test_run_all_returns_report(self, mock_paths, mock_ensure_dirs):
        """run_all 返回 LowFreqReport"""
        with patch("intraday_monitor.read_live_snapshot", return_value={}):
            m = LowFreqMonitor()
            report = m.run_all()
            assert isinstance(report, LowFreqReport)

    def test_empty_run_all(self, mock_paths, mock_cst, mock_ensure_dirs):
        """无行情数据时, run_all 不报错"""
        with patch("intraday_monitor.read_live_snapshot", return_value={}):
            m = LowFreqMonitor()
            report = m.run_all()
            s = report.summary()
            assert "正常" in s or "暂无" in s

    def test_summary_mentions_all_sections(self, monitor):
        """summary 包含所有监测章节"""
        report = LowFreqReport(monitor)
        s = report.summary()
        assert "预警" in s or "正常" in s
        assert "扩散度" in s
        assert "情绪" in s
        assert "指数" in s
        assert "成交额" in s

    def test_to_dict_keys(self, monitor):
        report = LowFreqReport(monitor)
        d = report.to_dict()
        assert "etf_alerts" in d
        assert "u3_diffusion" in d
        assert "sentiment" in d
        assert "index_risk" in d
        assert "volume_anomaly" in d


# ═══════════════════════════════════════════════════════════════════════
# 辅助方法
# ═══════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_etf_name(self, monitor):
        assert "国联安" in monitor._etf_name("512480")
        assert "芯片" in monitor._etf_name("588290")
        assert monitor._etf_name("999999") == "999999"

    def test_fmt_vol(self, monitor):
        assert monitor._fmt_vol(0) == "--"
        assert "万亿" in monitor._fmt_vol(1.5e12)
        assert "亿" in monitor._fmt_vol(5e8)
        assert "万" in monitor._fmt_vol(3e4)


# ═══════════════════════════════════════════════════════════════════════
# IntradayMonitor 部分单元（去重引擎）
# ═══════════════════════════════════════════════════════════════════════

class TestDeduplicator:
    def test_is_deduped_fresh(self, tmp_path):
        """同一事件在冷却期内 → dedup"""
        d = Deduplicator()
        d.state_path = tmp_path / "alert_state.json"
        event = {"symbol": "000001", "alert_type": "price_drop_3pct"}
        d.register_event(event, "L2")
        assert d.is_deduped(event, "L2") is True

    def test_not_deduped_for_different_symbol(self, tmp_path):
        d = Deduplicator()
        d.state_path = tmp_path / "alert_state.json"
        d.register_event({"symbol": "000001", "alert_type": "price_drop_3pct"}, "L2")
        # 不同股票 → 不 dedup
        assert d.is_deduped({"symbol": "000002", "alert_type": "price_drop_3pct"}, "L2") is False

    def test_l4_cooldown_zero_never_deduped(self, tmp_path):
        """L4 cooldown=0 → is_deduped 始终返回 False"""
        d = Deduplicator()
        d.state_path = tmp_path / "alert_state.json"
        event = {"symbol": "000001", "alert_type": "price_drop_3pct"}
        d.register_event(event, "L4")
        # L4 cooldown=0, 条件 (now-last).total_seconds() < 0 永远不成立
        assert d.is_deduped(event, "L4") is False
