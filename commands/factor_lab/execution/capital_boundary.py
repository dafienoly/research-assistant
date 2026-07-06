"""V4.8 Capital Safety Boundary — 资金安全边界、额度、权限、异常保护

Defines capital-specific safety boundaries that integrate with the existing
risk boundary system (V4.0) and trade filtering (V4.6) to provide a
comprehensive capital safety layer for the controlled pipeline.

Components:
  1. CapitalAllocation — Per-strategy, per-asset, and total capital limits
  2. CapitalAuthority  — Trading authority tiers and permission checks
  3. CapitalSafetyMonitor — Real-time capital usage tracking
  4. CapitalIncidentProtection — Abnormal capital flow detection
  5. CapitalBoundaryEnforcer — Integrated enforcer for all capital boundaries

Design principles:
  - All limits are configurable (sensible defaults provided)
  - All checks produce structured results for auditing
  - All abnormal patterns are logged as incidents
  - Integration with existing BoundaryEnforcer for pipeline enforcement
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from factor_lab.execution.risk_boundary import (
    RiskBoundary, RiskPolicy, BoundaryEnforcer, ForbiddenActionRegistry,
)

CST = timezone(timedelta(hours=8))


# ===========================================================================
# Enums
# ===========================================================================

class AuthorityTier(Enum):
    """Authority tiers for capital operations.

    Each tier inherits all permissions from lower tiers.
    """
    OBSERVER = "observer"       # Can view capital state only
    TRADER = "trader"           # Can execute trades within limits
    STRATEGIST = "strategist"   # Can modify strategy allocations
    ADMIN = "admin"             # Can change limits and policies
    SUPER_ADMIN = "super_admin" # Can override any boundary (audited)


class CapitalActionType(Enum):
    """Types of capital-related actions subject to authority checks."""
    VIEW_CAPITAL = "view_capital"
    VIEW_ALLOCATION = "view_allocation"
    EXECUTE_TRADE = "execute_trade"
    MODIFY_ALLOCATION = "modify_allocation"
    CHANGE_LIMITS = "change_limits"
    OVERRIDE_BOUNDARY = "override_boundary"
    APPROVE_CAPITAL_FLOW = "approve_capital_flow"
    DISABLE_SAFETY = "disable_safety"


class IncidentSeverity(Enum):
    """Severity levels for capital incidents."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKER = "blocker"


# ===========================================================================
# Capital Allocation — 额度
# ===========================================================================

@dataclass
class AllocationLimit:
    """A single allocation limit definition.

    Each limit constrains how much capital can be allocated to a
    specific strategy, asset, or the total portfolio.
    """
    scope: str                # "global" | "strategy:<name>" | "asset:<symbol>"
    max_capital: float = 0.0  # Maximum capital in CNY (0 = unlimited)
    max_pct: float = 0.0      # Maximum percentage of total capital (0-1, 0 = unlimited)
    min_capital: float = 0.0  # Minimum capital reserve in CNY
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapitalAllocationConfig:
    """Configuration for capital allocation limits.

    Defines the full set of limits governing capital usage across
    strategies, assets, and the total portfolio.

    Defaults provide a conservative safety profile.
    """
    # Global limits
    total_capital: float = 1_000_000.0       # Total available capital (CNY)
    max_total_exposure_pct: float = 0.95     # Max 95% of total capital deployed
    min_free_capital: float = 50_000.0       # At least 50k CNY kept free
    max_daily_turnover_pct: float = 0.30     # Max 30% turnover per day

    # Per-strategy limits (applied to each strategy)
    max_per_strategy_pct: float = 0.40       # No single strategy > 40%
    max_per_strategy_capital: float = 0.0    # 0 = unlimited beyond pct cap

    # Per-asset limits
    max_per_asset_pct: float = 0.15          # No single asset > 15%
    max_per_asset_capital: float = 0.0       # 0 = unlimited beyond pct cap

    # Sector/industry limits
    max_per_sector_pct: float = 0.40         # No single sector > 40%
    max_per_industry_pct: float = 0.25       # No single industry > 25%

    # Order-level limits
    max_single_order_capital: float = 200_000.0  # Max 200k per order
    max_daily_orders: int = 50                    # Max 50 orders per day
    max_daily_trade_capital: float = 500_000.0    # Max 500k total traded per day

    # Custom per-scope overrides
    scope_overrides: dict = field(default_factory=dict)

    def get_limit_for(self, scope: str) -> AllocationLimit:
        """Get the effective allocation limit for a scope.

        Checks scope_overrides first, then falls back to global defaults.
        """
        if scope in self.scope_overrides:
            return self.scope_overrides[scope]

        # Build from defaults
        if scope == "global":
            return AllocationLimit(
                scope=scope,
                max_capital=self.total_capital,
                max_pct=1.0,
                min_capital=self.min_free_capital,
                description="Global capital allocation limit",
            )
        elif scope.startswith("strategy:"):
            return AllocationLimit(
                scope=scope,
                max_capital=self.max_per_strategy_capital,
                max_pct=self.max_per_strategy_pct,
                description=f"Per-strategy limit for {scope.split(':', 1)[1]}",
            )
        elif scope.startswith("asset:"):
            return AllocationLimit(
                scope=scope,
                max_capital=self.max_per_asset_capital,
                max_pct=self.max_per_asset_pct,
                description=f"Per-asset limit for {scope.split(':', 1)[1]}",
            )
        elif scope.startswith("sector:"):
            return AllocationLimit(
                scope=scope,
                max_pct=self.max_per_sector_pct,
                description=f"Sector limit for {scope.split(':', 1)[1]}",
            )
        elif scope.startswith("industry:"):
            return AllocationLimit(
                scope=scope,
                max_pct=self.max_per_industry_pct,
                description=f"Industry limit for {scope.split(':', 1)[1]}",
            )
        else:
            return AllocationLimit(scope=scope, enabled=False, description=f"Unknown scope: {scope}")

    def set_override(self, scope: str, limit: AllocationLimit):
        """Set a custom override for a specific scope."""
        self.scope_overrides[scope] = limit

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scope_overrides"] = {k: v.to_dict() for k, v in self.scope_overrides.items()}
        return d


