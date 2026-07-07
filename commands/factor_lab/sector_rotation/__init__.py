"""Sector Rotation V6.8 — A-share 行业轮动

行业轮动模块, 提供:
  1. 行业绩效计算 (动量/波动率/资金流)
  2. 3 种轮动策略 (动量轮动/均值回归/复合轮动)
  3. 轮动回测引擎 (基于 V6.4 PortfolioBacktestEngine)
  4. 轮动信号生成与报告
  5. 投研 Skill 集成

快速开始:
    import pandas as pd
    from factor_lab.sector_rotation import (
        SectorRotationConfig, SectorRotationEngine,
        RotationStrategyType,
    )

    # 配置
    config = SectorRotationConfig(
        name="动量轮动",
        strategy_type=RotationStrategyType.MOMENTUM,
        top_n=5,
        rebalance_freq="monthly",
    )

    # 运行
    engine = SectorRotationEngine(config)
    result = engine.run(stock_returns=...)
    print(result.summary())
"""

from factor_lab.sector_rotation.spec import (
    SectorRotationConfig,
    SectorPerformance,
    RotationSignal,
    RotationResult,
    RotationStrategyType,
)
from factor_lab.sector_rotation.sector_performance import (
    compute_sector_returns,
    compute_sector_performance_snapshot,
    compute_sector_rankings,
    get_sector_mapping,
    get_stocks_by_sector,
    get_sector_list,
    get_sector_stock_count,
    build_sector_performance_history,
)
from factor_lab.sector_rotation.rotation_strategies import (
    ISectorRotationStrategy,
    MomentumRotation,
    MeanReversionRotation,
    CompositeRotation,
    create_strategy,
)
from factor_lab.sector_rotation.rotation_engine import (
    SectorRotationEngine,
)

# 兼容性别名
SectorRotationResult = RotationResult

__all__ = [
    # spec
    "SectorRotationConfig",
    "SectorPerformance",
    "RotationSignal",
    "RotationResult",
    "RotationStrategyType",
    # sector_performance
    "compute_sector_returns",
    "compute_sector_performance_snapshot",
    "compute_sector_rankings",
    "get_sector_mapping",
    "get_stocks_by_sector",
    "get_sector_list",
    "get_sector_stock_count",
    "build_sector_performance_history",
    # rotation_strategies
    "ISectorRotationStrategy",
    "MomentumRotation",
    "MeanReversionRotation",
    "CompositeRotation",
    "create_strategy",
    # rotation_engine
    "SectorRotationEngine",
    # compatibility
    "SectorRotationResult",
]
