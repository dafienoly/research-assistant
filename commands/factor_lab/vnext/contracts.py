"""Shared contracts for the Hermes VNext research and execution boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CST = timezone(timedelta(hours=8))


class DataStatus(str, Enum):
    OK = "OK"
    MISSING = "MISSING"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    WATCH_ONLY = "WATCH_ONLY"
    BACKTEST_ONLY = "BACKTEST_ONLY"
    BLOCKED = "BLOCKED"


class Tradability(str, Enum):
    TRADABLE = "tradable"
    RESTRICTED = "restricted"
    ETF_SUBSTITUTION = "ETF_substitution"
    WATCH_ONLY = "watch_only"
    PROXY_SIGNAL = "proxy_signal"
    RISK_HEDGE = "risk_hedge"
    EXECUTION_CANDIDATE = "execution_candidate"
    BLOCKED = "blocked"


class TradingMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE_DRY_RUN = "LIVE_DRY_RUN"
    LIVE_APPROVAL_REQUIRED = "LIVE_APPROVAL_REQUIRED"
    LIVE_ENABLED = "LIVE_ENABLED"
    LIVE_DISABLED = "LIVE_DISABLED"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"


class MainlineState(str, Enum):
    SEMI_DORMANT = "SEMI_DORMANT"
    SEMI_POLICY_WARMUP = "SEMI_POLICY_WARMUP"
    SEMI_MAINLINE_START = "SEMI_MAINLINE_START"
    SEMI_MAINLINE_CONFIRM = "SEMI_MAINLINE_CONFIRM"
    SEMI_ACCELERATION = "SEMI_ACCELERATION"
    SEMI_HIGH_DIVERGENCE = "SEMI_HIGH_DIVERGENCE"
    SEMI_ROTATION_INTERNAL = "SEMI_ROTATION_INTERNAL"
    SEMI_PULLBACK_HEALTHY = "SEMI_PULLBACK_HEALTHY"
    SEMI_POLICY_RESCUE = "SEMI_POLICY_RESCUE"
    SEMI_DISTRIBUTION = "SEMI_DISTRIBUTION"
    SEMI_RETREAT = "SEMI_RETREAT"
    SEMI_FAILURE = "SEMI_FAILURE"


class RegimeName(str, Enum):
    TECH_ATTACK = "TECH_ATTACK"
    RISK_ON_BROAD = "RISK_ON_BROAD"
    DEFENSIVE_ROTATION = "DEFENSIVE_ROTATION"
    LIQUIDITY_SHOCK = "LIQUIDITY_SHOCK"
    OVERSEAS_TECH_LEAD = "OVERSEAS_TECH_LEAD"
    A_SHARE_POLICY_ALPHA = "A_SHARE_POLICY_ALPHA"
    RANGE_BOUND = "RANGE_BOUND"
    CASH_OR_WAIT = "CASH_OR_WAIT"


class ReviewDecision(str, Enum):
    KEEP = "KEEP"
    TUNE = "TUNE"
    DOWNGRADE = "DOWNGRADE"
    RETIRE = "RETIRE"
    ESCALATE = "ESCALATE"
    WATCH = "WATCH"


def now_iso() -> str:
    return datetime.now(CST).isoformat()


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def finite_number(value: Any) -> float | None:
    """Return a finite float, preserving missing/invalid data as ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def mean_available(values: Iterable[Any]) -> float | None:
    available = [number for value in values if (number := finite_number(value)) is not None]
    if not available:
        return None
    return sum(available) / len(available)


@dataclass(slots=True)
class ComponentResult:
    status: DataStatus
    as_of: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["confidence"] = round(clamp(self.confidence), 4)
        return result


@dataclass(slots=True)
class SourceObservation:
    source: str
    status: DataStatus
    updated_at: str | None
    required_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    path: str | None = None
    records: int | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


class VNextDataError(RuntimeError):
    """Raised when a computation requires real inputs that are unavailable."""