@dataclass
class AllocationCheckResult:
    """Result of checking a capital allocation against limits."""
    allowed: bool = True
    blocked: bool = False
    scope: str = ""
    reason: str = ""
    requested_amount: float = 0.0
    limit_amount: float = 0.0
    current_usage: float = 0.0
    severity: str = "info"

    def to_dict(self) -> dict:
        return asdict(self)


class CapitalAllocation:
    """Manages and enforces capital allocation limits.

    Tracks how capital is allocated across strategies and assets,
    and checks proposed allocations against configured limits.

    Usage:
        alloc = CapitalAllocation(config=CapitalAllocationConfig())
        result = alloc.check_allocation("strategy:mean_reversion", 300_000)
        if not result.allowed:
            print(f"Blocked: {result.reason}")
    """

    def __init__(self, config: Optional[CapitalAllocationConfig] = None):
        self.config = config or CapitalAllocationConfig()
        # Current usage tracking: {scope: current_amount}
        self._usage: dict[str, float] = {}
        # Tracking by category
        self._daily_trade_count: int = 0
        self._daily_trade_capital: float = 0.0
        self._daily_reset_at: str = datetime.now(CST).isoformat()

    # -- Usage tracking ------------------------------------------------

    def record_usage(self, scope: str, amount: float):
        """Record capital usage for a scope."""
        current = self._usage.get(scope, 0.0)
        self._usage[scope] = current + amount

    def record_daily_trade(self, amount: float):
        """Record a daily trade for turnover tracking.

        Resets daily counters if a new day has started.
        """
        now = datetime.now(CST)
        last_reset = datetime.fromisoformat(self._daily_reset_at)
        if now.date() != last_reset.date():
            self._daily_trade_count = 0
            self._daily_trade_capital = 0.0
            self._daily_reset_at = now.isoformat()

        self._daily_trade_count += 1
        self._daily_trade_capital += amount

    def get_usage(self, scope: str) -> float:
        """Get current capital usage for a scope."""
        return self._usage.get(scope, 0.0)

    def get_total_usage(self) -> float:
        """Get total capital usage across all scopes.

        Sums all recorded usage. For overlapping scopes (e.g., a strategy
        and its constituent assets), this may double-count — callers should
        query the specific scope they care about.
        """
        return sum(self._usage.values())

    def get_available_capital(self) -> float:
        """Get available (unallocated) capital."""
        return max(0.0, self.config.total_capital - self.get_total_usage())

    def reset_usage(self):
        """Reset all usage tracking (e.g., start of new trading day)."""
        self._usage.clear()
        self._daily_trade_count = 0
        self._daily_trade_capital = 0.0
        self._daily_reset_at = datetime.now(CST).isoformat()

    # -- Check methods ------------------------------------------------

    def check_allocation(self, scope: str, amount: float,
                         current_usage: Optional[float] = None) -> AllocationCheckResult:
        """Check if allocating `amount` to `scope` is within limits."""
        limit = self.config.get_limit_for(scope)

        if not limit.enabled:
            return AllocationCheckResult(
                allowed=True,
                scope=scope,
                reason=f"No limit defined for scope '{scope}'",
                requested_amount=amount,
            )

        # Check max_capital (absolute)
        if limit.max_capital > 0:
            usage = current_usage if current_usage is not None else self.get_usage(scope)
            projected = usage + amount
            if projected > limit.max_capital:
                return AllocationCheckResult(
                    allowed=False,
                    blocked=True,
                    scope=scope,
                    reason=f"Capital limit for '{scope}': {projected:.0f} exceeds "
                           f"max {limit.max_capital:.0f} CNY",
                    requested_amount=amount,
                    limit_amount=limit.max_capital,
                    current_usage=usage,
                    severity="blocker",
                )

        # Check max_pct (relative to total capital)
        if limit.max_pct > 0:
            usage = current_usage if current_usage is not None else self.get_usage(scope)
            projected_pct = (usage + amount) / self.config.total_capital
            if projected_pct > limit.max_pct:
                return AllocationCheckResult(
                    allowed=False,
                    blocked=True,
                    scope=scope,
                    reason=f"Percentage limit for '{scope}': {projected_pct:.1%} exceeds "
                           f"max {limit.max_pct:.0%}",
                    requested_amount=amount,
                    limit_amount=limit.max_pct * self.config.total_capital,
                    current_usage=usage,
                    severity="blocker",
                )

        # Check free capital reserve
        if scope == "global":
            free = self.get_available_capital() - amount
            if free < limit.min_capital:
                return AllocationCheckResult(
                    allowed=False,
                    blocked=True,
                    scope=scope,
                    reason=f"Free capital {free:.0f} would drop below "
                           f"minimum reserve {limit.min_capital:.0f} CNY",
                    requested_amount=amount,
                    limit_amount=limit.min_capital,
                    current_usage=self.get_total_usage(),
                    severity="blocker",
                )

        # Check daily trade count
        if not self._check_daily_order_limit():
            return AllocationCheckResult(
                allowed=False,
                blocked=True,
                scope="daily",
                reason=f"Daily order limit ({self.config.max_daily_orders}) reached",
                requested_amount=amount,
                limit_amount=float(self.config.max_daily_orders),
                current_usage=float(self._daily_trade_count),
                severity="warning",
            )

        return AllocationCheckResult(
            allowed=True,
            scope=scope,
            reason=f"Allocation of {amount:.0f} to '{scope}' within limits",
            requested_amount=amount,
            current_usage=self.get_usage(scope),
        )

    def check_order(self, amount: float) -> AllocationCheckResult:
        """Check a single order against capital constraints."""
        # Single order max
        if self.config.max_single_order_capital > 0 and amount > self.config.max_single_order_capital:
            return AllocationCheckResult(
                allowed=False,
                blocked=True,
                scope="order",
                reason=f"Order amount {amount:.0f} exceeds max single order "
                       f"{self.config.max_single_order_capital:.0f} CNY",
                requested_amount=amount,
                limit_amount=self.config.max_single_order_capital,
                severity="blocker",
            )

        # Daily trade capital limit
        projected_daily = self._daily_trade_capital + amount
        if self.config.max_daily_trade_capital > 0 and projected_daily > self.config.max_daily_trade_capital:
            return AllocationCheckResult(
                allowed=False,
                blocked=True,
                scope="daily",
                reason=f"Daily trade capital {projected_daily:.0f} would exceed "
                       f"limit {self.config.max_daily_trade_capital:.0f} CNY",
                requested_amount=amount,
                limit_amount=self.config.max_daily_trade_capital,
                current_usage=self._daily_trade_capital,
                severity="warning",
            )

        return AllocationCheckResult(
            allowed=True,
            scope="order",
            reason=f"Order amount {amount:.0f} within limits",
            requested_amount=amount,
        )

    def _check_daily_order_limit(self) -> bool:
        """Check if daily order count is within limit."""
        if self.config.max_daily_orders <= 0:
            return True
        return self._daily_trade_count < self.config.max_daily_orders


