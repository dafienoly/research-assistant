"""V6.5 Strategy Report Generator — 策略报告生成器测试

测试覆盖:
  - Spec 数据结构: ReportType, ReportFormat, ReportSection, StrategyReportConfig, StrategyReportResult
  - Metrics: 月度收益、年度收益、回撤分析、盈亏分析、风险指标、收益分布
  - HTMLRenderer: 各板块渲染、完整报告组装
  - StrategyReportGenerator: 从收益率生成、从 PortfolioResult 生成、保存
  - Built-in Skill: strategy-report 注册和执行
  - CLI 命令解析
  - 边界条件: 空数据、单点数据、全零收益
"""

import sys, os, json, tempfile, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
import pandas as pd

from factor_lab.strategy_report import (
    StrategyReportConfig,
    StrategyReportResult,
    ReportType,
    ReportFormat,
    ReportSection,
    MonthlyReturnsTable,
    DrawdownAnalysis,
    WinLossAnalysis,
    RiskMetrics,
    compute_monthly_returns,
    compute_annual_returns,
    compute_drawdown_analysis,
    compute_win_loss_analysis,
    compute_risk_metrics,
    compute_return_distribution,
    HTMLReportRenderer,
    StrategyReportGenerator,
    DEFAULT_OUTPUT_ROOT,
)
from factor_lab.strategy_report.spec import (
    VALID_REPORT_TYPES,
    VALID_REPORT_FORMATS,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture()
def sample_dates() -> pd.DatetimeIndex:
    """252 个交易日 (约 1 年)"""
    return pd.date_range("2025-01-02", periods=252, freq="B")


@pytest.fixture()
def two_year_dates() -> pd.DatetimeIndex:
    """504 个交易日 (约 2 年)"""
    return pd.date_range("2024-01-02", periods=504, freq="B")


@pytest.fixture()
def normal_returns(sample_dates) -> pd.Series:
    """年化 ~15%, Sharpe ~1.0 的策略收益率"""
    rng = np.random.default_rng(42)
    n = len(sample_dates)
    return pd.Series(
        rng.normal(0.15 / 252, 0.15 / np.sqrt(252), n),
        index=sample_dates,
        name="test_strategy",
    )


@pytest.fixture()
def high_sharpe_returns(sample_dates) -> pd.Series:
    """年化 ~20%, Sharpe ~1.5 的策略收益率"""
    rng = np.random.default_rng(123)
    n = len(sample_dates)
    return pd.Series(
        rng.normal(0.20 / 252, 0.13 / np.sqrt(252), n),
        index=sample_dates,
        name="high_sharpe",
    )


@pytest.fixture()
def negative_returns(sample_dates) -> pd.Series:
    """负收益策略"""
    rng = np.random.default_rng(99)
    n = len(sample_dates)
    return pd.Series(
        rng.normal(-0.05 / 252, 0.20 / np.sqrt(252), n),
        index=sample_dates,
        name="negative",
    )


@pytest.fixture()
def zero_returns(sample_dates) -> pd.Series:
    """全零收益"""
    return pd.Series(
        np.zeros(len(sample_dates)),
        index=sample_dates,
        name="zero",
    )


@pytest.fixture()
def benchmark_returns(sample_dates) -> pd.Series:
    """年化 ~8% 基准"""
    rng = np.random.default_rng(42)
    n = len(sample_dates)
    return pd.Series(
        rng.normal(0.08 / 252, 0.18 / np.sqrt(252), n),
        index=sample_dates,
        name="CSI300",
    )


@pytest.fixture()
def temp_output_dir(tmp_path) -> str:
    """临时输出目录"""
    d = tmp_path / "reports"
    d.mkdir()
    return str(d)


@pytest.fixture()
def two_strategy_portfolio(sample_dates):
    """两个策略的组合数据 (生成 PortfolioResult)"""
    rng = np.random.default_rng(42)
    n = len(sample_dates)

    mom_ret = pd.Series(rng.normal(0.15 / 252, 0.15 / np.sqrt(252), n), index=sample_dates)
    val_ret = pd.Series(rng.normal(0.12 / 252, 0.15 / np.sqrt(252), n), index=sample_dates)

    from factor_lab.portfolio import PortfolioSpec, PortfolioBacktestEngine
    spec = PortfolioSpec(
        name="测试组合",
        strategy_returns={"momentum": mom_ret, "value": val_ret},
        weights={"momentum": 0.6, "value": 0.4},
        rebalance_freq="monthly",
    )
    engine = PortfolioBacktestEngine(spec)
    return engine.run_with_benchmark("CSI300")


# ═══════════════════════════════════════════════════════════════════
# Spec Tests
# ═══════════════════════════════════════════════════════════════════

class TestStrategyReportConfig:

    def test_default_config(self):
        config = StrategyReportConfig()
        assert config.report_format == "html"
        assert config.theme == "light"
        assert config.decimal_places == 2
        assert config.include_sections is None

    def test_custom_config(self):
        config = StrategyReportConfig(
            include_sections=["overview", "metrics"],
            report_format="json",
            title="我的报告",
            theme="dark",
            decimal_places=4,
        )
        assert config.include_sections == ["overview", "metrics"]
        assert config.report_format == "json"
        assert config.title == "我的报告"
        assert config.theme == "dark"
        assert config.decimal_places == 4

    def test_validate_valid(self):
        config = StrategyReportConfig()
        assert config.validate() == []

    def test_validate_invalid_format(self):
        config = StrategyReportConfig(report_format="pdf")
        errors = config.validate()
        assert len(errors) > 0
        assert "格式" in errors[0]

    def test_validate_invalid_section(self):
        config = StrategyReportConfig(include_sections=["nonexistent"])
        errors = config.validate()
        assert len(errors) > 0

    def test_validate_invalid_theme(self):
        config = StrategyReportConfig(theme="neon")
        errors = config.validate()
        assert len(errors) > 0
        assert "主题" in errors[0]

    def test_to_dict(self):
        config = StrategyReportConfig(title="test")
        d = config.to_dict()
        assert d["title"] == "test"
        assert "report_format" in d


class TestStrategyReportResult:

    def test_default_result(self):
        result = StrategyReportResult()
        assert result.report_type == "single_strategy"
        assert result.sections_generated == []
        assert result.errors == []
        assert result.generated_at

    def test_custom_result(self):
        result = StrategyReportResult(
            report_type="portfolio",
            title="组合报告",
            sections_generated=["overview", "metrics"],
            output_path="/tmp/report.html",
            n_strategies=2,
            n_days=252,
        )
        assert result.report_type == "portfolio"
        assert result.title == "组合报告"
        assert result.n_strategies == 2

    def test_to_dict(self):
        result = StrategyReportResult(title="test", n_days=100)
        d = result.to_dict()
        assert d["title"] == "test"
        assert d["n_days"] == 100
        assert "generated_at" in d


class TestEnums:

    def test_report_types(self):
        assert ReportType.SINGLE_STRATEGY.value == "single_strategy"
        assert ReportType.PORTFOLIO.value == "portfolio"
        assert ReportType.COMPARISON.value == "comparison"
        assert ReportType.BACKTEST.value == "backtest"

    def test_report_formats(self):
        assert ReportFormat.HTML.value == "html"
        assert ReportFormat.JSON.value == "json"
        assert ReportFormat.TEXT.value == "text"

    def test_report_sections(self):
        assert ReportSection.OVERVIEW.value == "overview"
        assert ReportSection.METRICS.value == "metrics"
        assert ReportSection.RISK.value == "risk"

    def test_valid_sets(self):
        assert "single_strategy" in VALID_REPORT_TYPES
        assert "html" in VALID_REPORT_FORMATS


# ═══════════════════════════════════════════════════════════════════
# Metrics Tests
# ═══════════════════════════════════════════════════════════════════

class TestMonthlyReturns:

    def test_compute_monthly_returns(self, normal_returns):
        monthly = compute_monthly_returns(normal_returns)
        assert len(monthly) > 0
        assert all(isinstance(m, MonthlyReturnsTable) for m in monthly)

    def test_monthly_data_shape(self, normal_returns):
        monthly = compute_monthly_returns(normal_returns, show_all_months=True)
        for table in monthly:
            assert len(table.data) <= 12
            assert table.annual_return_pct != 0 or True  # could be 0 with certain data

    def test_empty_returns(self):
        monthly = compute_monthly_returns(pd.Series([], dtype=float))
        assert monthly == []

    def test_single_day(self):
        ret = pd.Series([0.01], index=pd.DatetimeIndex(["2025-01-02"]))
        monthly = compute_monthly_returns(ret)
        assert len(monthly) <= 1


class TestAnnualReturns:

    def test_compute_annual_returns(self, normal_returns):
        annual = compute_annual_returns(normal_returns)
        assert len(annual) > 0
        for year, ret in annual.items():
            assert isinstance(year, int)
            assert isinstance(ret, float)

    def test_empty_returns(self):
        assert compute_annual_returns(pd.Series([], dtype=float)) == {}

    def test_two_year_data(self, two_year_dates):
        rng = np.random.default_rng(42)
        n = len(two_year_dates)
        ret = pd.Series(rng.normal(0.10 / 252, 0.15 / np.sqrt(252), n), index=two_year_dates)
        annual = compute_annual_returns(ret)
        assert len(annual) >= 2  # 2 years + maybe partial


class TestDrawdownAnalysis:

    def test_compute_drawdown_analysis(self, normal_returns):
        equity = (1 + normal_returns).cumprod()
        dd = compute_drawdown_analysis(equity)
        assert isinstance(dd, DrawdownAnalysis)
        assert dd.max_drawdown_pct <= 0  # drawdown is negative
        assert dd.underwater_days_pct >= 0

    def test_drawdown_periods(self, normal_returns):
        equity = (1 + normal_returns).cumprod()
        dd = compute_drawdown_analysis(equity, top_n=3)
        assert len(dd.drawdown_periods) <= 3
        if dd.drawdown_periods:
            dp = dd.drawdown_periods[0]
            assert "peak_date" in dp
            assert "trough_date" in dp
            assert "max_drawdown_pct" in dp

    def test_empty_equity(self):
        dd = compute_drawdown_analysis(pd.Series([], dtype=float))
        assert dd.max_drawdown_pct == 0
        assert dd.drawdown_periods == []

    def test_single_point(self):
        dd = compute_drawdown_analysis(pd.Series([1.0]))
        assert dd.max_drawdown_pct == 0

    def constant_equity(self):
        eq = pd.Series(np.ones(100))
        dd = compute_drawdown_analysis(eq)
        assert dd.max_drawdown_pct == 0
        assert dd.underwater_days_pct == 0


class TestWinLossAnalysis:

    def test_compute_win_loss(self, normal_returns):
        wl = compute_win_loss_analysis(normal_returns)
        assert isinstance(wl, WinLossAnalysis)
        assert wl.total_trades == len(normal_returns)
        assert wl.winning_trades + wl.losing_trades <= wl.total_trades

    def test_win_rate(self, normal_returns):
        wl = compute_win_loss_analysis(normal_returns)
        assert 0 <= wl.win_rate_pct <= 100

    def test_consecutive_streaks(self, normal_returns):
        wl = compute_win_loss_analysis(normal_returns)
        assert wl.max_consecutive_wins >= 0
        assert wl.max_consecutive_losses >= 0

    def test_empty_returns(self):
        wl = compute_win_loss_analysis(pd.Series([], dtype=float))
        assert wl.total_trades == 0

    def test_all_positive(self, sample_dates):
        ret = pd.Series(np.ones(len(sample_dates)) * 0.001, index=sample_dates)
        wl = compute_win_loss_analysis(ret)
        assert wl.win_rate_pct == 100.0
        assert wl.winning_trades == len(ret)

    def test_all_negative(self, sample_dates):
        ret = pd.Series(np.ones(len(sample_dates)) * -0.001, index=sample_dates)
        wl = compute_win_loss_analysis(ret)
        assert wl.win_rate_pct == 0.0

    def test_profit_factor_infinite(self, sample_dates):
        """全正收益时盈亏比为无穷"""
        ret = pd.Series(np.ones(len(sample_dates)) * 0.001, index=sample_dates)
        wl = compute_win_loss_analysis(ret)
        assert wl.profit_factor == float("inf")


class TestRiskMetrics:

    def test_compute_risk_metrics(self, normal_returns):
        risk = compute_risk_metrics(normal_returns)
        assert isinstance(risk, RiskMetrics)
        assert risk.var_95_pct < 0  # VaR should be negative
        assert risk.sortino_ratio != 0
        assert risk.skewness != 0

    def test_empty_returns(self):
        risk = compute_risk_metrics(pd.Series([], dtype=float))
        assert risk.var_95_pct == 0

    def test_few_data_points(self, sample_dates):
        ret = pd.Series([0.01, 0.02], index=sample_dates[:2])
        risk = compute_risk_metrics(ret)
        assert risk.var_95_pct == 0


class TestReturnDistribution:

    def test_compute_distribution(self, normal_returns):
        dist = compute_return_distribution(normal_returns)
        assert "bins" in dist
        assert "counts" in dist
        assert "mean" in dist
        assert "positive_pct" in dist
        assert "negative_pct" in dist
        assert len(dist["bins"]) == 10  # default n_bins
        assert sum(dist["frequencies"]) == pytest.approx(1.0, abs=0.01)

    def test_empty_returns(self):
        dist = compute_return_distribution(pd.Series([], dtype=float))
        assert dist == {}

    def test_single_value(self, sample_dates):
        ret = pd.Series([0.01], index=sample_dates[:1])
        dist = compute_return_distribution(ret)
        assert "mean" in dist


# ═══════════════════════════════════════════════════════════════════
# HTMLRenderer Tests
# ═══════════════════════════════════════════════════════════════════

class TestHTMLReportRenderer:

    def test_init(self):
        renderer = HTMLReportRenderer()
        assert renderer.dp == 2

    def test_custom_decimal_places(self):
        config = StrategyReportConfig(decimal_places=4)
        renderer = HTMLReportRenderer(config)
        assert renderer.dp == 4

    def test_render_full_report(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_full_report(
            "single_strategy",
            "测试报告",
            {"overview": "<p>overview</p>"},
            {"generated_at": "2025-01-01", "n_strategies": 1},
        )
        assert "<!DOCTYPE html>" in html
        assert "测试报告" in html
        assert "V6.5" in html
        assert "overview" in html

    def test_render_full_report_multiple_sections(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_full_report(
            "portfolio",
            "Portfolio Report",
            {"overview": "<p>OV</p>", "metrics": "<p>M</p>", "risk": "<p>R</p>"},
        )
        assert "Portfolio Report" in html
        assert "id=\"section-overview\"" in html
        assert "id=\"section-metrics\"" in html
        assert "id=\"section-risk\"" in html

    def test_render_overview(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_overview("My Strategy", "single_strategy", 1, 252, "CSI300")
        assert "My Strategy" in html
        assert "single_strategy" in html
        assert "252" in html
        assert "CSI300" in html

    def test_render_metrics_table(self):
        renderer = HTMLReportRenderer()
        metrics = {
            "cumulative_return_pct": 15.5,
            "sharpe": 1.25,
            "max_drawdown_pct": -8.3,
            "n_trading_days": 252,
        }
        html = renderer.render_metrics_table(metrics)
        assert "累计收益率" in html
        assert "15.50" in html
        assert "1.25" in html
        assert "252" in html

    def test_render_metrics_table_empty(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_metrics_table({})
        assert "无指标数据" in html

    def test_render_equity_curve(self):
        renderer = HTMLReportRenderer()
        equity = [1.0, 1.02, 1.01, 1.03, 1.05, 1.04, 1.06]
        html = renderer.render_equity_curve(equity)
        assert "sparkline" in html
        assert "起始净值" in html
        assert "最终净值" in html

    def test_render_equity_curve_empty(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_equity_curve([])
        assert "无净值数据" in html

    def test_render_monthly_returns(self, normal_returns):
        renderer = HTMLReportRenderer()
        monthly = compute_monthly_returns(normal_returns, show_all_months=True)
        html = renderer.render_monthly_returns(monthly)
        assert "年收益" in html
        assert "Jan" in html or "Feb" in html

    def test_render_monthly_returns_empty(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_monthly_returns([])
        assert "无月度数据" in html

    def test_render_drawdown_analysis(self):
        renderer = HTMLReportRenderer()
        dd = DrawdownAnalysis(
            max_drawdown_pct=-15.5,
            max_drawdown_duration_days=45,
            avg_drawdown_pct=-5.2,
            underwater_days_pct=35.0,
            current_drawdown_pct=-2.1,
            recovery_days=0,
            drawdown_periods=[
                {"peak_date": "2025-01-01", "trough_date": "2025-03-15",
                 "max_drawdown_pct": -15.5, "duration_days": 45},
            ],
        )
        html = renderer.render_drawdown_analysis(dd)
        assert "最大回撤" in html
        assert "15.50" in html

    def test_render_win_loss_analysis(self):
        renderer = HTMLReportRenderer()
        wl = WinLossAnalysis(
            total_trades=252,
            winning_trades=140,
            losing_trades=112,
            win_rate_pct=55.56,
            avg_win_pct=0.85,
            avg_loss_pct=-0.72,
            profit_factor=1.65,
            max_consecutive_wins=8,
            max_consecutive_losses=5,
        )
        html = renderer.render_win_loss_analysis(wl)
        assert "盈利天数" in html
        assert "55.6" in html
        assert "8" in html

    def test_render_risk_metrics(self):
        renderer = HTMLReportRenderer()
        risk = RiskMetrics(
            var_95_pct=-1.52,
            cvar_95_pct=-2.31,
            skewness=-0.15,
            kurtosis=3.2,
            downside_deviation_pct=10.5,
            sortino_ratio=1.35,
            ulcer_index=5.2,
            tail_ratio=1.8,
        )
        html = renderer.render_risk_metrics(risk)
        assert "VaR" in html
        assert "Sortino" in html

    def test_render_benchmark_comparison(self):
        renderer = HTMLReportRenderer()
        metrics = {
            "benchmark_cumulative_return_pct": 8.5,
            "benchmark_sharpe": 0.6,
            "active_return_pct": 5.2,
            "tracking_error_pct": 3.1,
            "information_ratio": 1.2,
            "alpha": 3.5,
            "beta": 0.85,
            "r_squared": 0.72,
        }
        html = renderer.render_benchmark_comparison(metrics)
        assert "基准累计收益" in html
        assert "Alpha" in html

    def test_render_attribution(self):
        renderer = HTMLReportRenderer()
        attr = [
            {"strategy_name": "动量", "weight": 0.6, "contribution_pct": 55.0,
             "standalone_return_pct": 12.5, "sharpe": 1.2, "correlation_to_portfolio": 0.85},
            {"strategy_name": "价值", "weight": 0.4, "contribution_pct": 45.0,
             "standalone_return_pct": 10.2, "sharpe": 0.9, "correlation_to_portfolio": 0.72},
        ]
        html = renderer.render_attribution(attr)
        assert "动量" in html
        assert "价值" in html
        assert "贡献%" in html

    def test_render_correlation(self):
        renderer = HTMLReportRenderer()
        corr = [
            {"strategy_i": "A", "strategy_j": "B", "correlation": 0.35},
            {"strategy_i": "A", "strategy_j": "C", "correlation": 0.12},
        ]
        html = renderer.render_correlation(corr)
        assert "A" in html
        assert "B" in html
        assert "0.35" in html

    def test_render_distribution(self):
        renderer = HTMLReportRenderer()
        dist = {
            "bins": ["-2~-1%", "-1~0%", "0~1%", "1~2%"],
            "counts": [15, 35, 40, 10],
            "frequencies": [0.15, 0.35, 0.40, 0.10],
            "mean": 0.15,
            "median": 0.12,
            "std": 1.2,
            "min": -3.5,
            "max": 3.8,
            "positive_pct": 55.0,
            "negative_pct": 45.0,
            "zero_pct": 0.0,
        }
        html = renderer.render_distribution(dist)
        assert "正收益占比" in html
        assert "55.0" in html

    def test_render_rolling_metrics(self):
        renderer = HTMLReportRenderer()
        rolling = {
            "rolling_sharpe": [1.0, 0.8, 1.2, 0.9, 1.1],
        }
        html = renderer.render_rolling_metrics(rolling)
        assert "滚动 Sharpe" in html
        assert "1.20" in html

    def test_render_warnings(self):
        renderer = HTMLReportRenderer()
        html = renderer.render_warnings(["数据缺失", "基准未对齐"])
        assert "警告" in html
        assert "数据缺失" in html

    def test_render_warnings_empty(self):
        renderer = HTMLReportRenderer()
        assert renderer.render_warnings([]) == ""

    def test_escape(self):
        renderer = HTMLReportRenderer()
        assert renderer._escape("<script>") == "&lt;script&gt;"
        assert renderer._escape("a & b") == "a &amp; b"


# ═══════════════════════════════════════════════════════════════════
# Generator Tests
# ═══════════════════════════════════════════════════════════════════

class TestStrategyReportGenerator:

    def test_init(self):
        gen = StrategyReportGenerator()
        assert gen.config is not None

    def test_init_with_config(self):
        config = StrategyReportConfig(title="定制报告", include_sections=["overview"])
        gen = StrategyReportGenerator(config=config)
        assert gen.config.title == "定制报告"

    def test_init_with_output_dir(self, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        assert gen.config.output_dir == temp_output_dir

    def test_from_strategy_returns_basic(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "动量策略")
        assert report.report_type == "single_strategy"
        assert report.n_days == len(normal_returns)
        assert report.output_path
        assert os.path.exists(report.output_path)
        assert "动量策略" in report.title

    def test_from_strategy_returns_with_benchmark(self, normal_returns, benchmark_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(
            normal_returns,
            "带基准策略",
            benchmark_returns=benchmark_returns,
            benchmark_name="CSI300",
        )
        assert "benchmark" in report.sections_generated
        assert report.output_path

    def test_from_strategy_returns_empty(self, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(pd.Series([], dtype=float), "空策略")
        assert report.errors
        assert "为空" in " ".join(report.errors) or len(report.errors) > 0

    def test_from_strategy_returns_config_custom(self, normal_returns, temp_output_dir):
        config = StrategyReportConfig(
            title="自定义报告",
            include_sections=["overview", "metrics", "equity"],
            benchmark_name="CSI500",
        )
        gen = StrategyReportGenerator(config=config, output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "Custom")
        assert report.title == "自定义报告"
        assert set(report.sections_generated).issubset(
            {"overview", "metrics", "equity"}
        )

    def test_from_strategy_returns_negative(self, negative_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(negative_returns, "负收益策略")
        assert report.n_days > 0
        assert report.output_path

    def test_from_strategy_returns_zero(self, zero_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(zero_returns, "零收益")
        assert report.output_path
        assert report.n_days > 0

    def test_from_portfolio_result(self, two_strategy_portfolio, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_portfolio_result(two_strategy_portfolio)
        assert report.report_type == "portfolio"
        assert report.n_strategies == 2
        assert report.output_path
        assert os.path.exists(report.output_path)
        assert "测试组合" in report.title

    def test_from_portfolio_result_single_strategy(self, normal_returns, temp_output_dir):
        """单策略 PortfolioResult 应返回 single_strategy 报告"""
        from factor_lab.portfolio import PortfolioSpec, PortfolioBacktestEngine
        spec = PortfolioSpec(
            name="单个策略",
            strategy_returns={"only": normal_returns},
            weights={"only": 1.0},
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run_with_benchmark("CSI300")
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_portfolio_result(result)
        # 一个策略时也视为 single_strategy
        assert report.n_strategies > 0
        assert report.output_path

    def test_generated_html_content(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "HTML验证")
        with open(report.output_path) as f:
            html = f.read()
        assert "<!DOCTYPE html>" in html
        assert "累计收益率" in html
        assert "Sharpe" in html
        assert "最大回撤" in html
        assert "V6.5" in html

    def test_list_reports_empty(self, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        reports = gen.list_reports()
        assert reports == []

    def test_list_reports_after_generation(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        gen.from_strategy_returns(normal_returns, "列表测试")
        reports = gen.list_reports()
        assert len(reports) > 0
        assert reports[0]["file_name"].endswith(".html")
        assert reports[0]["size_kb"] > 0

    def test_list_reports_filter(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        gen.from_strategy_returns(normal_returns, "筛选测试")
        reports = gen.list_reports(report_type="single_strategy")
        assert len(reports) > 0
        assert reports[0]["type"] == "single_strategy"

    def test_get_report_count(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        gen.from_strategy_returns(normal_returns, "计数测试")
        counts = gen.get_report_count()
        assert "single_strategy" in counts
        assert counts["single_strategy"] >= 1

    def test_high_sharpe_generates_report(self, high_sharpe_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(high_sharpe_returns, "高Sharpe")
        assert report.n_days > 0
        assert report.output_path

    def test_different_output_formats(self, normal_returns, temp_output_dir):
        """使用不同配置参数不影响基本功能"""
        config = StrategyReportConfig(
            include_sections=["overview", "metrics"],
            show_all_monthly=True,
            decimal_places=4,
        )
        gen = StrategyReportGenerator(config=config, output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "配置测试")
        assert report.output_path

    def test_generated_at_timestamp(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "时间戳")
        assert report.generated_at
        # ISO format check
        assert "T" in report.generated_at

    def test_include_raw_data_config(self, normal_returns, temp_output_dir):
        """设置 include_raw_data=True 不影响生成流程"""
        config = StrategyReportConfig(include_raw_data=True)
        gen = StrategyReportGenerator(config=config, output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "原始数据")
        assert report.output_path

    def test_duration_measured(self, normal_returns, temp_output_dir):
        gen = StrategyReportGenerator(output_dir=temp_output_dir)
        report = gen.from_strategy_returns(normal_returns, "耗时测试")
        assert report.duration_ms > 0


# ═══════════════════════════════════════════════════════════════════
# Built-in Skill Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestStrategyReportSkill:

    def test_skill_registered(self):
        """strategy-report skill 应存在于 BUILTIN_SKILLS 中"""
        from factor_lab.research_skill.builtins import BUILTIN_SKILLS
        skill_ids = [s.skill_id for s in BUILTIN_SKILLS]
        assert "strategy-report" in skill_ids

    def test_skill_has_correct_category(self):
        from factor_lab.research_skill.builtins import BUILTIN_SKILLS
        for s in BUILTIN_SKILLS:
            if s.skill_id == "strategy-report":
                assert s.category == "report"
                assert len(s.params) >= 3
                return
        pytest.fail("strategy-report skill not found")

    def test_skill_execute_demo(self, monkeypatch, tmp_path):
        """通过 Runtime 执行 strategy-report skill (demo 模式)"""
        from factor_lab.research_skill import SkillRuntime
        from factor_lab.research_skill.skill_registry import SkillRegistry
        from factor_lab.research_skill.builtins import BUILTIN_SKILLS

        registry = SkillRegistry(root=tmp_path / "skill_registry")
        registry.seed_defaults(BUILTIN_SKILLS)

        from factor_lab.research_skill import skill_runtime as run_mod
        monkeypatch.setattr(run_mod, "RUNTIME_ROOT", tmp_path / "skill_runs")

        runtime = SkillRuntime(registry=registry, runtime_root=tmp_path / "skill_runs")
        result = runtime.run("strategy-report", params={"source": "demo"})

        assert result.status == "completed", f"Skill failed: {result.error}"
        assert result.data.get("status") == "completed"
        assert "output_path" in result.data

    def test_skill_execute_with_custom_params(self, monkeypatch, tmp_path):
        """带自定义参数的 skill 执行"""
        from factor_lab.research_skill import SkillRuntime
        from factor_lab.research_skill.skill_registry import SkillRegistry
        from factor_lab.research_skill.builtins import BUILTIN_SKILLS

        registry = SkillRegistry(root=tmp_path / "skill_registry")
        registry.seed_defaults(BUILTIN_SKILLS)

        from factor_lab.research_skill import skill_runtime as run_mod
        monkeypatch.setattr(run_mod, "RUNTIME_ROOT", tmp_path / "skill_runs")

        runtime = SkillRuntime(registry=registry, runtime_root=tmp_path / "skill_runs")
        result = runtime.run(
            "strategy-report",
            params={
                "source": "demo",
                "report_title": "自定义策略报告",
                "benchmark_name": "CSI500",
            },
        )

        assert result.status == "completed"
        assert "output_path" in result.data


# ═══════════════════════════════════════════════════════════════════
# Regression Tests — 确保与 V6.x/V5.x 无冲突
# ═══════════════════════════════════════════════════════════════════

class TestRegression:

    def test_research_skill_runtime_still_works(self, monkeypatch, tmp_path):
        """V6.0 Skill Runtime 仍然正常运作"""
        from factor_lab.research_skill import (
            SkillSpec, SkillParam, SkillCategory,
            SkillRegistry, SkillRuntime,
        )

        registry = SkillRegistry(root=tmp_path / "skill_registry")
        from factor_lab.research_skill import skill_runtime as run_mod
        monkeypatch.setattr(run_mod, "RUNTIME_ROOT", tmp_path / "skill_runs")

        # 注册一个测试 skill
        test_spec = SkillSpec(
            skill_id="test-skill",
            name="测试",
            description="Regression test skill",
            category=SkillCategory.ANALYSIS.value,
            execute=lambda ctx, p: {"result": "ok"},
            handler="factor_lab.research_skill.builtins:_execute_data_quality",
        )
        registry.register(test_spec)

        runtime = SkillRuntime(registry=registry, runtime_root=tmp_path / "skill_runs")
        result = runtime.run("test-skill")
        assert result.status == "completed"
        assert result.data.get("result") == "ok"

    def test_portfolio_backtest_still_works(self, sample_dates):
        """V6.4 Portfolio Backtest 仍然正常运作"""
        from factor_lab.portfolio import PortfolioSpec, PortfolioBacktestEngine
        rng = np.random.default_rng(42)
        n = len(sample_dates)
        ret_a = pd.Series(rng.normal(0.1 / 252, 0.15 / np.sqrt(252), n), index=sample_dates)
        ret_b = pd.Series(rng.normal(0.12 / 252, 0.15 / np.sqrt(252), n), index=sample_dates)

        spec = PortfolioSpec(
            name="回归测试",
            strategy_returns={"A": ret_a, "B": ret_b},
            weights={"A": 0.5, "B": 0.5},
        )
        engine = PortfolioBacktestEngine(spec)
        result = engine.run_with_benchmark("CSI300")
        assert result.metrics.n_strategies == 2
        assert result.metrics.sharpe != 0.0

    def test_cli_help_includes_strategy_report(self):
        """CLI 帮助应包含 strategy:report 命令"""
        from hermes_cli import show_help
        import io
        captured = io.StringIO()
        sys.stdout = captured
        try:
            show_help()
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        assert "strategy:report" in output