class QualityStatus(str, Enum):
    """Canonical cross-process quality states without changing legacy DataStatus."""

    OK = "OK"
    MISSING = "MISSING"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    WATCH_ONLY = "WATCH_ONLY"
    BACKTEST_ONLY = "BACKTEST_ONLY"
    BLOCKED = "BLOCKED"
    PROVIDER_ERROR = "PROVIDER_ERROR"


def aware_now() -> datetime:
    return datetime.now(CST)


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON for hashes and signatures."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=False)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ContractModel(BaseModel):
    """Strict Hermes-owned boundary model; third-party objects never cross it."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=False)


class MarketDataEnvelope(ContractModel):
    dataset: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    requested_at: datetime
    observed_at: datetime
    available_at: datetime
    ingested_at: datetime = Field(default_factory=aware_now)
    as_of: str = Field(min_length=1)
    quality_status: QualityStatus
    coverage: float = Field(ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_snapshot_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str = "1.0"
    lineage: dict[str, Any] = Field(default_factory=dict)
    data: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_point_in_time(self) -> "MarketDataEnvelope":
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        if self.ingested_at < self.available_at:
            raise ValueError("ingested_at cannot precede available_at")
        return self


class ResearchSignal(ContractModel):
    signal_run_id: str = Field(min_length=1)
    as_of: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    factor_score: float | None = None
    ml_score: float | None = None
    rank: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    regime_applicability: float = Field(ge=0.0, le=1.0)
    semi_state_applicability: float = Field(ge=0.0, le=1.0)
    evidence_bundle_id: str = Field(min_length=1)
    quality_status: QualityStatus
    source_strategy: str = Field(min_length=1)
    model_version: str | None = None
    evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class TargetWeightLine(ContractModel):
    instrument_id: str = Field(min_length=1)
    current_weight: float = Field(ge=0.0, le=1.0)
    raw_target_weight: float = Field(ge=0.0, le=1.0)
    eligible_target_weight: float = Field(ge=0.0, le=1.0)
    risk_adjusted_target_weight: float = Field(ge=0.0, le=1.0)
    weight_delta: float = Field(ge=-1.0, le=1.0)
    source_strategy: str = Field(min_length=1)
    model_version: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    risk_budget: float = Field(ge=0.0, le=1.0)
    tradability: Tradability
    substitution_of: str | None = None
    quality_status: QualityStatus
    evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_tradability(self) -> "TargetWeightLine":
        non_executable = {
            Tradability.RESTRICTED,
            Tradability.WATCH_ONLY,
            Tradability.PROXY_SIGNAL,
            Tradability.BLOCKED,
        }
        if self.tradability in non_executable and self.eligible_target_weight > 0:
            raise ValueError("non-executable instrument must have eligible_target_weight=0")
        if self.tradability in non_executable and self.risk_adjusted_target_weight > 0:
            raise ValueError("non-executable instrument must have risk_adjusted_target_weight=0")
        if self.tradability == Tradability.ETF_SUBSTITUTION and not self.substitution_of:
            raise ValueError("ETF substitution must identify substitution_of")
        expected_delta = self.risk_adjusted_target_weight - self.current_weight
        if abs(self.weight_delta - expected_delta) > 1e-8:
            raise ValueError("weight_delta must equal risk_adjusted_target_weight-current_weight")
        return self


class TargetPortfolioWeights(ContractModel):
    portfolio_run_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    as_of: str = Field(min_length=1)
    universe_snapshot_id: str = Field(min_length=1)
    data_snapshot_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    model_version: str | None = None
    regime_state: str = Field(min_length=1)
    semi_mainline_state: str = Field(min_length=1)
    weights: list[TargetWeightLine]
    raw_weights: dict[str, float]
    eligibility_adjusted_weights: dict[str, float]
    risk_adjusted_weights: dict[str, float]
    cash_weight: float = Field(ge=0.0, le=1.0)
    constraints: dict[str, Any] = Field(default_factory=dict)
    substitutions: dict[str, str] = Field(default_factory=dict)
    evidence_bundle_id: str = Field(min_length=1)
    quality_status: QualityStatus
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def validate_weight_book(self) -> "TargetPortfolioWeights":
        instruments = [line.instrument_id for line in self.weights]
        if len(instruments) != len(set(instruments)):
            raise ValueError("target weight instruments must be unique")
        expected = {
            "raw_weights": {line.instrument_id: line.raw_target_weight for line in self.weights},
            "eligibility_adjusted_weights": {
                line.instrument_id: line.eligible_target_weight for line in self.weights
            },
            "risk_adjusted_weights": {
                line.instrument_id: line.risk_adjusted_target_weight for line in self.weights
            },
        }
        for field_name, expected_map in expected.items():
            actual = getattr(self, field_name)
            if set(actual) != set(expected_map):
                raise ValueError(f"{field_name} keys must match weights")
            if any(abs(float(actual[key]) - expected_map[key]) > 1e-8 for key in expected_map):
                raise ValueError(f"{field_name} values must match weight lines")
        total = sum(self.risk_adjusted_weights.values()) + self.cash_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError("risk_adjusted_weights plus cash_weight must sum to 1")
        expected_substitutions = {
            line.instrument_id: line.substitution_of
            for line in self.weights
            if line.substitution_of is not None
        }
        if self.substitutions != expected_substitutions:
            raise ValueError("substitutions must match weight-line substitution_of values")
        return self

    @property
    def target_weights_hash(self) -> str:
        return sha256_payload(self.to_dict())


class OrderDraft(ContractModel):
    order_draft_id: str = Field(default_factory=lambda: f"draft_{secrets.token_hex(8)}")
    approval_id: str = Field(default_factory=lambda: f"appr_{secrets.token_hex(8)}")
    portfolio_run_id: str = "legacy_unbound"
    account_snapshot_id: str = "legacy_unbound"
    position_snapshot_id: str = "legacy_unbound"
    instrument_id: str = Field(alias="symbol", min_length=1)
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    order_type: Literal["LIMIT", "MARKET", "BEST5"] = "LIMIT"
    limit_price: float | None = Field(default=None, gt=0)
    reason: str = Field(alias="rationale", min_length=1)
    risk_summary: list[str] = Field(default_factory=list)
    data_snapshot_id: str = "legacy_unbound"
    strategy_source: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    semiconductor_state: str = Field(min_length=1)
    model_score: float | None = None
    portfolio_impact: dict[str, Any] = Field(default_factory=dict)
    data_freshness: str = Field(min_length=1)
    account_permission: str = Field(min_length=1)
    alternative_etf: str | None = None
    watch_only: bool = False
    quality_status: QualityStatus = QualityStatus.BACKTEST_ONLY
    created_at: datetime = Field(default_factory=aware_now)
    expires_at: datetime = Field(default_factory=lambda: aware_now() + timedelta(minutes=5))
    draft_hash: str = ""

    @field_validator("side", mode="before")
    @classmethod
    def normalize_side(cls, value: Any) -> str:
        return str(value).upper()

    @model_validator(mode="after")
    def validate_and_hash(self) -> "OrderDraft":
        if self.order_type == "LIMIT" and self.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")
        if self.expires_at <= self.created_at:
            raise ValueError("order draft expires_at must follow created_at")
        expected = sha256_payload(self.hash_payload())
        if self.draft_hash and not hmac.compare_digest(self.draft_hash, expected):
            raise ValueError("order draft hash mismatch")
        object.__setattr__(self, "draft_hash", expected)
        return self

    @property
    def symbol(self) -> str:
        return self.instrument_id

    @property
    def rationale(self) -> str:
        return self.reason

    def hash_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            by_alias=False,
            exclude={"draft_hash"},
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class ApprovedOrderEnvelope(ContractModel):
    approval_id: str = Field(min_length=1)
    order_draft_id: str = Field(min_length=1)
    order_draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    order_draft: OrderDraft
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    expires_at: datetime
    one_time_nonce: str = Field(min_length=16)
    allowed_mode: TradingMode
    risk_snapshot_id: str = Field(min_length=1)
    kill_switch_snapshot: bool
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def bind_order(self) -> "ApprovedOrderEnvelope":
        if self.order_draft_id != self.order_draft.order_draft_id:
            raise ValueError("approved envelope order_draft_id mismatch")
        if not hmac.compare_digest(self.order_draft_hash, self.order_draft.draft_hash):
            raise ValueError("approved envelope order_draft_hash mismatch")
        if self.approval_id != self.order_draft.approval_id:
            raise ValueError("approved envelope approval_id mismatch")
        if self.expires_at > self.order_draft.expires_at:
            raise ValueError("approval cannot outlive order draft")
        return self

    def signature_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"signature"})

    def verify(self, secret: str, *, at: datetime | None = None) -> tuple[bool, str]:
        if not secret:
            return False, "approval_signing_key_missing"
        expected = hmac.new(
            secret.encode("utf-8"),
            canonical_json(self.signature_payload()).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(self.signature, expected):
            return False, "approval_signature_mismatch"
        if not hmac.compare_digest(self.order_draft_hash, self.order_draft.draft_hash):
            return False, "order_draft_hash_mismatch"
        now = at or aware_now()
        if now >= self.expires_at or now >= self.order_draft.expires_at:
            return False, "approval_expired"
        if self.kill_switch_snapshot:
            return False, "approval_created_under_kill_switch"
        return True, "approved_envelope_valid"

    @classmethod
    def sign(
        cls,
        *,
        order_draft: OrderDraft,
        approved_by: str,
        allowed_mode: TradingMode | str,
        risk_snapshot_id: str,
        secret: str,
        ttl_seconds: int = 300,
        approved_at: datetime | None = None,
        one_time_nonce: str | None = None,
        kill_switch_snapshot: bool = False,
    ) -> "ApprovedOrderEnvelope":
        if not secret:
            raise ValueError("approval signing key is required")
        if ttl_seconds < 1:
            raise ValueError("approval ttl_seconds must be positive")
        approved_time = approved_at or aware_now()
        expires_at = min(approved_time + timedelta(seconds=ttl_seconds), order_draft.expires_at)
        unsigned = {
            "approval_id": order_draft.approval_id,
            "order_draft_id": order_draft.order_draft_id,
            "order_draft_hash": order_draft.draft_hash,
            "order_draft": order_draft,
            "approved_by": approved_by,
            "approved_at": approved_time,
            "expires_at": expires_at,
            "one_time_nonce": one_time_nonce or secrets.token_urlsafe(24),
            "allowed_mode": TradingMode(allowed_mode),
            "risk_snapshot_id": risk_snapshot_id,
            "kill_switch_snapshot": kill_switch_snapshot,
        }
        signature = hmac.new(
            secret.encode("utf-8"),
            canonical_json(
                {
                    **unsigned,
                    "order_draft": order_draft.model_dump(mode="json", by_alias=False),
                    "allowed_mode": TradingMode(allowed_mode).value,
                    "approved_at": approved_time.isoformat(),
                    "expires_at": expires_at.isoformat(),
                }
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return cls(**unsigned, signature=signature)


class ExecutionEvent(ContractModel):
    event_id: str = Field(default_factory=lambda: secrets.token_hex(16))
    correlation_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    event_time: datetime = Field(default_factory=aware_now)
    broker: str
    mode: TradingMode
    order_id: str | None = None
    trade_id: str | None = None
    position_delta: float | None = None
    status: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    previous_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewRecord(ContractModel):
    review_id: str = Field(default_factory=lambda: f"review_{secrets.token_hex(8)}")
    correlation_id: str = Field(min_length=1)
    as_of: str = Field(min_length=1)
    decision: ReviewDecision
    layer_scores: dict[str, float]
    evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    quality_status: QualityStatus
    reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=aware_now)


def contract_json_schemas() -> dict[str, dict[str, Any]]:
    """Expose authoritative schemas for artifacts and cross-process validation."""
    models = (
        MarketDataEnvelope,
        ResearchSignal,
        TargetPortfolioWeights,
        OrderDraft,
        ApprovedOrderEnvelope,
        ExecutionEvent,
        ReviewRecord,
    )
    return {model.__name__: model.model_json_schema() for model in models}