# ===========================================================================
# Capital Authority — 权限
# ===========================================================================

# Permission matrix: which tier can perform which action
_TIER_PERMISSIONS: dict[AuthorityTier, set[CapitalActionType]] = {
    AuthorityTier.OBSERVER: {
        CapitalActionType.VIEW_CAPITAL,
        CapitalActionType.VIEW_ALLOCATION,
    },
    AuthorityTier.TRADER: {
        CapitalActionType.VIEW_CAPITAL,
        CapitalActionType.VIEW_ALLOCATION,
        CapitalActionType.EXECUTE_TRADE,
    },
    AuthorityTier.STRATEGIST: {
        CapitalActionType.VIEW_CAPITAL,
        CapitalActionType.VIEW_ALLOCATION,
        CapitalActionType.EXECUTE_TRADE,
        CapitalActionType.MODIFY_ALLOCATION,
    },
    AuthorityTier.ADMIN: {
        CapitalActionType.VIEW_CAPITAL,
        CapitalActionType.VIEW_ALLOCATION,
        CapitalActionType.EXECUTE_TRADE,
        CapitalActionType.MODIFY_ALLOCATION,
        CapitalActionType.CHANGE_LIMITS,
        CapitalActionType.APPROVE_CAPITAL_FLOW,
    },
    AuthorityTier.SUPER_ADMIN: {
        CapitalActionType.VIEW_CAPITAL,
        CapitalActionType.VIEW_ALLOCATION,
        CapitalActionType.EXECUTE_TRADE,
        CapitalActionType.MODIFY_ALLOCATION,
        CapitalActionType.CHANGE_LIMITS,
        CapitalActionType.APPROVE_CAPITAL_FLOW,
        CapitalActionType.OVERRIDE_BOUNDARY,
        CapitalActionType.DISABLE_SAFETY,
    },
}

# Amount-based permission thresholds (CNY)
# Amounts above these thresholds require higher authority
_AMOUNT_THRESHOLDS: dict[AuthorityTier, float] = {
    AuthorityTier.OBSERVER: 0.0,
    AuthorityTier.TRADER: 100_000.0,        # Trader can execute up to 100k
    AuthorityTier.STRATEGIST: 500_000.0,     # Strategist can execute up to 500k
    AuthorityTier.ADMIN: 2_000_000.0,        # Admin can execute up to 2M
    AuthorityTier.SUPER_ADMIN: float("inf"), # Super admin no limit
}


