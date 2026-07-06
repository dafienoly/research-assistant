"""V4.1 Shadow Live Pipeline — execution package

The execution package defines the contracts, gates, and risk boundaries
for Hermes' controlled live pipeline. It does NOT execute real trades.

Core modules:
  - pipeline_design:     Stage definitions, signal→proposal→intent contracts
  - approval_gate:       Multi-level approval gate state machine
  - risk_boundary:       Safety policies, forbidden actions, enforcer
  - shadow_account:      V4.1 Shadow account — simulated cash + positions + PnL
  - shadow_order:        V4.1 Shadow order lifecycle — PENDING→FILLED/REJECTED
  - shadow_fill:         V4.1 Fill simulation with slippage models
  - shadow_ledger:       V4.1 Execution ledger + signal-vs-fill deviation reports
  - shadow_pipeline:     V4.1 Shadow pipeline runner — orchestrates flow
  - trade_filter:        V4.6 Pre-execution trade filter engine
  - slippage_control:    V4.6 Slippage budget, estimation, and control
  - order_book:          V4.7 Centralized order book — depth, aggregation, events
  - execution_route:     V4.7 Deep execution route — selection, scoring, routing
  - capital_boundary:    V4.8 Capital safety boundary — allocation, authority, incident protection
"""

from factor_lab.execution.pipeline_design import (
    ResearchSignal,
    ProposalContract,
    ExecutionIntent,
    AuditRecord,
    PipelineContext,
    PipelineStage,
    PipelineResult,
    LivePipelineRunner,
    STAGE_RESEARCH_SIGNAL,
    STAGE_PROPOSAL_CREATION,
    STAGE_PROPOSAL_APPROVAL,
    STAGE_PAPER_SHADOW,
    STAGE_PAPER_REVIEW,
    STAGE_LIVE_READINESS,
    STAGE_LIVE_APPROVAL,
    STAGE_LIVE_EXECUTION,
)

from factor_lab.execution.approval_gate import (
    ApprovalLevel,
    ApprovalGateConfig,
    ApprovalDecision,
    GateEvaluator,
    Gates,
)

from factor_lab.execution.risk_boundary import (
    RiskBoundary,
    RiskPolicy,
    BoundaryEnforcer,
    ForbiddenActionRegistry,
)

# V4.1 Shadow Live Pipeline
from factor_lab.execution.shadow_account import (
    ShadowAccount,
    ShadowPosition,
    AccountStatus,
)

from factor_lab.execution.shadow_order import (
    ShadowOrder,
    ShadowOrderManager,
    FillEvent,
    OrderSide,
    OrderStatus,
    OrderType,
    RejectReason,
)

from factor_lab.execution.shadow_fill import (
    FillEngine,
    SlippageConfig,
    SlippageModel,
    FillStrategy,
    MarketDataSnapshot,
    MarketDataStatus,
)

from factor_lab.execution.shadow_ledger import (
    ShadowExecutionLedger,
    LedgerEntry,
    DeviationEntry,
)

from factor_lab.execution.shadow_pipeline import (
    ShadowPipelineRunner,
    ShadowPipelineConfig,
    ShadowPipelineResult,
)

# V4.6 Trade Filter & Slippage Control
from factor_lab.execution.trade_filter import (
    TradeFilterEngine,
    TradeFilterRule,
    TradeContext,
    FilterResult,
    FilterReport,
    FilterType,
    FilterSeverity,
    FilterStatus,
    build_default_trade_filter_rules,
    detect_board_type,
    is_st_board,
)

from factor_lab.execution.slippage_control import (
    SlippageController,
    SlippageEstimator,
    SlippageBudgetTracker,
    SlippageBudget,
    SlippageEstimate,
    SlippageLimitAction,
    BudgetPeriod,
)

# V4.7 Order Book & Deep Execution Route
from factor_lab.execution.order_book import (
    OrderBook,
    OrderBookEntry,
    OrderBookEvent,
    OrderBookSnapshot,
    PriceLevel,
    BookSide,
    OrderBookEventType,
)

