"""Shared contracts for the Hermes VNext research and execution boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Iterable


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