@dataclass
class AuthorityCheckResult:
    """Result of an authority check."""
    allowed: bool = True
    blocked: bool = False
    action: str = ""
    tier: str = ""
    reason: str = ""
    requires_higher_tier: str = ""
    amount: float = 0.0
    amount_allowed: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class CapitalAuthority:
    """Manages trading authority and permission checks.

    Provides a permission system for capital operations based on
    authority tiers. Each tier grants access to specific actions,
    and amount-based thresholds further constrain execution.

    Usage:
        auth = CapitalAuthority()
        result = auth.check_permission(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            amount=50_000,
        )
        if not result.allowed:
            print(f"Blocked: {result.reason}")
    """

    def __init__(self):
        self._audit_log: list = []

    @classmethod
    def get_required_tier(cls, action: CapitalActionType) -> AuthorityTier:
        """Get the minimum authority tier required for an action."""
        for tier in list(AuthorityTier):  # Ordered from lowest to highest
            if action in _TIER_PERMISSIONS.get(tier, set()):
                return tier
        return AuthorityTier.SUPER_ADMIN  # Fallback: require highest

    @classmethod
    def tier_has_permission(cls, tier: AuthorityTier, action: CapitalActionType) -> bool:
        """Check if a tier has permission for an action."""
        return action in _TIER_PERMISSIONS.get(tier, set())

    @classmethod
    def check_amount_threshold(cls, tier: AuthorityTier, amount: float) -> bool:
        """Check if amount is within the tier's threshold."""
        threshold = _AMOUNT_THRESHOLDS.get(tier, 0.0)
        return amount <= threshold

    @classmethod
    def get_tier_threshold(cls, tier: AuthorityTier) -> float:
        """Get the amount threshold for a tier."""
        return _AMOUNT_THRESHOLDS.get(tier, 0.0)

    def check_permission(self, tier: AuthorityTier,
                         action: CapitalActionType,
                         amount: float = 0.0,
                         context: dict = None) -> AuthorityCheckResult:
        """Check if a tier is authorized to perform an action.

        Args:
            tier: The authority tier to check
            action: The action being requested
            amount: Optional amount involved (for amount-based gating)
            context: Optional context dict for audit trail

        Returns:
            AuthorityCheckResult with allowed/blocked status
        """
        # Check action permission
        if not self.tier_has_permission(tier, action):
            required = self.get_required_tier(action)
            result = AuthorityCheckResult(
                allowed=False,
                blocked=True,
                action=action.value,
                tier=tier.value,
                reason=f"Tier '{tier.value}' not authorized for '{action.value}'. "
                       f"Requires at least '{required.value}'",
                requires_higher_tier=required.value,
                amount=amount,
            )
            self._audit_log.append(result.to_dict())
            return result

        # Check amount threshold (only for EXECUTE_TRADE and MODIFY_ALLOCATION)
        if amount > 0 and action in (
            CapitalActionType.EXECUTE_TRADE,
            CapitalActionType.MODIFY_ALLOCATION,
            CapitalActionType.APPROVE_CAPITAL_FLOW,
        ):
            if not self.check_amount_threshold(tier, amount):
                required = self._find_tier_for_amount(amount)
                result = AuthorityCheckResult(
                    allowed=False,
                    blocked=True,
                    action=action.value,
                    tier=tier.value,
                    reason=f"Amount {amount:.0f} exceeds tier '{tier.value}' "
                           f"threshold of {self.get_tier_threshold(tier):.0f}. "
                           f"Requires at least '{required.value}'",
                    requires_higher_tier=required.value,
                    amount=amount,
                    amount_allowed=False,
                )
                self._audit_log.append(result.to_dict())
                return result

        result = AuthorityCheckResult(
            allowed=True,
            action=action.value,
            tier=tier.value,
            reason=f"Tier '{tier.value}' authorized for '{action.value}'",
            amount=amount,
            amount_allowed=True,
        )
        self._audit_log.append(result.to_dict())
        return result

    def _find_tier_for_amount(self, amount: float) -> AuthorityTier:
        """Find the minimum tier that can handle the given amount."""
        for tier in list(AuthorityTier):
            if self.check_amount_threshold(tier, amount):
                return tier
        return AuthorityTier.SUPER_ADMIN

    def get_audit_log(self) -> list:
        """Get the full audit log of authority checks."""
        return list(self._audit_log)

    def clear_audit_log(self):
        """Clear the audit log."""
        self._audit_log.clear()


# ===========================================================================
# Capital Safety Monitor — 资金安全监控
# ===========================================================================

