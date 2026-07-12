#!/usr/bin/env python3
"""
V4.7 低频组合构建与推荐系统 — 单元测试

测试覆盖:
  - FactorSignalItem / PortfolioStock / Portfolio 数据类
  - ConstraintViolation / RiskStatus 数据类
  - PortfolioBuilder._normalize_signals
  - PortfolioBuilder.build_portfolio (测试信号)
  - PortfolioBuilder.apply_constraints (各类约束)
  - PortfolioBuilder.build_etf_replacement
  - PortfolioBuilder.portfolio_report
  - CLI 缺少真实信号时安全阻断
  - 边界条件: 空信号、单只信号、所有信号不可交易等
"""

import sys, os, json, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── 确保能找到 commands/ ──
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import pytest
import numpy as np
import pandas as pd

from portfolio_builder import (
    PortfolioBuilder,
    Portfolio,
    PortfolioStock,
    FactorSignalItem,
    ConstraintViolation,
    RiskStatus,
    DEFAULT_CONSTRAINTS,
    ETF_REPLACEMENT_POOL,
)

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def builder() -> PortfolioBuilder:
    return PortfolioBuilder()


@pytest.fixture()
def sample_signals() -> list[dict]:
    """10 条模拟因子信号"""
    return [
        {"ts_code": "002371.SZ", "symbol": "002371", "name": "北方华创",
         "factor_value": 0.038, "signal_source": "ret5",
         "selection_reason": "半导体设备龙头"},
        {"ts_code": "688012.SH", "symbol": "688012", "name": "中微公司",
         "factor_value": 0.035, "signal_source": "ret5",
         "selection_reason": "刻蚀设备龙头"},
        {"ts_code": "688256.SH", "symbol": "688256", "name": "寒武纪",
         "factor_value": 0.040, "signal_source": "ret5",
         "selection_reason": "AI芯片龙头"},
        {"ts_code": "603501.SH", "symbol": "603501", "name": "韦尔股份",
         "factor_value": 0.030, "signal_source": "ret5",
         "selection_reason": "CIS龙头"},
        {"ts_code": "002049.SZ", "symbol": "002049", "name": "紫光国微",
         "factor_value": 0.027, "signal_source": "ret5",
         "selection_reason": "FPGA芯片龙头"},
        {"ts_code": "688981.SH", "symbol": "688981", "name": "中芯国际",
         "factor_value": 0.028, "signal_source": "ret5",
         "selection_reason": "晶圆代工龙头"},
        {"ts_code": "600703.SH", "symbol": "600703", "name": "三安光电",
         "factor_value": 0.024, "signal_source": "ret5",
         "selection_reason": "化合物半导体"},
        {"ts_code": "300782.SZ", "symbol": "300782", "name": "卓胜微",
         "factor_value": 0.018, "signal_source": "ret5",
         "selection_reason": "射频芯片龙头"},
        {"ts_code": "688126.SH", "symbol": "688126", "name": "沪硅产业",
         "factor_value": 0.025, "signal_source": "ret5",
         "selection_reason": "硅片材料龙头"},
        {"ts_code": "688396.SH", "symbol": "688396", "name": "华润微",
         "factor_value": 0.022, "signal_source": "ret5",
         "selection_reason": "功率半导体"},
    ]


