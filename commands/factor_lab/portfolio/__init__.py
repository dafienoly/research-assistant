"""Portfolio Backtest/Benchmark V6.4 — 组合回测与基准对比

模块结构:
  spec              组合配置 (PortfolioSpec, BenchmarkSpec, PortfolioResult)
  metrics           组合层面指标 (交叉相关性, 主动收益, Alpha/Beta, 归因)
  benchmark         基准指数收益率 (CSI300/500/1000/ALL)
  portfolio_backtest 组合回测引擎 (PortfolioBacktestEngine)
  report            报告生成与保存

快速开始:
    import pandas as pd
    from factor_lab.portfolio import (
        PortfolioSpec, BenchmarkSpec, PortfolioBacktestEngine, print_summary,
    )

    # 准备策略收益率
    strategy_a_returns = pd.Series(...)  # index=date
    strategy_b_returns = pd.Series(...)

    # 定义组合
    spec = PortfolioSpec(
        name="平衡组合",
        strategy_returns={"动量": strategy_a_returns, "价值": strategy_b_returns},
        weights={"动量": 0.5, "价值": 0.5},
        rebalance_freq="monthly",
    )

    # 回测 (带基准对比)
    engine = PortfolioBacktestEngine(spec)
    result = engine.run_with_benchmark("CSI300")

    # 查看结果
    print_summary(result)
    print(result.metrics.sharpe)
"""

from factor_lab.portfolio.spec import (
    PortfolioSpec,
    BenchmarkSpec,
    PortfolioMetrics,
    PortfolioResult,
    AttributionItem,
)
from factor_lab.portfolio.metrics import (
    compute_portfolio_absolute_metrics,
    compute_benchmark_relative_metrics,
    compute_cross_correlation,
    compute_avg_correlation,
    compute_attribution,
    compute_portfolio_metrics,
)
from factor_lab.portfolio.benchmark import (
    get_benchmark_returns,
    get_benchmark_meta,
    fetch_index_kline,
    list_benchmarks,
    make_benchmark_spec,
    VALID_BENCHMARK_NAMES,
)
from factor_lab.portfolio.portfolio_backtest import PortfolioBacktestEngine
from factor_lab.portfolio.report import (
    print_summary,
    format_report,
    save_report,
)

__all__ = [
    # spec
    "PortfolioSpec",
    "BenchmarkSpec",
    "PortfolioMetrics",
    "PortfolioResult",
    "AttributionItem",
    # metrics
    "compute_portfolio_absolute_metrics",
    "compute_benchmark_relative_metrics",
    "compute_cross_correlation",
    "compute_avg_correlation",
    "compute_attribution",
    "compute_portfolio_metrics",
    # benchmark
    "get_benchmark_returns",
    "get_benchmark_meta",
    "fetch_index_kline",
    "list_benchmarks",
    "make_benchmark_spec",
    "VALID_BENCHMARK_NAMES",
    # engine
    "PortfolioBacktestEngine",
    # report
    "print_summary",
    "format_report",
    "save_report",
]