@dataclass
class CapitalUsageSnapshot:
    """Snapshot of capital usage across all tracked dimensions."""
    timestamp: str = ""
    total_capital: float = 0.0
    total_used: float = 0.0
    total_free: float = 0.0
    usage_pct: float = 0.0
    per_strategy: dict = field(default_factory=dict)
    per_asset: dict = field(default_factory=dict)
    per_sector: dict = field(default_factory=dict)
    daily_trade_count: int = 0
    daily_trade_capital: float = 0.0
    n_alerts: int = 0
    alerts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapitalAlert:
    """An alert generated by the capital safety monitor."""
    alert_id: str = ""
    timestamp: str = ""
    severity: str = "info"
    category: str = ""       # "allocation" | "authority" | "exposure" | "abnormal"
    message: str = ""
    scope: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class CapitalSafetyMonitor:
    """Monitors capital usage and generates alerts for violations.

    Tracks real-time capital usage across strategies, assets, and sectors,
    and compares against configured limits. Generates structured alerts
    when limits are approached or exceeded.

    Usage:
        monitor = CapitalSafetyMonitor(allocation=allocation)
        snapshot = monitor.snapshot()
        alerts = monitor.check_all()
        for alert in alerts:
            print(f"[{alert.severity}] {alert.message}")
    """

    def __init__(self, allocation: Optional[CapitalAllocation] = None):
        self.allocation = allocation or CapitalAllocation()
        self._alerts: list[CapitalAlert] = []
        self._alert_counter: int = 0

    def _next_alert_id(self) -> str:
        self._alert_counter += 1
        return f"alert_{self._alert_counter:04d}"

    def check_exposure(self) -> list[CapitalAlert]:
        """Check total exposure against limits."""
        alerts = []
        total_used = self.allocation.get_total_usage()
        total_cap = self.allocation.config.total_capital
        usage_pct = total_used / total_cap if total_cap > 0 else 0.0

        # Check total exposure
        if usage_pct > self.allocation.config.max_total_exposure_pct:
            alerts.append(CapitalAlert(
                alert_id=self._next_alert_id(),
                severity="warning",
                category="exposure",
                message=f"Total exposure {usage_pct:.1%} exceeds "
                        f"max {self.allocation.config.max_total_exposure_pct:.0%}",
                scope="global",
                current_value=total_used,
                threshold=self.allocation.config.max_total_exposure_pct * total_cap,
            ))

        # Check free capital
        free = self.allocation.get_available_capital()
        if free < self.allocation.config.min_free_capital:
            severity = "critical" if free < self.allocation.config.min_free_capital * 0.5 else "warning"
            alerts.append(CapitalAlert(
                alert_id=self._next_alert_id(),
                severity=severity,
                category="exposure",
                message=f"Free capital {free:.0f} below minimum "
                        f"{self.allocation.config.min_free_capital:.0f} CNY",
                scope="global",
                current_value=free,
                threshold=self.allocation.config.min_free_capital,
            ))

        # Check daily turnover
        if self.allocation.config.total_capital > 0:
            turnover_pct = self.allocation._daily_trade_capital / self.allocation.config.total_capital
            if turnover_pct > self.allocation.config.max_daily_turnover_pct:
                alerts.append(CapitalAlert(
                    alert_id=self._next_alert_id(),
                    severity="warning",
                    category="exposure",
                    message=f"Daily turnover {turnover_pct:.1%} exceeds "
                            f"max {self.allocation.config.max_daily_turnover_pct:.0%}",
                    scope="daily",
                    current_value=self.allocation._daily_trade_capital,
                    threshold=self.allocation.config.max_daily_turnover_pct * self.allocation.config.total_capital,
                ))

        self._alerts.extend(alerts)
        return alerts

    def check_all(self) -> list[CapitalAlert]:
        """Run all monitor checks and return new alerts."""
        return self.check_exposure()

    def snapshot(self) -> CapitalUsageSnapshot:
        """Generate a full capital usage snapshot."""
        total_used = self.allocation.get_total_usage()
        total_cap = self.allocation.config.total_capital
        usage_pct = total_used / total_cap if total_cap > 0 else 0.0

        # Group usage by category
        per_strategy = {}
        per_asset = {}
        per_sector = {}
        for scope, amount in self.allocation._usage.items():
            if scope.startswith("strategy:"):
                per_strategy[scope] = amount
            elif scope.startswith("asset:"):
                per_asset[scope] = amount
            elif scope.startswith("sector:"):
                per_sector[scope] = amount

        return CapitalUsageSnapshot(
            timestamp=datetime.now(CST).isoformat(),
            total_capital=total_cap,
            total_used=total_used,
            total_free=self.allocation.get_available_capital(),
            usage_pct=usage_pct,
            per_strategy=per_strategy,
            per_asset=per_asset,
            per_sector=per_sector,
            daily_trade_count=self.allocation._daily_trade_count,
            daily_trade_capital=self.allocation._daily_trade_capital,
            n_alerts=len(self._alerts),
            alerts=[a.to_dict() for a in self._alerts[-20:]],
        )

    def get_alerts(self, severity: Optional[str] = None) -> list[CapitalAlert]:
        """Get alerts, optionally filtered by severity."""
        if severity:
            return [a for a in self._alerts if a.severity == severity]
        return list(self._alerts)

    def clear_alerts(self):
        """Clear all alerts."""
        self._alerts.clear()


# ===========================================================================
# Capital Incident Protection — 异常保护
# ===========================================================================