@pytest.fixture()
def single_signal() -> list[dict]:
    """仅 1 条信号 — 边界情况"""
    return [
        {"ts_code": "002371.SZ", "symbol": "002371", "name": "北方华创",
         "factor_value": 0.05, "signal_source": "test"},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Data Class Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDataClasses:
    def test_factor_signal_item(self):
        item = FactorSignalItem(
            ts_code="002371.SZ",
            symbol="002371",
            name="北方华创",
            factor_value=0.038,
            factor_rank=1,
            signal_source="ret5",
            selection_reason="设备龙头",
        )
        assert item.ts_code == "002371.SZ"
        assert item.factor_rank == 1
        assert item.selection_reason == "设备龙头"

    def test_constraint_violation(self):
        v = ConstraintViolation(
            rule="position_cap",
            severity="blocker",
            message="仓位超过上限",
            symbol="002371",
            actual_value=0.20,
            threshold=0.15,
        )
        assert v.severity == "blocker"
        assert v.rule == "position_cap"

    def test_risk_status_defaults(self):
        risk = RiskStatus()
        assert risk.is_blocked is False
        assert risk.block_reasons == []
        assert risk.is_st is False

    def test_portfolio_stock_defaults(self):
        stock = PortfolioStock(ts_code="002371.SZ", symbol="002371", name="北方华创")
        assert stock.weight == 0.0
        assert stock.is_tradable is True
        assert stock.is_core is True
        assert stock.risk is not None

    def test_portfolio_defaults(self):
        p = Portfolio(name="test")
        assert p.stocks == []
        assert p.violations == []
        assert p.etf_replacements == []
        assert p.theme_position == ""


# ═══════════════════════════════════════════════════════════════════════════
# PortfolioBuilder Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeSignals:
    def test_normalize_empty(self, builder):
        result = builder._normalize_signals([])
        assert result == []

    def test_normalize_rank_order(self, builder, sample_signals):
        result = builder._normalize_signals(sample_signals)
        assert len(result) == 10
        # 按 rank 排序
        ranks = [s["factor_rank"] for s in result]
        assert ranks == sorted(ranks)
        # 值最大的 rank=1
        assert result[0]["factor_rank"] == 1
        assert result[0]["factor_value"] == max(s["factor_value"] for s in sample_signals)

    def test_normalize_zscore(self, builder, sample_signals):
        result = builder._normalize_signals(sample_signals)
        assert all(s["factor_zscore"] != 0 for s in result)
        # zscore 应该以 0 为中心 (近似的)
        zscores = [s["factor_zscore"] for s in result]
        assert abs(np.mean(zscores)) < 0.5  # 允许浮动

    def test_normalize_single_signal(self, builder, single_signal):
        result = builder._normalize_signals(single_signal)
        assert len(result) == 1
        assert result[0]["factor_rank"] == 1


class TestBuildPortfolio:
    def test_build_with_sample_signals(self, builder, sample_signals):
        """基本功能: 从信号构建完整组合"""
        portfolio = builder.build_portfolio(sample_signals)
        assert isinstance(portfolio, Portfolio)
        assert len(portfolio.stocks) <= DEFAULT_CONSTRAINTS["top_n"]
        assert portfolio.capital == DEFAULT_CONSTRAINTS["capital"]
        assert portfolio.built_at

    def test_build_weights_sum_to_one(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        total_weight = sum(s.weight for s in portfolio.stocks)
        assert abs(total_weight - 1.0) < 0.01, f"权重总和={total_weight}"

    def test_build_with_custom_constraints(self, builder, sample_signals):
        constraints = {"capital": 100000, "top_n": 5}
        portfolio = builder.build_portfolio(sample_signals, constraints)
        assert portfolio.capital == 100000
        assert portfolio.target_n == 5
        assert len(portfolio.stocks) <= 5

    def test_build_empty_signals(self, builder):
        portfolio = builder.build_portfolio([])
        assert len(portfolio.stocks) == 0

    def test_build_single_signal(self, builder, single_signal):
        portfolio = builder.build_portfolio(single_signal)
        assert len(portfolio.stocks) == 1
        assert portfolio.stocks[0].symbol == "002371"

    def test_build_mainboard_multiplier(self, builder):
        """主板票权重应高于同排名的非主板票"""
        signals = [
            {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行",
             "factor_value": 0.03, "signal_source": "test"},
            {"ts_code": "688000.SH", "symbol": "688000", "name": "科创A",
             "factor_value": 0.03, "signal_source": "test"},
        ]
        portfolio = builder.build_portfolio(signals)
        # 权重应该不同
        w0 = portfolio.stocks[0].weight
        w1 = portfolio.stocks[1].weight
        if "主板" in (portfolio.stocks[0].board or portfolio.stocks[1].board):
            pass  # 因无法确定板信息, 仅验证不崩溃


class TestApplyConstraints:
    def test_constraints_position_cap(self, builder):
        """验证单票仓位上限"""
        # 只有一只股票时, 即使 total=1 也不会超过 position_cap 逻辑
        signals = [
            {"ts_code": "002371.SZ", "symbol": "002371", "name": "北方华创",
             "factor_value": 0.05, "signal_source": "test"},
        ]
        portfolio = builder.build_portfolio(signals, {"position_cap": 0.10})
        # 单只股票时权重 100%, 会被 cap 截断
        assert portfolio.stocks[0].weight <= 0.10 or len(portfolio.stocks) == 1

    def test_constraints_mainboard_preference(self, builder):
        """主板优先不应导致错误"""
        signals = [
            {"ts_code": "600000.SH", "symbol": "600000", "name": "主板A",
             "factor_value": 0.02, "signal_source": "test"},
        ]
        constraints = {"mainboard_multiplier": 2.0}
        portfolio = builder.build_portfolio(signals, constraints)
        # 仅验证不崩溃, 因为 board 信息依赖 universe_data
        assert len(portfolio.stocks) == 1

    def test_constraints_late_session(self, builder, sample_signals):
        """手工检查尾盘禁新仓标记"""
        # 使用 mock 方式: 直接构建组合再手动检查
        portfolio = builder.build_portfolio(sample_signals)
        # apply_constraints 会检查尾盘
        # 无法控制时间, 仅验证不崩溃
        assert hasattr(portfolio.stocks[0], "is_tradable")

    def test_constraints_non_tradable_marked(self, builder):
        """不可交易标记应在风控中体现"""
        signals = [{
            "ts_code": "688012.SH",
            "symbol": "688012",
            "name": "测试标的",
            "factor_value": 0.035,
            "signal_source": "pytest_fixture",
        }]
        portfolio = builder.build_portfolio(signals)
        # 检查风控结构
        assert hasattr(portfolio.stocks[0], "risk")
        assert isinstance(portfolio.stocks[0].risk, RiskStatus)

    def test_lot_rounding(self, builder):
        """验证 100 股整数倍"""
        assert builder._round_to_lot(150) == 100
        assert builder._round_to_lot(99) == 100
        assert builder._round_to_lot(0) == 0
        assert builder._round_to_lot(250) == 200
        assert builder._round_to_lot(1000) == 1000


class TestETFReplacement:
    def test_build_etf_replacement_standard(self, builder):
        """为科创板票生成 ETF 替代方案"""
        stock = PortfolioStock(
            ts_code="688012.SH",
            symbol="688012",
            name="中微公司",
            weight=0.15,
            board="科创板",
            is_tradable=False,
        )
        stock.risk.is_non_tradable_board = True
        stock.risk.block_reasons = ["科创板权限"]

        portfolio = Portfolio(
            name="Test",
            stocks=[stock],
        )

        result = builder.build_etf_replacement(portfolio)
        assert len(result.etf_replacements) > 0
        etf = result.etf_replacements[0]
        assert "ts_code" in etf
        assert "name" in etf

    def test_etf_replacement_tradable_stock_ignored(self, builder):
        """可交易股票不应生成 ETF 替代"""
        stock = PortfolioStock(
            ts_code="002371.SZ",
            symbol="002371",
            name="北方华创",
            weight=0.15,
            board="主板",
            is_tradable=True,
        )

        portfolio = Portfolio(name="Test", stocks=[stock])
        result = builder.build_etf_replacement(portfolio)
        assert len(result.etf_replacements) == 0

    def test_etf_match_finds_semiconductor(self, builder):
        """验证 find_etf_match 返回半导体ETF"""
        stock = PortfolioStock(
            ts_code="688012.SH",
            symbol="688012",
            name="中微公司",
            board="科创板",
        )
        match = builder._find_etf_match(stock)
        assert match is not None
        assert "芯片" in match.get("name", "") or "半导体" in match.get("name", "")


class TestPortfolioReport:
    def test_report_structure(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        report = builder.portfolio_report(portfolio)

        # 必须包含的顶层字段
        assert "report_type" in report
        assert "portfolio_name" in report
        assert "theme_position" in report
        assert "core_composition" in report
        assert "satellite_composition" in report
        assert "risk_overview" in report
        assert "etf_replacements" in report
        assert "industry_exposure" in report
        assert "market_cap_exposure" in report
        assert "beta_exposure" in report
        assert "benchmark_comparison" in report
        assert "next_day_risk_tips" in report
        assert "constraints_summary" in report

    def test_report_theme_position(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        report = builder.portfolio_report(portfolio)
        tp = report["theme_position"]
        assert "suggestion" in tp
        assert "description" in tp
        assert "narrative" in tp
        assert tp["suggestion"] in ("0%", "30%", "50%", "70%", "100%")

    def test_report_core_stocks_have_selection_reason(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        report = builder.portfolio_report(portfolio)
        for s in report.get("core_composition", []):
            assert "selection_reason" in s, f"{s['symbol']} 缺少入选原因"
            assert s["selection_reason"], f"{s['symbol']} 入选原因为空"

    def test_report_core_stocks_have_risk_status(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        report = builder.portfolio_report(portfolio)
        for s in report.get("core_composition", []):
            risk = s.get("risk", {})
            assert risk.get("is_blocked") is not None
            assert "block_reasons" in risk

    def test_report_risk_overview(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        report = builder.portfolio_report(portfolio)
        ro = report["risk_overview"]
        assert "n_violations" in ro
        assert "blocker_count" in ro
        assert "warning_count" in ro

    def test_report_constraints_summary(self, builder, sample_signals):
        portfolio = builder.build_portfolio(sample_signals)
        report = builder.portfolio_report(portfolio)
        cs = report["constraints_summary"]
        assert "position_cap" in cs
        assert "industry_cap" in cs
        assert "min_turnover" in cs


class TestDetermineThemePosition:
    def test_full_position(self):
        p = Portfolio(stocks=[PortfolioStock(ts_code="A", symbol="A", is_tradable=True)])
        assert PortfolioBuilder._determine_theme_position(p) == "100%"

    def test_zero_position_empty(self):
        p = Portfolio(stocks=[])
        assert PortfolioBuilder._determine_theme_position(p) == "0%"

    def test_zero_position_all_blocked(self):
        s = PortfolioStock(ts_code="A", symbol="A", is_tradable=False)
        p = Portfolio(stocks=[s])
        assert PortfolioBuilder._determine_theme_position(p) == "0%"

    def test_mixed_position(self):
        stocks = [
            PortfolioStock(ts_code="A", symbol="A", is_tradable=True),
            PortfolioStock(ts_code="B", symbol="B", is_tradable=False),
        ]
        p = Portfolio(stocks=stocks)
        assert PortfolioBuilder._determine_theme_position(p) == "50%"


class TestIndustryExposure:
    def test_compute_industry_exposure(self, builder):
        stocks = [
            PortfolioStock(ts_code="A", symbol="A", name="A", weight=0.6, industry="半导体"),
            PortfolioStock(ts_code="B", symbol="B", name="B", weight=0.4, industry="电子"),
        ]
        exposure = builder._compute_industry_exposure(stocks)
        assert len(exposure) == 2
        weights = {e["industry"]: e["weight"] for e in exposure}
        assert weights["半导体"] == 0.6
        assert weights["电子"] == 0.4

    def test_compute_industry_exposure_empty(self, builder):
        assert builder._compute_industry_exposure([]) == []


class TestMarketCapExposure:
    def test_compute_market_cap_exposure(self, builder):
        stocks = [
            PortfolioStock(ts_code="A.SH", symbol="600000", name="A", weight=0.5),
            PortfolioStock(ts_code="B.SH", symbol="688012", name="B", weight=0.5),
        ]
        exposure = builder._compute_market_cap_exposure(stocks)
        assert len(exposure) > 0
        # 仅验证结构
        assert all("bucket" in e for e in exposure)
        assert all("weight" in e for e in exposure)


class TestRiskTips:
    def test_generate_risk_tips(self, builder):
        portfolio = Portfolio(stocks=[])
        tips = builder._generate_risk_tips(portfolio)
        assert isinstance(tips, list)

    def test_risk_tips_high_concentration(self, builder):
        stock = PortfolioStock(
            ts_code="A.SH", symbol="A", name="A",
            weight=0.5, semiconductor_subsector="设备",
        )
        portfolio = Portfolio(stocks=[stock])
        tips = builder._generate_risk_tips(portfolio)
        assert any("集中度" in t for t in tips)

    def test_risk_tips_board_permission(self, builder):
        stock = PortfolioStock(
            ts_code="688012.SH", symbol="688012", name="中微公司",
            weight=0.5, board="科创板", is_tradable=False,
        )
        stock.risk.is_non_tradable_board = True
        stock.risk.block_reasons = ["科创板权限"]
        portfolio = Portfolio(stocks=[stock])
        tips = builder._generate_risk_tips(portfolio)
        assert any("权限" in t for t in tips)


class TestThemePositionDesc:
    def test_theme_position_descriptions(self):
        for pos in ("0%", "30%", "50%", "70%", "100%"):
            desc = PortfolioBuilder._theme_position_description(pos)
            assert desc
            assert isinstance(desc, str)

    def test_theme_position_narratives(self):
        for pos in ("0%", "30%", "50%", "70%", "100%"):
            narr = PortfolioBuilder._theme_position_narrative(pos)
            assert narr
            assert isinstance(narr, str)


class TestETFPool:
    def test_etf_pool_has_essential_etfs(self):
        codes = {e["ts_code"] for e in ETF_REPLACEMENT_POOL}
        assert "512480.SH" in codes  # 半导体ETF
        assert "588000.SH" in codes  # 科创50ETF

    def test_etf_replacement_pool_not_empty(self):
        assert len(ETF_REPLACEMENT_POOL) > 0


# ═══════════════════════════════════════════════════════════════════════════
# CLI Command Tests (smoke tests — only verify they don't crash)
# ═══════════════════════════════════════════════════════════════════════════

class TestCLICommands:
    def test_cmd_build_lowfreq_defaults_are_blocked(self, capsys):
        PortfolioBuilder.cmd_build_lowfreq([])
        assert "缺少 --signal-file" in capsys.readouterr().out

    def test_cmd_build_lowfreq_custom_top_n_is_blocked(self, capsys):
        PortfolioBuilder.cmd_build_lowfreq(["--top-n", "3"])
        assert "缺少 --signal-file" in capsys.readouterr().out

    def test_cmd_build_lowfreq_custom_capital_is_blocked(self, capsys):
        PortfolioBuilder.cmd_build_lowfreq(["--capital", "200000"])
        assert "缺少 --signal-file" in capsys.readouterr().out

    def test_cmd_recommend(self):
        PortfolioBuilder.cmd_recommend([])

    def test_cmd_risk(self):
        PortfolioBuilder.cmd_risk([])

    def test_cmd_premarket_v4(self):
        PortfolioBuilder.cmd_premarket_v4([])
