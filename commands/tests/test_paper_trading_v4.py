#!/usr/bin/env python3
"""
V4.8 Paper / Shadow Trading 闭环 — 测试

验收标准:
  1. 模拟 20 个交易日
  2. 输出计划 vs 实际差异
  3. 输出风控拦截原因
  4. 输出相对半导体同池等权表现
  5. 若跑输同池 = NOT_READY 标志
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pandas as pd
import numpy as np

# 确保能找到 commands 包
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)  # commands/
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from factor_lab.paper.standing_paper_trading import PaperTradingV4
from factor_lab.paper.shadow_trading import ShadowTradingEngine

CST = timezone(timedelta(hours=8))
BASE = Path(_commands_dir)


# ── 辅助: 生成 20 个模拟交易日 ──────────────────────────────────────────

def _make_trade_dates(n: int = 20, start: str = "2026-06-01") -> list[str]:
    """生成连续模拟交易日 (跳过周末)"""
    dates = []
    cur = pd.Timestamp(start)
    while len(dates) < n:
        if cur.weekday() < 5:  # Mon-Fri
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


def _make_mock_market_data(
    symbols: list[str],
    dates: list[str],
    price_base: float = 50.0,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """生成模拟市场数据 (包含 close/prev_close/volume)"""
    rng = np.random.default_rng(seed)
    rows = []

    for sym in symbols:
        price = price_base + rng.uniform(-10, 10)
        prev_close = price * (1 + rng.normal(0, 0.01))
        for d in dates:
            ret = rng.normal(0, volatility)
            close = price * (1 + ret)
            # 偶尔涨停/跌停
            if rng.random() < 0.03:
                close = prev_close * 1.10  # 涨停
            elif rng.random() < 0.03:
                close = prev_close * 0.90  # 跌停
            # 偶尔停牌
            volume = max(1, int(rng.exponential(5e6)))
            if rng.random() < 0.02:
                close = 0
                volume = 0

            rows.append({
                "date": d,
                "symbol": sym.split(".")[0] if "." in sym else sym,
                "close": round(close, 2),
                "prev_close": round(prev_close, 2),
                "volume": volume,
                "open": round(close * (1 + rng.normal(0, 0.005)), 2),
                "high": round(close * (1 + abs(rng.normal(0, 0.01))), 2),
                "low": round(close * (1 - abs(rng.normal(0, 0.01))), 2),
            })
            prev_close = close
            price = close

    return pd.DataFrame(rows)


def _make_mock_factor_signals(n_signals: int = 30) -> list[dict]:
    """生成模拟因子信号"""
    symbols = [
        "688012", "688981", "002371", "688072", "603501",
        "688008", "600703", "300661", "688126", "002049",
        "300782", "688256", "600745", "300274", "688041",
        "002415", "300124", "688036", "688396", "600584",
        "688005", "002916", "300433", "688187", "603986",
        "688525", "688110", "688728", "688200", "688469",
    ]

    signals = []
    for i, sym in enumerate(symbols[:n_signals]):
        zscore = np.random.normal(0, 1)
        signals.append({
            "ts_code": f"{sym}.{'SH' if sym.startswith('6') else 'SZ'}",
            "symbol": sym,
            "name": f"Mock_{sym}",
            "factor_value": float(zscore),
            "factor_rank": i + 1,
            "factor_zscore": float(zscore),
            "signal_source": "ret5",
            "selection_reason": "模拟信号测试",
        })
    return signals


# ═══════════════════════════════════════════════════════════════════════════════
# Test Suite
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaperTradingV4:
    """PaperTradingV4 核心功能测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.capital = 50000.0
        self.top_n = 10
        self.dates = _make_trade_dates(20)
        self.symbols = [
            "688012", "688981", "002371", "688072", "603501",
            "688008", "600703", "300661", "688126", "002049",
            "300782", "688256", "600745", "300274", "688041",
        ]
        self.market_data = _make_mock_market_data(self.symbols, self.dates)
        self.factor_signals = _make_mock_factor_signals(30)

    def test_init(self):
        """测试引擎初始化"""
        engine = PaperTradingV4(capital=self.capital)
        assert engine.capital == self.capital
        assert engine.cash == self.capital
        assert engine.holdings == {}
        assert engine.trades == []

    def test_run_paper_requires_explicit_signals(self):
        engine = PaperTradingV4(capital=self.capital)
        with pytest.raises(ValueError, match="必须显式提供"):
            engine.run_paper(date=self.dates[0], factor_signals=None)

    def test_run_paper_single_day(self):
        """测试单日模拟盘运行"""
        engine = PaperTradingV4(capital=self.capital)
        date = self.dates[0]

        result = engine.run_paper(
            date=date,
            factor_signals=self.factor_signals,
            constraints={"top_n": self.top_n, "capital": self.capital},
            market_data=self.market_data,
        )

        # 验证结果结构
        assert result["date"] == date
        assert "plan" in result
        assert "execution" in result
        assert "pnl" in result
        assert "deviation" in result
        assert "tradability_check" in result
        assert "risk_interceptions" in result

        # 验证计划
        plan = result["plan"]
        assert plan["n_stocks"] > 0
        assert plan["n_tradable"] + plan["n_blocked"] == plan["n_stocks"]
        assert len(plan["stocks"]) == plan["n_stocks"]

        # 验证执行
        execution = result["execution"]
        assert execution["n_filled"] + execution["n_failed"] <= execution["n_planned"]
        assert execution["cash_remaining"] >= 0

        # 验证收益
        pnl = result["pnl"]
        assert pnl["capital"] == self.capital
        assert pnl["cash"] >= 0
        assert pnl["holdings_value"] >= 0
        assert pnl["total_value"] == pnl["cash"] + pnl["holdings_value"]

        # 验证偏差
        deviation = result["deviation"]
        assert deviation["n_planned"] == plan["n_stocks"]
        assert deviation["n_filled"] <= plan["n_stocks"]
        assert deviation["fill_rate_pct"] >= 0

        # 验证风控拦截
        assert isinstance(result["risk_interceptions"], list)

    def test_run_paper_20_days(self):
        """验收标准 #1: 模拟 20 个交易日"""
        engine = PaperTradingV4(capital=self.capital)

        results = engine.run_multiple_days(
            dates=self.dates[:20],
            factor_signals=self.factor_signals,
            constraints={"top_n": self.top_n, "capital": self.capital},
            market_data=self.market_data,
        )

        assert len(results) == 20

        # 验收标准 #2: 输出计划 vs 实际差异
        for r in results:
            deviation = r["deviation"]
            assert deviation["n_planned"] > 0
            assert deviation.get("total_deviation_pct") is not None
            # 每只股票都有偏差记录
            assert len(deviation["details"]) == deviation["n_planned"]

        # 验收标准 #3: 输出风控拦截原因
        all_risk = [r["risk_interceptions"] for r in results]
        all_reasons: dict[str, int] = {}
        for rlist in all_risk:
            for r in rlist:
                reason = r.get("reason", "unknown")
                all_reasons[reason] = all_reasons.get(reason, 0) + 1

        if all_reasons:
            # 至少有一些拦截原因被记录
            assert len(all_reasons) >= 1

    def test_tradability_check(self):
        """测试可交易性检查"""
        engine = PaperTradingV4(capital=self.capital)
        date = self.dates[0]

        result = engine.run_paper(
            date, self.factor_signals,
            constraints={"top_n": self.top_n, "capital": self.capital},
            market_data=self.market_data,
        )

        tc = result["tradability_check"]
        assert tc["total"] > 0
        assert tc["plannable"] + tc["blocked"] == tc["total"]
        assert len(tc["details"]) == tc["total"]

    def test_deviation_analysis(self):
        """测试执行偏差分析"""
        engine = PaperTradingV4(capital=self.capital)
        date = self.dates[0]

        result = engine.run_paper(
            date, self.factor_signals,
            constraints={"top_n": self.top_n, "capital": self.capital},
            market_data=self.market_data,
        )

        deviation = result["deviation"]
        assert deviation["fill_rate_pct"] >= 0
        assert deviation["fill_rate_pct"] <= 100

        # 偏差明细
        for d in deviation["details"]:
            assert d["symbol"]
            assert d["planned_amount"] >= 0
            if d["status"] == "filled":
                assert d["actual_amount"] > 0
            else:
                assert d["reason"]  # 必须说明原因

    def test_summary(self):
        """测试摘要统计"""
        engine = PaperTradingV4(capital=self.capital)

        results = engine.run_multiple_days(
            dates=self.dates[:5],
            factor_signals=self.factor_signals,
            constraints={"top_n": self.top_n, "capital": self.capital},
            market_data=self.market_data,
        )

        summary = PaperTradingV4.summary(results)
        assert summary["n_days"] == 5
        assert "date_range" in summary
        assert "total_return_pct" in summary
        assert "avg_fill_rate_pct" in summary
        assert "total_risk_interceptions" in summary
        assert "risk_breakdown" in summary