@dataclass
class CapitalIncidentAlert:
    """Alert for abnormal capital activity."""
    alert_id: str = ""
    timestamp: str = ""
    severity: str = "warning"
    pattern: str = ""          # "rapid_position_change" | "circular_trade" | "unusual_size" | "wash_trade" | "velocity"
    message: str = ""
    scope: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class CapitalIncidentProtection:
    """Detects and alerts on abnormal capital flow patterns.

    Monitors for:
      1. Rapid position changes — positions changing too quickly
      2. Unusual order sizes — orders significantly larger than average
      3. High-frequency activity — too many trades in a short window
      4. Concentrated activity — all activity in a single asset/sector
      5. Velocity anomalies — capital flow velocity exceeding thresholds

    Usage:
        protector = CapitalIncidentProtection()
        protector.record_trade("000001.SZ", 100_000)
        alerts = protector.check_all()
        for alert in alerts:
            print(f"[{alert.severity}] {alert.pattern}: {alert.message}")
    """

    def __init__(self):
        # Trade history for pattern detection
        self._trade_history: list[dict] = []
        self._position_changes: dict[str, list[dict]] = {}  # symbol -> [(timestamp, delta)]
        self._alerts: list[CapitalIncidentAlert] = []
        self._alert_counter: int = 0

        # Configuration thresholds
        self.max_position_change_pct: float = 0.25       # Max 25% position change per hour
        self.max_trades_per_minute: int = 10              # Max 10 trades per minute
        self.unusual_size_multiplier: float = 3.0          # 3x average is unusual
        self.max_concentration_pct: float = 0.80           # Max 80% in one asset
        self.velocity_window_seconds: int = 300            # 5-minute velocity window

    def _next_alert_id(self) -> str:
        self._alert_counter += 1
        return f"inc_{self._alert_counter:04d}"

    def record_trade(self, symbol: str, amount: float,
                     side: str = "buy", timestamp: str = ""):
        """Record a trade for pattern analysis."""
        record = {
            "symbol": symbol,
            "amount": amount,
            "side": side,
            "timestamp": timestamp or datetime.now(CST).isoformat(),
        }
        self._trade_history.append(record)

        # Track per-symbol position changes
        if symbol not in self._position_changes:
            self._position_changes[symbol] = []
        self._position_changes[symbol].append({
            "timestamp": record["timestamp"],
            "amount": amount if side == "buy" else -amount,
        })

    def check_rapid_position_change(self) -> list[CapitalIncidentAlert]:
        """Detect positions changing too quickly."""
        alerts = []
        now = datetime.now(CST)
        window_start = now - timedelta(hours=1)

        for symbol, changes in self._position_changes.items():
            recent = [
                c for c in changes
                if datetime.fromisoformat(c["timestamp"]) >= window_start
            ]
            if not recent:
                continue

            total_delta = abs(sum(c["amount"] for c in recent))
            # We need a reference to know what "25% of position" means.
            # Without the full position size, we estimate from cumulative history.
            cumulative = sum(c["amount"] for c in changes)
            base = abs(cumulative - sum(c["amount"] for c in recent))

            # When base is 0, all position changes happened in the window.
            # Treat this as a 100% change rate relative to the window.
            if base == 0:
                change_pct = 1.0
            else:
                change_pct = total_delta / (base + total_delta)

            if change_pct > self.max_position_change_pct:
                    alerts.append(CapitalIncidentAlert(
                        alert_id=self._next_alert_id(),
                        severity="warning",
                        pattern="rapid_position_change",
                        message=f"Position in {symbol} changed {change_pct:.1%} in the last hour "
                                f"(threshold: {self.max_position_change_pct:.0%})",
                        scope=symbol,
                        details={
                            "symbol": symbol,
                            "change_pct": round(change_pct, 4),
                            "threshold": self.max_position_change_pct,
                            "n_changes": len(recent),
                            "total_delta": total_delta,
                        },
                    ))

        self._alerts.extend(alerts)
        return alerts

    def check_unusual_order_size(self) -> list[CapitalIncidentAlert]:
        """Detect orders significantly larger than the average."""
        alerts = []
        if len(self._trade_history) < 5:
            return alerts

        amounts = [t["amount"] for t in self._trade_history]
        avg = sum(amounts) / len(amounts)
        std = (sum((a - avg) ** 2 for a in amounts) / len(amounts)) ** 0.5

        if std == 0:
            return alerts

        # Check the most recent trade
        latest = self._trade_history[-1]
        z_score = (latest["amount"] - avg) / std

        if z_score > self.unusual_size_multiplier:
            alerts.append(CapitalIncidentAlert(
                alert_id=self._next_alert_id(),
                severity="warning",
                pattern="unusual_size",
                message=f"Order {latest['amount']:.0f} for {latest['symbol']} is "
                        f"{z_score:.1f} stddev above mean ({avg:.0f})",
                scope=latest["symbol"],
                details={
                    "symbol": latest["symbol"],
                    "amount": latest["amount"],
                    "mean": round(avg, 2),
                    "stddev": round(std, 2),
                    "z_score": round(z_score, 2),
                    "threshold": self.unusual_size_multiplier,
                },
            ))

        self._alerts.extend(alerts)
        return alerts

    def check_concentration(self) -> list[CapitalIncidentAlert]:
        """Detect excessive concentration in a single asset."""
        alerts = []
        if not self._trade_history:
            return alerts

        # Calculate per-symbol total
        symbol_totals: dict[str, float] = {}
        grand_total = 0.0
        for t in self._trade_history:
            symbol_totals[t["symbol"]] = symbol_totals.get(t["symbol"], 0.0) + t["amount"]
            grand_total += t["amount"]

        if grand_total == 0:
            return alerts

        for symbol, total in symbol_totals.items():
            pct = total / grand_total
            if pct > self.max_concentration_pct:
                alerts.append(CapitalIncidentAlert(
                    alert_id=self._next_alert_id(),
                    severity="critical",
                    pattern="concentration",
                    message=f"Activity in {symbol} is {pct:.1%} of total "
                            f"(threshold: {self.max_concentration_pct:.0%})",
                    scope=symbol,
                    details={
                        "symbol": symbol,
                        "concentration_pct": round(pct, 4),
                        "threshold": self.max_concentration_pct,
                        "total_amount": total,
                        "grand_total": grand_total,
                    },
                ))

        self._alerts.extend(alerts)
        return alerts

    def check_all(self) -> list[CapitalIncidentAlert]:
        """Run all incident protection checks."""
        alerts = []
        alerts.extend(self.check_rapid_position_change())
        alerts.extend(self.check_unusual_order_size())
        alerts.extend(self.check_concentration())
        return alerts

    def get_alerts(self, severity: Optional[str] = None,
                   pattern: Optional[str] = None) -> list[CapitalIncidentAlert]:
        """Get alerts, optionally filtered."""
        results = list(self._alerts)
        if severity:
            results = [a for a in results if a.severity == severity]
        if pattern:
            results = [a for a in results if a.pattern == pattern]
        return results

    def clear_alerts(self):
        """Clear all alerts."""
        self._alerts.clear()
        self._alert_counter = 0

    def clear_history(self):
        """Clear all trade history and position changes."""
        self._trade_history.clear()
        self._position_changes.clear()
        self.clear_alerts()


