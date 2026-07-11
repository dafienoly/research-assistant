"""Hermes VNext governed research and trading-control components.

The package deliberately separates research scores from executable orders.  No
module in this package enables live trading by default, and unavailable inputs
are represented as explicit data-quality states instead of synthetic values.
"""

from .contracts import (
    ApprovedOrderEnvelope,
    DataStatus,
    ExecutionEvent,
    MainlineState,
    MarketDataEnvelope,
    OrderDraft,
    QualityStatus,
    RegimeName,
    ResearchSignal,
    ReviewRecord,
    TargetPortfolioWeights,
    TargetWeightLine,
    TradingMode,
    Tradability,
)

__all__ = [
    "ApprovedOrderEnvelope",
    "DataStatus",
    "ExecutionEvent",
    "MainlineState",
    "MarketDataEnvelope",
    "OrderDraft",
    "QualityStatus",
    "RegimeName",
    "ResearchSignal",
    "ReviewRecord",
    "TargetPortfolioWeights",
    "TargetWeightLine",
    "TradingMode",
    "Tradability",
]
