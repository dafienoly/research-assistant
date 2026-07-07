"""Strategy Report Generator V6.5 — 策略报告生成器

生成全面、格式化的策略分析报告，支持:
  - 单策略深度报告 (收益分析、回撤分析、风险指标、月度收益、盈亏分析)
  - 组合策略报告 (权重归因、基准对比、相关性分析)
  - 多策略对比报告
  - HTML/JSON/TEXT 输出格式
  - Hermes 设计系统风格 HTML 渲染

快速开始:
    from factor_lab.portfolio import PortfolioBacktestEngine, PortfolioSpec
    from factor_lab.strategy_report import StrategyReportGenerator

    # 从 PortfolioResult (V6.4) 生成报告
    engine = PortfolioBacktestEngine(spec)
    result = engine.run_with_benchmark("CSI300")
    gen = StrategyReportGenerator()
    report = gen.from_portfolio_result(result)
    print(f"报告已保存: {report.output_path}")

    # 从收益率序列直接生成
    report = gen.from_strategy_returns(
        strategy_returns=momentum_series,
        strategy_name="动量策略",
    )
"""

from factor_lab.strategy_report.spec import (
    StrategyReportConfig,
    StrategyReportResult,
    ReportType,
    ReportFormat,
    ReportSection,
    MonthlyReturnsTable,
    DrawdownAnalysis,
    WinLossAnalysis,
    RiskMetrics,
    VALID_REPORT_TYPES,
    VALID_REPORT_FORMATS,
)
from factor_lab.strategy_report.metrics import (
    compute_monthly_returns,
    compute_annual_returns,
    compute_drawdown_analysis,
    compute_win_loss_analysis,
    compute_risk_metrics,
    compute_rolling_metrics,
    compute_return_distribution,
)
from factor_lab.strategy_report.html_renderer import HTMLReportRenderer
from factor_lab.strategy_report.generator import (
    StrategyReportGenerator,
    DEFAULT_OUTPUT_ROOT,
)

__all__ = [
    # spec
    "StrategyReportConfig",
    "StrategyReportResult",
    "ReportType",
    "ReportFormat",
    "ReportSection",
    "MonthlyReturnsTable",
    "DrawdownAnalysis",
    "WinLossAnalysis",
    "RiskMetrics",
    "VALID_REPORT_TYPES",
    "VALID_REPORT_FORMATS",
    # metrics
    "compute_monthly_returns",
    "compute_annual_returns",
    "compute_drawdown_analysis",
    "compute_win_loss_analysis",
    "compute_risk_metrics",
    "compute_rolling_metrics",
    "compute_return_distribution",
    # renderer
    "HTMLReportRenderer",
    # generator
    "StrategyReportGenerator",
    "DEFAULT_OUTPUT_ROOT",
]