# ===========================================================================
# Capital Boundary Enforcer — 资金安全边界执行器
# ===========================================================================

class CapitalBoundaryEnforcer:
    """Integrated enforcer for capital safety boundaries.

    Combines CapitalAllocation, CapitalAuthority, CapitalSafetyMonitor,
    and CapitalIncidentProtection into a single enforcement interface
    that integrates with the pipeline's existing BoundaryEnforcer.

    This is the primary entry point for V4.8 capital safety checks.

    Usage:
        enforcer = CapitalBoundaryEnforcer()
        result = enforcer.check_all(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=50_000,
        )
        if not result.get("allowed", True):
            print(f"Blocked: {result.get('blocked_by')}: {result.get('reason')}")

    Integration with BoundaryEnforcer:
        boundary_enforcer = BoundaryEnforcer()
        boundary_enforcer.load_policy(build_capital_safety_policy())
        capital_enforcer = CapitalBoundaryEnforcer()
        # Use capital_enforcer.check_all() alongside boundary_enforcer.check_action()
    """

    def __init__(self,
                 allocation: Optional[CapitalAllocation] = None,
                 authority: Optional[CapitalAuthority] = None,
                 monitor: Optional[CapitalSafetyMonitor] = None,
                 incident_protection: Optional[CapitalIncidentProtection] = None):
        self.allocation = allocation or CapitalAllocation()
        self.authority = authority or CapitalAuthority()
        self.monitor = monitor or CapitalSafetyMonitor(allocation=self.allocation)
        self.incident_protection = incident_protection or CapitalIncidentProtection()
        self._check_history: list = []
        self._blocked_actions: list = []
        self._enabled: bool = True

    # -- Master check ---------------------------------------------------

    def check_all(self,
                  tier: AuthorityTier,
                  action: CapitalActionType,
                  scope: str,
                  amount: float = 0.0,
                  symbol: str = "",
                  context: dict = None) -> dict:
        """Run all capital safety checks for a proposed action.

        Checks are performed in order:
          1. Is the enforcer enabled?
          2. Does the actor have authority for this action?
          3. Does the allocation fit within limits?
          4. Is the order within single-order limits?
          5. Are there any abnormal patterns?

        Args:
            tier: Actor's authority tier
            action: The action being requested
            scope: Allocation scope (e.g., "strategy:mean_reversion", "asset:000001.SZ")
            amount: Capital amount involved
            symbol: Asset symbol (for incident protection)
            context: Optional context dict

        Returns:
            dict with:
              - allowed: bool — overall decision
              - blocked: bool — was it blocked?
              - blocked_by: str — which check blocked it
              - reason: str — explanation
              - checks: list of individual check results
              - alerts: list of triggered alerts
        """
        context = context or {}
        checks = []
        alerts = []

        # 1. Enabler check
        if not self._enabled:
            record = {
                "check": "enabled",
                "allowed": False,
                "blocked": True,
                "reason": "CapitalBoundaryEnforcer is disabled",
            }
            checks.append(record)
            self._record_blocked("enabled", "CapitalBoundaryEnforcer is disabled")
            return self._build_result(False, "enabled", "Enforcer is disabled", checks, alerts)

        checks.append({"check": "enabled", "allowed": True})

        # 2. Authority check
        auth_result = self.authority.check_permission(tier, action, amount, context)
        checks.append({
            "check": "authority",
            "allowed": auth_result.allowed,
            "blocked": auth_result.blocked,
            "reason": auth_result.reason,
            "tier": auth_result.tier,
            "requires": auth_result.requires_higher_tier,
        })
        if auth_result.blocked:
            self._record_blocked("authority", auth_result.reason)
            return self._build_result(False, "authority", auth_result.reason, checks, alerts)

        # 3. Allocation check
        alloc_result = self.allocation.check_allocation(scope, amount)
        checks.append({
            "check": "allocation",
            "allowed": alloc_result.allowed,
            "blocked": alloc_result.blocked,
            "reason": alloc_result.reason,
            "scope": alloc_result.scope,
            "requested": alloc_result.requested_amount,
            "limit": alloc_result.limit_amount,
            "current_usage": alloc_result.current_usage,
        })
        if alloc_result.blocked:
            self._record_blocked("allocation", alloc_result.reason)
            return self._build_result(False, "allocation", alloc_result.reason, checks, alerts)

        # 4. Order-level check (if amount > 0)
        if amount > 0:
            order_result = self.allocation.check_order(amount)
            checks.append({
                "check": "order_limit",
                "allowed": order_result.allowed,
                "blocked": order_result.blocked,
                "reason": order_result.reason,
                "requested": order_result.requested_amount,
            })
            if order_result.blocked:
                self._record_blocked("order_limit", order_result.reason)
                return self._build_result(False, "order_limit", order_result.reason, checks, alerts)

        # 5. Incident protection (if symbol is provided)
        if symbol:
            inc_alerts = self.incident_protection.check_all()
            for inc in inc_alerts:
                alerts.append(inc.to_dict())
                if inc.severity in ("critical", "blocker"):
                    checks.append({
                        "check": "incident_protection",
                        "allowed": False,
                        "blocked": True,
                        "reason": f"Incident: {inc.message}",
                        "pattern": inc.pattern,
                    })
                    self._record_blocked("incident_protection", inc.message)
                    return self._build_result(False, "incident_protection",
                                              inc.message, checks, alerts)
            checks.append({"check": "incident_protection", "allowed": True})

        # 6. Monitor check (non-blocking, generates alerts)
        monitor_alerts = self.monitor.check_all()
        for ma in monitor_alerts:
            alerts.append(ma.to_dict())

        # All checks passed
        result = self._build_result(True, "", "All capital safety checks passed", checks, alerts)
        self._check_history.append(result)
        return result

    # -- Usage recording ------------------------------------------------

    def record_trade(self, symbol: str, amount: float,
                     side: str = "buy", scope: str = ""):
        """Record a successfully checked trade for tracking."""
        self.allocation.record_usage(scope, amount)
        self.allocation.record_daily_trade(amount)
        if symbol:
            self.incident_protection.record_trade(symbol, amount, side)

    # -- State management -----------------------------------------------

    def enable(self):
        """Enable the capital boundary enforcer."""
        self._enabled = True

    def disable(self, reason: str = "manual override"):
        """Disable the enforcer (audited action, requires super admin)."""
        self._enabled = False
        self._check_history.append({
            "action": "disabled",
            "reason": reason,
            "timestamp": datetime.now(CST).isoformat(),
        })

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def reset(self):
        """Reset all state (usage tracking, alerts, history)."""
        self.allocation.reset_usage()
        self.incident_protection.clear_history()
        self.authority.clear_audit_log()
        self.monitor.clear_alerts()
        self._check_history.clear()
        self._blocked_actions.clear()

    # -- Reporting ------------------------------------------------------

    def get_report(self) -> dict:
        """Generate a comprehensive capital safety report."""
        snapshot = self.monitor.snapshot()
        return {
            "version": "V4.8",
            "enabled": self._enabled,
            "timestamp": datetime.now(CST).isoformat(),
            "capital_usage": snapshot.to_dict(),
            "alerts": [a.to_dict() for a in self.incident_protection.get_alerts()],
            "monitor_alerts": [a.to_dict()
                               for a in self.monitor.get_alerts()],
            "n_checks": len(self._check_history),
            "n_blocked": len(self._blocked_actions),
            "recent_blocked": self._blocked_actions[-10:] if self._blocked_actions else [],
            "authority_audit": self.authority.get_audit_log()[-20:],
        }

    # -- Internal helpers -----------------------------------------------

    def _record_blocked(self, check: str, reason: str):
        """Record a blocked action."""
        record = {
            "blocked_by": check,
            "reason": reason,
            "timestamp": datetime.now(CST).isoformat(),
        }
        self._blocked_actions.append(record)
        self._check_history.append(record)

    def _build_result(self, allowed: bool, blocked_by: str,
                      reason: str, checks: list,
                      alerts: list) -> dict:
        return {
            "allowed": allowed,
            "blocked": not allowed,
            "blocked_by": blocked_by,
            "reason": reason,
            "checks": checks,
            "alerts": alerts,
            "timestamp": datetime.now(CST).isoformat(),
        }