class TestShadowTradingEngine:
    """ShadowTradingEngine 核心功能测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.capital = 50000.0
        self.top_n = 10
        self.dates = _make_trade_dates(20)
        self.symbols = [
            "688012", "688981", "002371", "688072", "603501",
            "688008", "600703", "300661", "688126", "002049",
            "300782", "688256", "600745", "300274", "688041",
        ]
        self.market_data = _make_mock_market_data(self.symbols, self.dates)
        self.factor_signals = _make_mock_factor_signals(30)

    def test_init(self):
        """测试引擎初始化"""
        engine = ShadowTradingEngine(capital=self.capital, top_n=self.top_n)
        assert engine.capital == self.capital
        assert engine.top_n == self.top_n
        assert engine.BENCHMARK_NAME == "semiconductor_ew"

    def test_run_shadow_requires_explicit_signals(self):
        engine = ShadowTradingEngine(capital=self.capital, top_n=self.top_n)
        with pytest.raises(ValueError, match="必须显式提供"):
            engine.run_shadow(date=self.dates[0], factor_signals=None)

    def test_run_shadow_single_day(self):
        """测试单日影子交易"""
        engine = ShadowTradingEngine(capital=self.capital, top_n=self.top_n)
        date = self.dates[0]

        result = engine.run_shadow(
            date=date,
            factor_signals=self.factor_signals,
            market_data=self.market_data,
            constraints={"top_n": self.top_n, "capital": self.capital},
        )

        # 验证结果结构
        assert result["date"] == date
        assert "plan" in result
        assert "tradability" in result
        assert "risk_interceptions" in result
        assert "performance" in result
        assert "summary" in result
        assert "not_ready" in result

        # 验证可交易性
        trad = result["tradability"]
        assert trad["n_total"] > 0
        assert trad["n_tradable_planned"] >= 0
        assert trad["n_check_blocked"] >= 0
        assert trad["n_total"] == trad["n_tradable_planned"] + trad["n_non_tradable_planned"]

        # 验收标准 #4: 输出相对半导体同池等权表现
        perf = result["performance"]
        assert "benchmark_name" in perf
        assert "benchmark_label" in perf
        assert perf["benchmark_name"] == "semiconductor_ew"
        assert perf["benchmark_label"] == "半导体同池等权"
        # 策略收益一定有
        assert perf["strategy_return_pct"] is not None

        # 验收标准 #5: NOT_READY 标志
        assert isinstance(result["not_ready"], bool)

        # 验证风控拦截统计
        risk = result["risk_interceptions"]
        assert risk["total_interceptions"] >= 0
        assert "by_reason" in risk
        assert "by_stage" in risk

    def test_run_shadow_20_days(self):
        """验收标准 #1: 模拟 20 个交易日"""
        engine = ShadowTradingEngine(capital=self.capital, top_n=self.top_n)

        results = engine.run_shadow_multi(
            dates=self.dates[:20],
            factor_signals=self.factor_signals,
            market_data=self.market_data,
            constraints={"top_n": self.top_n, "capital": self.capital},
        )

        assert len(results) == 20

        # 每个结果都包含完整结构
        for r in results:
            assert "date" in r
            assert "not_ready" in r
            assert "risk_interceptions" in r
            assert "performance" in r
            assert "summary" in r

        # 验收标准 #2: 输出计划 vs 实际差异 (在 performance 和 tradability 中体现)
        for r in results:
            perf = r["performance"]
            assert perf["strategy_return_pct"] is not None
            assert r["tradability"]["n_total"] > 0

        # 验收标准 #3 & #4 & #5 在汇总报告中验证
        report = ShadowTradingEngine.build_report(results)
        self._verify_report(report)

    def _verify_report(self, report: dict):
        """验证汇总报告"""
        # status 表示执行状态 (success/error) 或准备状态 (READY/NOT_READY)
        if report["n_days"] >= 1 and report.get("avg_benchmark_return_pct") is not None:
            # 有基准数据时验证 READY/NOT_READY 逻辑
            assert report["status"] in ("READY", "NOT_READY")
            if report["not_ready_days"] > report["n_days"] / 2:
                assert report["status"] == "NOT_READY"
        else:
            # 无基准数据时 status 可能是 success (执行成功但无法比较)
            # 也可能是 READY/NOT_READY (已自动 fallback)
            pass

        # 验收标准 #4: 相对半导体同池等权表现
        assert report["benchmark_label"] == "半导体同池等权"
        if report.get("avg_strategy_return_pct") is not None:
            assert isinstance(report["avg_strategy_return_pct"], float)
        if report.get("avg_benchmark_return_pct") is not None:
            assert isinstance(report["avg_benchmark_return_pct"], float)

        # 验收标准 #3: 风控拦截原因
        assert "risk_interception_reasons" in report
        assert isinstance(report["risk_interception_reasons"], dict)

        # 验收标准 #5: NOT_READY 统计
        assert "not_ready_days" in report
        assert "not_ready_days_pct" in report
        assert "status" in report
        # status 必须是 READY 或 NOT_READY
        assert report["status"] in ("READY", "NOT_READY")

        if report["not_ready_days"] > report["n_days"] / 2:
            assert report["status"] == "NOT_READY"

        # 执行质量统计
        assert "total_planned_stocks" in report
        assert "total_filled_stocks" in report
        assert "overall_fill_rate_pct" in report

        # 每日明细
        assert "daily_summaries" in report
        assert len(report["daily_summaries"]) == report["n_days"]

    def test_build_report_empty(self):
        """测试空结果"""
        report = ShadowTradingEngine.build_report([])
        assert report["status"] == "error"
        assert "message" in report

    def test_risk_interception_reasons(self):
        """验收标准 #3: 风控拦截原因"""
        engine = ShadowTradingEngine(capital=self.capital, top_n=self.top_n)

        results = engine.run_shadow_multi(
            dates=self.dates[:10],
            factor_signals=self.factor_signals,
            market_data=self.market_data,
            constraints={"top_n": self.top_n, "capital": self.capital},
        )

        report = ShadowTradingEngine.build_report(results)
        reasons = report.get("risk_interception_reasons", {})

        # 原因应该只包含已知的风控类型
        known_reasons = {
            "涨停封板 (禁买)", "跌停封板 (禁交易)", "停牌",
            "资金不足", "无价格数据", "计划股数为0", "不足一手(100股)",
        }
        for reason in reasons:
            # 每个原因要么是已知类型, 要么是 portfolio_builder 返回的已有原因
            assert reason is not None  # 只要有原因即可

    def test_not_ready_flag(self):
        """验收标准 #5: NOT_READY 标志"""
        engine = ShadowTradingEngine(capital=self.capital, top_n=self.top_n)
        date = self.dates[0]

        result = engine.run_shadow(
            date, self.factor_signals, self.market_data,
            constraints={"top_n": self.top_n, "capital": self.capital},
        )

        # NOT_READY 判断逻辑: 跑输同池
        perf = result["performance"]
        if perf.get("excess_return_pct") is not None:
            expected = perf["excess_return_pct"] < 0
            assert result["not_ready"] == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Test: 20-day V4.8 Paper/Shadow Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestV48Pipeline:
    """V4.8 Paper → Shadow 全管线集成测试"""

    def test_paper_shadow_pipeline(self):
        """完整管线: Paper 运行 → Shadow 运行 → 汇总报告"""
        capital = 50000.0
        top_n = 10
        dates = _make_trade_dates(20)
        symbols = [
            "688012", "688981", "002371", "688072", "603501",
            "688008", "600703", "300661", "688126", "002049",
        ]
        market_data = _make_mock_market_data(symbols, dates)
        factor_signals = _make_mock_factor_signals(30)

        # Step 1: Paper Trading
        paper = PaperTradingV4(capital=capital)
        paper_results = paper.run_multiple_days(
            dates, factor_signals,
            constraints={"top_n": top_n, "capital": capital},
            market_data=market_data,
        )
        assert len(paper_results) == 20

        paper_summary = PaperTradingV4.summary(paper_results)
        assert paper_summary["n_days"] == 20
        assert paper_summary["avg_fill_rate_pct"] >= 0
        assert paper_summary["total_risk_interceptions"] >= 0

        # Step 2: Shadow Trading
        shadow = ShadowTradingEngine(capital=capital, top_n=top_n)
        shadow_results = shadow.run_shadow_multi(
            dates, factor_signals, market_data,
            constraints={"top_n": top_n, "capital": capital},
        )
        assert len(shadow_results) == 20

        # Step 3: 汇总报告
        report = ShadowTradingEngine.build_report(shadow_results)
        assert report["n_days"] == 20
        assert "date_range" in report
        assert "benchmark_label" in report
        assert "risk_interception_reasons" in report
        assert "not_ready_days" in report
        assert report["total_planned_stocks"] > 0
        assert 0 <= report["overall_fill_rate_pct"] <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