from factor_lab.execution.execution_route import (
    DeepExecutionRouter,
    RouteSelector,
    RouteResult,
    RouteConfig,
    RoutePerformance,
    RouteType,
    RouteUrgency,
    RouteRecommendation,
)

# V4.8 Capital Safety Boundary
from factor_lab.execution.capital_boundary import (
    # Enums
    AuthorityTier,
    CapitalActionType,
    IncidentSeverity,
    # Allocation
    CapitalAllocationConfig,
    AllocationLimit,
    AllocationCheckResult,
    CapitalAllocation,
    # Authority
    CapitalAuthority,
    AuthorityCheckResult,
    # Monitor
    CapitalSafetyMonitor,
    CapitalUsageSnapshot,
    CapitalAlert,
    # Incident Protection
    CapitalIncidentProtection,
    CapitalIncidentAlert,
    # Enforcer
    CapitalBoundaryEnforcer,
    # Convenience
    build_capital_safety_boundaries,
    build_capital_safety_policy,
)

__all__ = [
    # Pipeline design
    "ResearchSignal", "ProposalContract", "ExecutionIntent", "AuditRecord",
    "PipelineContext", "PipelineStage", "PipelineResult", "LivePipelineRunner",
    "STAGE_RESEARCH_SIGNAL", "STAGE_PROPOSAL_CREATION", "STAGE_PROPOSAL_APPROVAL",
    "STAGE_PAPER_SHADOW", "STAGE_PAPER_REVIEW", "STAGE_LIVE_READINESS",
    "STAGE_LIVE_APPROVAL", "STAGE_LIVE_EXECUTION",
    # Approval gate
    "ApprovalLevel", "ApprovalGateConfig", "ApprovalDecision", "GateEvaluator", "Gates",
    # Risk boundary
    "RiskBoundary", "RiskPolicy", "BoundaryEnforcer", "ForbiddenActionRegistry",
    # V4.1 Shadow Account
    "ShadowAccount", "ShadowPosition", "AccountStatus",
    # V4.1 Shadow Order
    "ShadowOrder", "ShadowOrderManager", "FillEvent",
    "OrderSide", "OrderStatus", "OrderType", "RejectReason",
    # V4.1 Shadow Fill
    "FillEngine", "SlippageConfig", "SlippageModel", "FillStrategy",
    "MarketDataSnapshot", "MarketDataStatus",
    # V4.1 Shadow Ledger
    "ShadowExecutionLedger", "LedgerEntry", "DeviationEntry",
    # V4.1 Shadow Pipeline Runner
    "ShadowPipelineRunner", "ShadowPipelineConfig", "ShadowPipelineResult",
    # V4.6 Trade Filter & Slippage Control
    "TradeFilterEngine", "TradeFilterRule", "TradeContext",
    "FilterResult", "FilterReport", "FilterType", "FilterSeverity", "FilterStatus",
    "build_default_trade_filter_rules", "detect_board_type", "is_st_board",
    "SlippageController", "SlippageEstimator", "SlippageBudgetTracker",
    "SlippageBudget", "SlippageEstimate", "SlippageLimitAction", "BudgetPeriod",
    # V4.7 Order Book & Deep Execution Route
    "OrderBook", "OrderBookEntry", "OrderBookEvent", "OrderBookSnapshot",
    "PriceLevel", "BookSide", "OrderBookEventType",
    "DeepExecutionRouter", "RouteSelector", "RouteResult", "RouteConfig",
    "RoutePerformance", "RouteType", "RouteUrgency", "RouteRecommendation",
    # V4.8 Capital Safety Boundary
    "AuthorityTier", "CapitalActionType", "IncidentSeverity",
    "CapitalAllocationConfig", "AllocationLimit", "AllocationCheckResult",
    "CapitalAllocation",
    "CapitalAuthority", "AuthorityCheckResult",
    "CapitalSafetyMonitor", "CapitalUsageSnapshot", "CapitalAlert",
    "CapitalIncidentProtection", "CapitalIncidentAlert",
    "CapitalBoundaryEnforcer",
    "build_capital_safety_boundaries", "build_capital_safety_policy",
]