# ===========================================================================
# Convenience — Build capital safety risk boundaries for BoundaryEnforcer
# ===========================================================================

def build_capital_safety_boundaries() -> list[RiskBoundary]:
    """Build risk boundaries that can be added to the pipeline's BoundaryEnforcer.

    These boundaries extend the V4.0 base policy with V4.8 capital safety rules.
    """
    return [
        RiskBoundary(
            name="capital_allocation_limit",
            severity="blocker",
            description="资本分配上限 — 策略/资产/总量不得超过配置上限",
            policy="All capital allocations must be within configured limits. "
                   "Per-strategy, per-asset, and total portfolio limits apply.",
            enforced=True,
            auto_blocked_methods=["allocate_capital", "modify_capital_allocation"],
            requires_human=True,
        ),
        RiskBoundary(
            name="capital_authority_tier",
            severity="blocker",
            description="资本操作权限 — 操作必须匹配权限层级",
            policy="Every capital operation requires appropriate authority tier. "
                   "Amount-based thresholds may require higher-tier approval.",
            enforced=True,
            auto_blocked_methods=["execute_capital_action", "override_limit"],
            requires_human=True,
        ),
        RiskBoundary(
            name="capital_exposure_limit",
            severity="warning",
            description="资本暴露上限 — 总暴露不得超过安全阈值",
            policy="Total capital exposure must not exceed configured percentage "
                   "of total capital. Free capital reserve must be maintained.",
            enforced=True,
            auto_blocked_methods=["increase_exposure"],
            requires_human=False,
        ),
        RiskBoundary(
            name="capital_incident_protection",
            severity="warning",
            description="异常资本流动保护 — 检测异常交易模式",
            policy="Abnormal capital flow patterns (rapid position changes, "
                   "unusual order sizes, concentration) trigger alerts and "
                   "may block further activity.",
            enforced=True,
            auto_blocked_methods=[],
            requires_human=False,
        ),
        RiskBoundary(
            name="daily_trade_limits",
            severity="warning",
            description="日内交易限额 — 订单数量和总金额限制",
            policy="Daily trade count and total trade capital must stay "
                   "within configured limits.",
            enforced=True,
            auto_blocked_methods=[],
            requires_human=False,
        ),
    ]


def build_capital_safety_policy(name: str = "V4.8 Capital Safety Policy",
                                 version: str = "V4.8") -> RiskPolicy:
    """Build a complete RiskPolicy with V4.8 capital safety boundaries.

    This policy can be loaded into a BoundaryEnforcer alongside the
    V4.0 base policy for comprehensive pipeline enforcement.
    """
    policy = RiskPolicy(name=name, version=version)
    for boundary in build_capital_safety_boundaries():
        policy.add_boundary(boundary)
    return policy
