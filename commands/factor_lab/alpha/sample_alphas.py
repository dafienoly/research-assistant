"""Sample Alphas V3.0 — 内置示例, 不启用交易"""
from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.registry import register_alpha


def create_sample_alphas():
    """创建 3 个 sample alpha, 全 disabled"""
    samples = []

    a1 = AlphaSpec(
        name="ret5_momentum",
        description="5日动量因子, ret5 降序选股",
        hypothesis="过去5日收益最高的股票在未来一个月继续跑赢",
        universe="all_watchlist",
        factor_expression="ret5 = close.pct_change(5); rank(ret5, ascending=False)",
        signal_direction="long",
        rebalance_frequency="monthly",
        status="registered",
        author="system",
        source="sample",
        enabled=False,
        paper_enabled=False,
        live_enabled=False,
        tags=["momentum", "ret5", "sample"],
    )
    samples.append(register_alpha(a1))

    a2 = AlphaSpec(
        name="low_vol_quality",
        description="低波动 + 基本面质量复合因子",
        hypothesis="低波动高ROE股票在中国市场具有超额收益",
        universe="all_watchlist",
        factor_expression="rank(-volatility20) * rank(roe_q)",
        signal_direction="long",
        rebalance_frequency="monthly",
        status="registered",
        author="system",
        source="sample",
        enabled=False,
        paper_enabled=False,
        live_enabled=False,
        tags=["volatility", "quality", "sample"],
    )
    samples.append(register_alpha(a2))

    a3 = AlphaSpec(
        name="sector_relative_strength",
        description="行业相对强度因子",
        hypothesis="强势行业中的龙头个股具有 momentum 延续性",
        universe="all_watchlist",
        factor_expression="industry_rank(ret5) * close_gt_ma20",
        signal_direction="long",
        rebalance_frequency="monthly",
        status="registered",
        author="system",
        source="sample",
        enabled=False,
        paper_enabled=False,
        live_enabled=False,
        tags=["sector", "momentum", "sample"],
    )
    samples.append(register_alpha(a3))

    return samples
