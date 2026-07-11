"""Strict domain contracts for the quantitative decision closed loop."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, str_strip_whitespace=True
    )


class Book(str, Enum):
    CATALYST = "catalyst"
    SWING = "swing"
    CORE = "core"


class Severity(str, Enum):
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class AdviceMode(str, Enum):
    EXECUTABLE = "executable"
    WATCH_ONLY = "watch_only"
    BLOCKED = "blocked"


class RiskMode(str, Enum):
    NORMAL = "normal"
    NO_NEW_POSITIONS = "no_new_positions"
    REDUCE_HIGH_BETA = "reduce_high_beta"
    REDUCE_ONLY = "reduce_only"


class Position(StrictModel):
    symbol: str
    name: str = ""
    quantity: int = Field(ge=0)
    available_quantity: int = Field(default=0, ge=0)
    frozen_quantity: int = Field(default=0, ge=0)
    cost_price: float = Field(ge=0)
    market_price: float | None = Field(default=None, ge=0)
    instrument_type: Literal["stock", "etf"] = "stock"
    book: Book = Book.SWING
    theme: str = "unclassified"
    thesis: str = ""
    invalidation: str = ""

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def available_not_above_quantity(self):
        if self.available_quantity > self.quantity:
            raise ValueError("available_quantity cannot exceed quantity")
        if self.available_quantity + self.frozen_quantity > self.quantity:
            raise ValueError("available plus frozen quantity cannot exceed quantity")
        return self


class PositionSnapshot(StrictModel):
    snapshot_id: str
    as_of: datetime
    source: Literal["csv", "clipboard", "ocr", "manual", "miniqmt"]
    positions: list[Position]
    confirmed: bool = False
    content_hash: str


class PositionDiff(StrictModel):
    preview_id: str
    created_at: datetime
    source: str
    additions: list[Position] = Field(default_factory=list)
    removals: list[Position] = Field(default_factory=list)
    changes: list[dict[str, Any]] = Field(default_factory=list)
    unchanged: int = 0
    proposed_snapshot: PositionSnapshot
    quality_issues: list[dict[str, Any]] = Field(default_factory=list)
    requires_correction: bool = False


class QuoteSnapshot(StrictModel):
    symbol: str
    last_price: float = Field(gt=0)
    vwap: float | None = Field(default=None, gt=0)
    volume: float = Field(default=0, ge=0)
    average_volume: float | None = Field(default=None, gt=0)
    observed_at: datetime
    source: str
    freshness_seconds: int = Field(default=0, ge=0)


class DataItemStatus(StrictModel):
    name: str
    available: bool
    fresh: bool
    source: str | None = None
    as_of: datetime | None = None
    detail: str = ""


class DataGateResult(StrictModel):
    mode: AdviceMode
    confidence_multiplier: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    evaluated_at: datetime


class ActionCard(StrictModel):
    event_id: str
    severity: Severity
    symbol: str | None = None
    book: Book | None = None
    action: Literal[
        "warn",
        "reduce_half",
        "exit_remaining",
        "reentry_eligible",
        "freeze_buy",
        "reduce_high_beta",
        "reduce_only",
    ]
    quantity: int | None = Field(default=None, ge=0)
    reason: str
    current_return_pct: float | None = None
    peak_return_pct: float | None = None
    giveback_points: float | None = None
    advice_mode: AdviceMode
    generated_at: datetime
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    acknowledged_at: datetime | None = None


class PortfolioRiskInput(StrictModel):
    equity: float = Field(gt=0)
    intraday_peak_equity: float = Field(gt=0)
    previous_close_equity: float = Field(gt=0)
    rolling_20d_peak_equity: float = Field(gt=0)


class PortfolioRiskResult(StrictModel):
    mode: RiskMode
    intraday_drawdown_pct: float
    daily_return_pct: float
    rolling_20d_drawdown_pct: float
    actions: list[str] = Field(default_factory=list)
    evaluated_at: datetime


class PlannedOrder(StrictModel):
    order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    limit_price: float = Field(gt=0)
    book: Book
    strategy: str
    reason: str

    @property
    def amount(self) -> float:
        return self.quantity * self.limit_price


class DailyExecutionPlan(StrictModel):
    plan_id: str
    trading_date: str
    strategy_summary: str
    risk_budget: dict[str, float]
    max_order_amount: float = Field(gt=0)
    max_total_amount: float = Field(gt=0)
    orders: list[PlannedOrder]
    parameter_version: str
    plan_hash: str
    created_at: datetime


class DailyAuthorization(StrictModel):
    authorization_id: str
    plan: DailyExecutionPlan
    status: Literal["pending", "active", "revoked", "expired"]
    confirmation_nonce_hash: str
    activated_at: datetime | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


class ExecutionRequest(StrictModel):
    order: PlannedOrder
    event_id: str | None = None
    hard_risk_sell: bool = False
    available_quantity: int | None = Field(default=None, ge=0)
    data_mode: AdviceMode
    audit_passed: bool
    parameter_version: str
    plan_hash: str
    risk_mode: RiskMode = RiskMode.NORMAL


class Candidate(StrictModel):
    candidate_id: str
    symbol: str
    name: str
    instrument_type: Literal["stock", "etf"] = "stock"
    book: Book
    holding_period: str
    catalyst_score: float = Field(ge=0, le=100)
    industry_fundamental_score: float = Field(ge=0, le=100)
    technical_flow_score: float = Field(ge=0, le=100)
    risk_score: float = Field(ge=0, le=100)
    catalyst_evidence: list[dict[str, Any]]
    industry_logic: str
    fundamental_valuation: str
    entry_plan: str
    entry_reference_price: float | None = Field(default=None, gt=0)
    no_chase_zone: str
    position_pct: float = Field(gt=0, le=0.30)
    invalidation: str
    exit_plan: str
    crowding_risk: str
    benchmark_symbol: str | None = None
    data_gate: DataGateResult
    total_score: float | None = None


class PassList(StrictModel):
    decision_id: str
    generated_at: datetime
    primary: list[Candidate]
    backup: list[Candidate]
    no_opportunity_reason: str | None = None

    @model_validator(mode="after")
    def validate_limits(self):
        if len(self.primary) > 3 or len(self.backup) > 5:
            raise ValueError(
                "PassList supports at most 3 primary and 5 backup candidates"
            )
        if not self.primary and not self.no_opportunity_reason:
            raise ValueError("empty primary list requires no_opportunity_reason")
        return self


class ReviewMetrics(StrictModel):
    returns: dict[str, float | None]
    excess_returns: dict[str, float | None]
    mfe_pct: float | None
    mae_pct: float | None
    slippage_bps: float | None
    total_cost: float
    execution_feasible: bool | None
    system_counterfactual_return_pct: float | None
    actual_minus_system_pct: float | None
    attribution: dict[str, str]


class ReviewRecord(StrictModel):
    review_id: str
    trading_date: str
    decision_id: str | None = None
    event_id: str | None = None
    order_id: str | None = None
    parameter_version: str | None = None
    symbol: str
    book: Book
    execution_status: str
    metrics: ReviewMetrics | None = None
    benchmark_symbol: str | None = None
    benchmark_missing_reason: str | None = None
    created_at: datetime


class ParameterCandidate(StrictModel):
    candidate_id: str
    parameter: str
    current_value: Any
    proposed_value: Any
    evidence: dict[str, Any]
    oos_status: Literal["pending", "passed", "failed"] = "pending"
    human_status: Literal["pending", "approved", "rejected"] = "pending"
    status: Literal["candidate", "promoted", "rejected"] = "candidate"
    created_at: datetime
    promoted_at: datetime | None = None
    decision_id: str | None = None
    event_id: str | None = None
    order_id: str | None = None


class DecisionCycleResult(StrictModel):
    cycle_id: str
    decision_id: str | None = None
    started_at: datetime
    completed_at: datetime
    status: Literal["ok", "degraded", "blocked", "skipped"]
    data_gate: dict[str, Any]
    portfolio_risk: PortfolioRiskResult | None = None
    action_cards: list[ActionCard] = Field(default_factory=list)
    notification_receipts: list[dict[str, Any]] = Field(default_factory=list)
    execution_results: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation: dict[str, Any] | None = None
    blockers: list[str] = Field(default_factory=list)
