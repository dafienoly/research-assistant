"""V4.6 Trade Filter & Slippage Control — Slippage Control Engine

Advanced slippage management built on top of the V4.1 FillEngine
slippage models. Adds pre-execution estimation, budget tracking,
and limit enforcement.

Core capabilities:
  1. SlippageBudget        — Per-order and per-day slippage budget tracking
  2. SlippageEstimator     — Pre-execution slippage estimation with adjustable confidence
  3. SlippageLimit         — Slippage threshold with configurable action on breach
  4. SlippageController    — Unified controller tying estimation + budget + limits

Design:
  - Slippage estimation occurs BEFORE the FillEngine processes a trade
  - If estimated slippage exceeds budget, the trade can be rejected or resized
  - Budgets are tracked per-order and reset daily
  - Integrates with TradeFilterEngine as a pre-filter step
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone, timedelta
from enum import Enum
from typing import Optional

from factor_lab.execution.shadow_fill import (
    FillEngine, SlippageConfig, SlippageModel, MarketDataSnapshot,
)

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SlippageLimitAction(Enum):
    """Action to take when slippage exceeds a limit."""
    WARN = "warn"            # Allow trade, log warning
    REJECT = "reject"        # Reject the trade
    RESIZE = "resize"        # Reduce order size to fit budget
    ADAPT = "adapt"          # Switch to more conservative slippage model


class BudgetPeriod(Enum):
    """Period over which a slippage budget is tracked."""
    PER_ORDER = "per_order"
    DAILY = "daily"
    WEEKLY = "weekly"


# ---------------------------------------------------------------------------
# Slippage Budget
# ---------------------------------------------------------------------------
@dataclass
class SlippageBudget:
    """Configuration for slippage budget limits.

    Can track slippage cost in both absolute (yuan) and relative
    (percentage of trade value) terms.
    """
    max_slippage_yuan: float = 0.0        # 0 = unlimited
    max_slippage_pct: float = 0.005       # 0.5% max slippage of trade value
    max_daily_slippage_yuan: float = 0.0  # 0 = unlimited
    max_daily_slippage_pct: float = 0.0   # 0 = unlimited
    action_on_exceed: str = SlippageLimitAction.WARN.value
    period: str = BudgetPeriod.PER_ORDER.value

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SlippageBudgetState:
    """Current state of slippage budget tracking."""
    order_slippage_yuan: float = 0.0
    order_slippage_pct: float = 0.0
    order_trade_value: float = 0.0
    daily_slippage_yuan: float = 0.0
    daily_slippage_pct: float = 0.0
    daily_total_trade_value: float = 0.0
    daily_trade_count: int = 0
    budget_exceeded: bool = False
    exceed_reason: str = ""
    tracking_date: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SlippageBudgetTracker:
    """Tracks slippage consumption against configured budgets.

    Usage:
        tracker = SlippageBudgetTracker(budget=SlippageBudget(...))
        result = tracker.check_order(order_value, estimated_slippage_pct)
        if result["allowed"]:
            # Proceed with trade
            tracker.record_fill(fill_value, actual_slippage)
    """

    def __init__(self, budget: Optional[SlippageBudget] = None,
                 name: str = "default"):
        self.budget = budget or SlippageBudget()
        self.name = name
        self._daily_state = SlippageBudgetState(
            tracking_date=datetime.now(CST).strftime("%Y-%m-%d"),
        )
        self._order_budgets: dict[str, SlippageBudgetState] = {}
        self._check_history: list[dict] = []

    def _ensure_daily_reset(self):
        """Reset daily tracking if a new trading day has started."""
        today = datetime.now(CST).strftime("%Y-%m-%d")
        if self._daily_state.tracking_date != today:
            self._daily_state = SlippageBudgetState(tracking_date=today)

    def check_order(self, order_id: str, trade_value: float,
                    estimated_slippage_pct: float) -> dict:
        """Check if an order fits within the slippage budget.

        Args:
            order_id: Unique identifier for this order
            trade_value: Expected trade value (price * quantity)
            estimated_slippage_pct: Estimated slippage as a percentage

        Returns:
            dict with:
              - allowed: bool
              - reason: str
              - state: SlippageBudgetState dict
        """
        self._ensure_daily_reset()
        estimated_slippage_yuan = trade_value * estimated_slippage_pct

        # Check per-order limits
        if self.budget.max_slippage_yuan > 0:
            if estimated_slippage_yuan > self.budget.max_slippage_yuan:
                return self._budget_exceeded(
                    order_id,
                    f"Order slippage ¥{estimated_slippage_yuan:.2f} "
                    f"> max ¥{self.budget.max_slippage_yuan:.2f}",
                    estimated_slippage_yuan, estimated_slippage_pct,
                    trade_value,
                )

        if self.budget.max_slippage_pct > 0:
            if estimated_slippage_pct > self.budget.max_slippage_pct:
                return self._budget_exceeded(
                    order_id,
                    f"Order slippage {estimated_slippage_pct:.4%} "
                    f"> max {self.budget.max_slippage_pct:.4%}",
                    estimated_slippage_yuan, estimated_slippage_pct,
                    trade_value,
                )

        # Check daily limits
        projected_daily_yuan = (self._daily_state.daily_slippage_yuan
                                + estimated_slippage_yuan)
        projected_total_value = (self._daily_state.daily_total_trade_value
                                 + trade_value)
        projected_daily_pct = (
            estimated_slippage_pct
            if self._daily_state.daily_total_trade_value <= 0
            else projected_daily_yuan / projected_total_value
        )

        if self.budget.max_daily_slippage_yuan > 0:
            if projected_daily_yuan > self.budget.max_daily_slippage_yuan:
                return self._budget_exceeded(
                    order_id,
                    f"Daily slippage ¥{projected_daily_yuan:.2f} "
                    f"> daily max ¥{self.budget.max_daily_slippage_yuan:.2f}",
                    estimated_slippage_yuan, estimated_slippage_pct,
                    trade_value,
                )

        if self.budget.max_daily_slippage_pct > 0:
            if projected_daily_pct > self.budget.max_daily_slippage_pct:
                return self._budget_exceeded(
                    order_id,
                    f"Daily slippage {projected_daily_pct:.4%} "
                    f"> daily max {self.budget.max_daily_slippage_pct:.4%}",
                    estimated_slippage_yuan, estimated_slippage_pct,
                    trade_value,
                )

        # Budget OK
        return self._budget_ok(order_id, estimated_slippage_yuan,
                               estimated_slippage_pct, trade_value)

    def record_fill(self, order_id: str, fill_value: float,
                    actual_slippage_yuan: float):
        """Record an actual fill after execution.

        Updates daily tracking state.
        """
        self._ensure_daily_reset()
        self._daily_state.daily_slippage_yuan += actual_slippage_yuan
        self._daily_state.daily_total_trade_value += fill_value
        self._daily_state.daily_trade_count += 1

        if self._daily_state.daily_total_trade_value > 0:
            self._daily_state.daily_slippage_pct = (
                self._daily_state.daily_slippage_yuan
                / self._daily_state.daily_total_trade_value
            )

        # Record in order-specific state
        if order_id in self._order_budgets:
            state = self._order_budgets[order_id]
            state.order_slippage_yuan = actual_slippage_yuan
            state.order_trade_value = fill_value
            if fill_value > 0:
                state.order_slippage_pct = actual_slippage_yuan / fill_value

    def _budget_exceeded(self, order_id: str, reason: str,
                          slippage_yuan: float, slippage_pct: float,
                          trade_value: float) -> dict:
        """Handle budget exceeded."""
        result = {
            "allowed": False,
            "action": self.budget.action_on_exceed,
            "reason": reason,
            "order_id": order_id,
            "estimated_slippage_yuan": round(slippage_yuan, 4),
            "estimated_slippage_pct": round(slippage_pct, 6),
            "trade_value": round(trade_value, 2),
            "state": self._daily_state.to_dict(),
        }
        self._check_history.append(result)
        return result

    def _budget_ok(self, order_id: str, slippage_yuan: float,
                    slippage_pct: float, trade_value: float) -> dict:
        """Handle budget OK."""
        # Store estimated budget for this order
        self._order_budgets[order_id] = SlippageBudgetState(
            order_slippage_yuan=slippage_yuan,
            order_slippage_pct=slippage_pct,
            order_trade_value=trade_value,
        )

        result = {
            "allowed": True,
            "action": "proceed",
            "reason": "Within budget",
            "order_id": order_id,
            "estimated_slippage_yuan": round(slippage_yuan, 4),
            "estimated_slippage_pct": round(slippage_pct, 6),
            "trade_value": round(trade_value, 2),
            "state": self._daily_state.to_dict(),
        }
        self._check_history.append(result)
        return result

    def get_daily_state(self) -> dict:
        """Get current daily tracking state."""
        self._ensure_daily_reset()
        return self._daily_state.to_dict()

    def get_summary(self) -> dict:
        """Get tracker activity summary."""
        total_checks = len(self._check_history)
        allowed = sum(1 for c in self._check_history if c.get("allowed"))
        blocked = total_checks - allowed
        return {
            "name": self.name,
            "budget": self.budget.to_dict(),
            "daily_state": self.get_daily_state(),
            "total_checks": total_checks,
            "n_allowed": allowed,
            "n_blocked": blocked,
        }

    def reset_daily(self):
        """Reset daily tracking (e.g., at start of new trading day)."""
        self._daily_state = SlippageBudgetState(
            tracking_date=datetime.now(CST).strftime("%Y-%m-%d"),
        )

    def reset(self):
        """Reset all tracking state."""
        self._daily_state = SlippageBudgetState(
            tracking_date=datetime.now(CST).strftime("%Y-%m-%d"),
        )
        self._order_budgets.clear()
        self._check_history.clear()


# ---------------------------------------------------------------------------
# Slippage Estimate
# ---------------------------------------------------------------------------
@dataclass
class SlippageEstimate:
    """Result of a pre-execution slippage estimation."""
    estimated_slippage_pct: float = 0.0
    estimated_slippage_yuan: float = 0.0
    model_used: str = SlippageModel.FIXED_PCT.value
    confidence: str = "medium"   # "low" | "medium" | "high"
    estimate_range: tuple = (0.0, 0.0)  # (min, max) estimate
    data_quality: str = "good"   # "good" | "partial" | "poor"
    warnings: list = field(default_factory=list)

    def is_reliable(self) -> bool:
        return self.confidence in ("medium", "high")

    def to_dict(self) -> dict:
        return {
            "estimated_slippage_pct": self.estimated_slippage_pct,
            "estimated_slippage_yuan": self.estimated_slippage_yuan,
            "model_used": self.model_used,
            "confidence": self.confidence,
            "estimate_range": list(self.estimate_range),
            "data_quality": self.data_quality,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Slippage Estimator
# ---------------------------------------------------------------------------
class SlippageEstimator:
    """Pre-execution slippage estimator.

    Estimates slippage before an order is submitted, using the same
    models as FillEngine but without executing the trade.

    Usage:
        estimator = SlippageEstimator()
        estimate = estimator.estimate("buy", 1000, 10.0, market_data)
        print(f"Estimated slippage: {estimate.estimated_slippage_pct:.4%}")
    """

    def __init__(self, slippage_config: Optional[SlippageConfig] = None,
                 confidence_multiplier: float = 1.0):
        """Initialize the estimator.

        Args:
            slippage_config: SlippageConfig (same as FillEngine configs)
            confidence_multiplier: Multiply estimate for safety margin.
                                   Higher = more conservative.
        """
        self.slippage_config = slippage_config or SlippageConfig()
        self.confidence_multiplier = confidence_multiplier
        self._fill_engine = FillEngine(
            slippage_config=self.slippage_config
        )
        self._estimate_history: list[dict] = []

    def estimate(self, side: str, quantity: int, price: float,
                 market: Optional[MarketDataSnapshot] = None,
                 model: str = "") -> SlippageEstimate:
        """Estimate slippage for a proposed trade.

        Args:
            side: "buy" or "sell"
            quantity: Number of shares
            price: Reference price
            market: Market data snapshot (optional)
            model: Slippage model override (optional)

        Returns:
            SlippageEstimate with estimated costs and confidence
        """
        model = model or self.slippage_config.model
        warnings = []

        # 1. Get raw slippage estimate from FillEngine
        slippage_per_share, model_used, meta = self._fill_engine.compute_slippage(
            order_price=price,
            shares=quantity,
            market=market,
            model=model,
        )

        # 2. Apply confidence multiplier
        slippage_per_share *= self.confidence_multiplier

        # 3. Compute total slippage
        total_slippage_yuan = slippage_per_share * quantity
        total_trade_value = price * quantity
        slippage_pct = (total_slippage_yuan / total_trade_value
                        if total_trade_value > 0 else 0.0)

        # 4. Determine confidence and estimate range
        confidence, data_quality, range_width = self._assess_quality(
            model, market, meta
        )

        min_est = round(slippage_per_share * (1 - range_width), 4)
        max_est = round(slippage_per_share * (1 + range_width), 4)

        # 5. Build warnings
        if data_quality == "poor":
            warnings.append("Limited market data — estimate may be inaccurate")
        if meta.get("fallback"):
            warnings.append(f"Using fallback model: {meta['fallback']}")

        estimate = SlippageEstimate(
            estimated_slippage_pct=round(slippage_pct, 6),
            estimated_slippage_yuan=round(total_slippage_yuan, 4),
            model_used=model_used,
            confidence=confidence,
            estimate_range=(min_est * quantity, max_est * quantity),
            data_quality=data_quality,
            warnings=warnings,
        )
        self._estimate_history.append(estimate.to_dict())
        return estimate

    def estimate_for_budget(self, side: str, quantity: int, price: float,
                             market: Optional[MarketDataSnapshot] = None,
                             model: str = "") -> float:
        """Quick estimate returning just the slippage percentage.

        Convenience method for integration with SlippageBudgetTracker.
        """
        est = self.estimate(side, quantity, price, market, model)
        return est.estimated_slippage_pct

    def _assess_quality(self, model: str,
                        market: Optional[MarketDataSnapshot],
                        meta: dict) -> tuple:
        """Assess estimate quality based on data availability.

        Returns:
            (confidence: str, data_quality: str, range_width: float)
        """
        if market is None:
            return "low", "poor", 0.5

        if market.status == "missing":
            return "low", "poor", 0.5

        has_volume = market.avg_volume_20d > 0
        has_volatility = market.volatility_20d > 0

        if model == SlippageModel.FIXED_PCT.value:
            return "high", "good", 0.1

        if model == SlippageModel.VOLUME_BASED.value:
            if has_volume:
                return "high", "good", 0.15
            return "low", "poor", 0.3

        if model == SlippageModel.VOLATILITY_BASED.value:
            if has_volatility:
                return "high", "good", 0.15
            return "low", "poor", 0.3

        if model == SlippageModel.HYBRID.value:
            if has_volume and has_volatility:
                return "high", "good", 0.2
            if has_volume or has_volatility:
                return "medium", "partial", 0.3
            return "low", "poor", 0.4

        return "medium", "partial", 0.25

    def get_summary(self) -> dict:
        """Get estimator activity summary."""
        n_estimates = len(self._estimate_history)
        return {
            "model": self.slippage_config.model,
            "confidence_multiplier": self.confidence_multiplier,
            "n_estimates": n_estimates,
        }

    def reset(self):
        """Reset estimate history."""
        self._estimate_history.clear()


# ---------------------------------------------------------------------------
# Slippage Controller (unified interface)
# ---------------------------------------------------------------------------
class SlippageController:
    """Unified slippage control interface.

    Combines slippage estimation, budget tracking, and limit enforcement
    into a single controller that can be plugged into the pipeline.

    Usage:
        controller = SlippageController()
        result = controller.check_trade("buy", 1000, 10.0, market_data)
        if result["allowed"]:
            controller.record_fill(order_id, fill_value, actual_slippage)
    """

    def __init__(self,
                 slippage_config: Optional[SlippageConfig] = None,
                 budget: Optional[SlippageBudget] = None,
                 confidence_multiplier: float = 1.0,
                 name: str = "default"):
        self.name = name
        self.config = slippage_config or SlippageConfig()
        self.estimator = SlippageEstimator(
            slippage_config=self.config,
            confidence_multiplier=confidence_multiplier,
        )
        self.budget_tracker = SlippageBudgetTracker(
            budget=budget or SlippageBudget(),
            name=f"{name}_budget",
        )

    def check_trade(self, order_id: str, side: str, quantity: int,
                    price: float,
                    market: Optional[MarketDataSnapshot] = None) -> dict:
        """Full pre-trade slippage check: estimate + budget check.

        Args:
            order_id: Unique order identifier
            side: "buy" or "sell"
            quantity: Number of shares
            price: Reference price
            market: Market data snapshot

        Returns:
            dict with:
              - allowed: bool
              - action: str (proceed/reject/warn/resize/adapt)
              - estimate: SlippageEstimate dict
              - budget_check: dict from SlippageBudgetTracker
              - reason: str
        """
        # Step 1: Estimate slippage
        estimate = self.estimator.estimate(side, quantity, price, market)
        trade_value = price * quantity

        # Step 2: Check budget
        budget_result = self.budget_tracker.check_order(
            order_id=order_id,
            trade_value=trade_value,
            estimated_slippage_pct=estimate.estimated_slippage_pct,
        )

        # Step 3: Determine action
        allowed = budget_result.get("allowed", True)
        action = budget_result.get("action", "proceed")

        if not allowed:
            if action == SlippageLimitAction.REJECT.value:
                return {
                    "allowed": False,
                    "action": "reject",
                    "reason": budget_result.get("reason", "Budget exceeded"),
                    "order_id": order_id,
                    "estimate": estimate.to_dict(),
                    "budget_check": budget_result,
                }
            elif action == SlippageLimitAction.WARN.value:
                # Allow but log warning
                pass

        return {
            "allowed": True,
            "action": action,
            "reason": budget_result.get("reason", "Within budget"),
            "order_id": order_id,
            "estimate": estimate.to_dict(),
            "budget_check": budget_result,
        }

    def record_fill(self, order_id: str, fill_value: float,
                    actual_slippage_yuan: float):
        """Record an actual fill for budget tracking."""
        self.budget_tracker.record_fill(order_id, fill_value,
                                        actual_slippage_yuan)

    def get_summary(self) -> dict:
        """Get controller summary."""
        return {
            "name": self.name,
            "model": self.config.model,
            "confidence_multiplier": self.estimator.confidence_multiplier,
            "estimator": self.estimator.get_summary(),
            "budget_tracker": self.budget_tracker.get_summary(),
        }

    def reset_daily(self):
        """Reset daily budget."""
        self.budget_tracker.reset_daily()

    def reset(self):
        """Reset all state."""
        self.estimator.reset()
        self.budget_tracker.reset()
