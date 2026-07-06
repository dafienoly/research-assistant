"""V4.7 Order Book & Deep Execution Route — Deep Execution Router

Intelligent execution route selection engine that determines the optimal
execution strategy for each order based on market conditions, order
characteristics, and configurable routing policies.

Core capabilities:
  1. RouteType            — Execution route strategy enum
  2. RouteResult          — Result of a route evaluation
  3. RouteConfig          — Route-specific configuration parameters
  4. RoutePerformance     — Performance tracking per route type
  5. RouteSelector        — Evaluates and selects the best route for an order
  6. DeepExecutionRouter  — Unified router combining selection + tracking

Execution routes available:
  - MARKET     : Execute immediately at market price (highest urgency)
  - LIMIT      : Execute at specified limit price or better
  - TWAP       : Time-weighted average price over a period
  - VWAP       : Volume-weighted average price, follows volume profile
  - ICEBERG    : Large order broken into smaller visible chunks
  - SMART      : Adaptive route that switches strategies based on market conditions

Design:
  - Route selection considers: order size, liquidity, urgency, volatility,
    spread, and historical fill quality.
  - Each route type has configurable parameters (e.g., slices for TWAP,
    visibility for ICEBERG).
  - Performance is tracked per route type per symbol for continuous improvement.
  - Routes never execute real trades — they only produce recommendations
    consumed by the pipeline's FillEngine or execution layer.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class RouteType(Enum):
    """Execution route strategy types."""
    MARKET = "market"         # Execute immediately at market price
    LIMIT = "limit"           # Execute at limit price or better
    TWAP = "twap"             # Time-weighted average price
    VWAP = "vwap"             # Volume-weighted average price
    ICEBERG = "iceberg"       # Large order as hidden slices
    SMART = "smart"           # Adaptive: switches based on conditions


class RouteUrgency(Enum):
    """How urgently an order needs to be executed."""
    IMMEDIATE = "immediate"    # Fill as fast as possible
    HIGH = "high"              # Fill within minutes
    NORMAL = "normal"          # Fill within the trading session
    LOW = "low"                # No urgency, seek best price


class RouteRecommendation(Enum):
    """Recommendation type from the router."""
    EXECUTE_NOW = "execute_now"         # Proceed with the selected route
    EXECUTE_LIMIT = "execute_limit"     # Proceed with limit price bound
    DEFER = "defer"                     # Wait for better conditions
    SPLIT = "split"                     # Split across multiple routes
    ESCALATE = "escalate"               # Escalate for human review


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class RouteConfig:
    """Configuration parameters for a specific execution route type.

    Each route type has its own parameter set that controls how orders
    are executed when that route is selected.
    """
    route_type: str = RouteType.MARKET.value

    # Common
    max_slippage_bps: float = 5.0         # Max acceptable slippage in bps
    time_limit_seconds: int = 0            # 0 = no time limit

    # TWAP / VWAP
    num_slices: int = 5                    # Number of slices to split into
    slice_interval_seconds: int = 60       # Seconds between slices

    # LIMIT
    limit_offset_bps: float = 0.0          # Offset from market price (pos = aggressive)
    max_wait_seconds: int = 300            # Max time to wait for limit fill

    # ICEBERG
    visible_quantity: int = 0              # Visible portion per slice (0 = auto)
    min_visible_pct: float = 5.0           # Min visible as % of total

    # SMART
    fallback_route: str = RouteType.MARKET.value   # Route if conditions shift
    volatility_threshold: float = 0.02             # Switch at this vol level
    min_urgency_for_market: str = RouteUrgency.IMMEDIATE.value

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def defaults_for(route_type: str) -> "RouteConfig":
        """Get sensible defaults for a given route type."""
        base = RouteConfig(route_type=route_type)
        if route_type == RouteType.MARKET.value:
            base.max_slippage_bps = 10.0
        elif route_type == RouteType.LIMIT.value:
            base.limit_offset_bps = -5.0
            base.max_wait_seconds = 300
        elif route_type == RouteType.TWAP.value:
            base.num_slices = 10
            base.slice_interval_seconds = 30
            base.max_slippage_bps = 3.0
        elif route_type == RouteType.VWAP.value:
            base.num_slices = 20
            base.max_slippage_bps = 2.0
        elif route_type == RouteType.ICEBERG.value:
            base.visible_quantity = 0  # auto
            base.min_visible_pct = 10.0
            base.max_slippage_bps = 8.0
        elif route_type == RouteType.SMART.value:
            base.fallback_route = RouteType.LIMIT.value
            base.volatility_threshold = 0.03
        return base


@dataclass
class RouteResult:
    """Result of a route evaluation for a specific order.

    Contains the recommended route, supporting data, and the reasoning
    behind the selection.
    """
    order_id: str = ""
    symbol: str = ""
    recommended_route: str = RouteType.MARKET.value
    recommendation: str = RouteRecommendation.EXECUTE_NOW.value
    confidence: float = 0.0           # 0.0 - 1.0
    estimated_slippage_bps: float = 0.0
    estimated_fill_time_seconds: int = 0
    estimated_slices: int = 1
    score_by_route: dict = field(default_factory=dict)   # route_type -> score
    reasoning: str = ""
    warnings: list = field(default_factory=list)
    evaluated_at: str = ""

    def __post_init__(self):
        if not self.evaluated_at:
            self.evaluated_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RoutePerformance:
    """Performance metrics for a route type, tracked per symbol.

    Used by SMART route and for post-trade analysis to improve
    future route selection.
    """
    route_type: str = RouteType.MARKET.value
    symbol: str = ""

    # Execution quality
    total_orders: int = 0
    successful_orders: int = 0
    failed_orders: int = 0
    avg_slippage_bps: float = 0.0
    avg_fill_time_seconds: float = 0.0
    avg_fill_pct: float = 0.0          # Average fill rate (filled/qty)

    # Running totals for incremental updates
    _total_slippage_bps: float = 0.0
    _total_fill_time: float = 0.0
    _total_fill_pct: float = 0.0

    def record_execution(self, slippage_bps: float = 0.0,
                         fill_time_seconds: float = 0.0,
                         fill_pct: float = 1.0,
                         success: bool = True):
        """Record a single execution result for this route/symbol."""
        self.total_orders += 1
        if success:
            self.successful_orders += 1
        else:
            self.failed_orders += 1

        self._total_slippage_bps += slippage_bps
        self._total_fill_time += fill_time_seconds
        self._total_fill_pct += fill_pct

        if self.total_orders > 0:
            self.avg_slippage_bps = round(self._total_slippage_bps / self.total_orders, 4)
            self.avg_fill_time_seconds = round(self._total_fill_time / self.total_orders, 2)
            self.avg_fill_pct = round(self._total_fill_pct / self.total_orders, 4)

    def merge(self, other: "RoutePerformance") -> "RoutePerformance":
        """Merge another performance record into this one."""
        combined = RoutePerformance(
            route_type=self.route_type,
            symbol=self.symbol or other.symbol,
            total_orders=self.total_orders + other.total_orders,
            successful_orders=self.successful_orders + other.successful_orders,
            failed_orders=self.failed_orders + other.failed_orders,
        )
        combined._total_slippage_bps = self._total_slippage_bps + other._total_slippage_bps
        combined._total_fill_time = self._total_fill_time + other._total_fill_time
        combined._total_fill_pct = self._total_fill_pct + other._total_fill_pct
        if combined.total_orders > 0:
            combined.avg_slippage_bps = round(combined._total_slippage_bps / combined.total_orders, 4)
            combined.avg_fill_time_seconds = round(combined._total_fill_time / combined.total_orders, 2)
            combined.avg_fill_pct = round(combined._total_fill_pct / combined.total_orders, 4)
        return combined

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in list(d.keys()):
            if k.startswith("_"):
                d.pop(k)
        return d


# ---------------------------------------------------------------------------
# Route Selector
# ---------------------------------------------------------------------------
class RouteSelector:
    """Evaluates and selects the best execution route for an order.

    The selector scores each available route based on:
      - Order characteristics (size, side, urgency)
      - Market conditions (spread, volatility, liquidity)
      - Historical performance of each route for the symbol
      - Configuration parameters

    Usage:
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="000001.SZ",
            quantity=10000,
            side="buy",
            urgency="normal",
            spread=0.05,
            bid_size=50000,
            ask_size=45000,
        )
        result.recommended_route  # e.g., "vwap"
    """

    def __init__(self, configs: dict = None):
        # route_type -> RouteConfig
        self.configs: dict[str, RouteConfig] = {}
        for rt in RouteType:
            key = rt.value
            self.configs[key] = configs.get(key, RouteConfig.defaults_for(key)) if configs else RouteConfig.defaults_for(key)

        # (route_type, symbol) -> RoutePerformance
        self.performance: dict[tuple[str, str], RoutePerformance] = {}

    def set_config(self, route_type: str, config: RouteConfig):
        """Override configuration for a route type."""
        self.configs[route_type] = config

    def get_config(self, route_type: str) -> Optional[RouteConfig]:
        return self.configs.get(route_type)

    def record_performance(self, route_type: str, symbol: str,
                           slippage_bps: float = 0.0,
                           fill_time_seconds: float = 0.0,
                           fill_pct: float = 1.0,
                           success: bool = True):
        """Record an execution result to improve future routing."""
        key = (route_type, symbol)
        if key not in self.performance:
            self.performance[key] = RoutePerformance(route_type=route_type, symbol=symbol)
        self.performance[key].record_execution(
            slippage_bps=slippage_bps,
            fill_time_seconds=fill_time_seconds,
            fill_pct=fill_pct,
            success=success,
        )

    def get_performance(self, route_type: str, symbol: str) -> Optional[RoutePerformance]:
        return self.performance.get((route_type, symbol))

    def evaluate(self, symbol: str,
                 quantity: int,
                 side: str = "buy",
                 urgency: str = "normal",
                 spread: float = 0.0,
                 volatility: float = 0.0,
                 bid_size: int = 0,
                 ask_size: int = 0,
                 avg_daily_volume: int = 0,
                 price: float = 0.0) -> RouteResult:
        """Evaluate all routes and select the best one for this order.

        Args:
            symbol: Stock symbol
            quantity: Order quantity
            side: 'buy' or 'sell'
            urgency: RouteUrgency value
            spread: Current bid-ask spread (in price units)
            volatility: Current volatility estimate (e.g., 0.02 = 2%)
            bid_size: Total bid size at top levels
            ask_size: Total ask size at top levels
            avg_daily_volume: Average daily trading volume
            price: Current market price

        Returns:
            RouteResult with recommended route and scores
        """
        urgency_enum = self._resolve_urgency(urgency)
        order_value = quantity * price
        liquidity = max(bid_size + ask_size, 1)
        pct_of_liquidity = quantity / liquidity if liquidity > 0 else 1.0
        pct_of_adv = quantity / avg_daily_volume if avg_daily_volume > 0 else 0.0

        # Score each route
        scores = {}
        for route_type in RouteType:
            rt = route_type.value
            score = self._score_route(
                rt, urgency_enum, quantity, order_value, spread,
                volatility, pct_of_liquidity, pct_of_adv,
            )
            scores[rt] = score

        # Pick the highest-scoring route
        best_route = max(scores, key=scores.get)
        best_score = scores[best_route]

        # Estimate slippage and fill time based on route
        est_slippage = self._estimate_slippage(best_route, spread, volatility, quantity)
        est_fill_time = self._estimate_fill_time(best_route, urgency_enum, quantity, pct_of_liquidity)
        est_slices = self._estimate_slices(best_route, quantity, pct_of_adv)

        # Generate warnings and recommendation
        warnings = []
        rec = RouteRecommendation.EXECUTE_NOW

        if urgency_enum == RouteUrgency.IMMEDIATE and spread > 0 and spread / price > 0.01 if price > 0 else False:
            warnings.append(f"Wide spread ({spread:.4f}) for immediate execution")

        if pct_of_adv > 0.1:
            warnings.append(f"Order is {pct_of_adv*100:.1f}% of ADV — consider splitting")
            if best_route in (RouteType.MARKET.value, RouteType.LIMIT.value):
                rec = RouteRecommendation.SPLIT

        if urgency_enum == RouteUrgency.LOW and best_route == RouteType.MARKET.value:
            warnings.append("Low urgency but MARKET route selected — consider LIMIT")
            rec = RouteRecommendation.DEFER

        if volatility > 0.05:
            warnings.append(f"High volatility ({volatility*100:.1f}%) — using {best_route} route")

        return RouteResult(
            order_id="",
            symbol=symbol,
            recommended_route=best_route,
            recommendation=rec.value,
            confidence=round(best_score / 100.0, 4),
            estimated_slippage_bps=est_slippage,
            estimated_fill_time_seconds=est_fill_time,
            estimated_slices=est_slices,
            score_by_route=scores,
            reasoning=self._build_reasoning(best_route, best_score, rec, warnings, urgency_enum),
            warnings=warnings,
        )

    def _score_route(self, route_type: str, urgency: RouteUrgency,
                     quantity: int, order_value: float, spread: float,
                     volatility: float, pct_of_liquidity: float,
                     pct_of_adv: float) -> float:
        """Score a single route type (higher = better)."""
        config = self.configs.get(route_type, RouteConfig.defaults_for(route_type))

        # Base score starts at 60
        score = 60.0

        if route_type == RouteType.MARKET.value:
            # Market: good for urgent orders, bad for large orders
            if urgency == RouteUrgency.IMMEDIATE:
                score += 30
            elif urgency == RouteUrgency.HIGH:
                score += 15
            elif urgency == RouteUrgency.LOW:
                score -= 20
            if pct_of_liquidity > 0.3:
                score -= 25  # Too large for market
            if spread > 0 and volatility > 0.03:
                score -= 10  # Risky in volatile wide-spread conditions

        elif route_type == RouteType.LIMIT.value:
            # Limit: good for patient orders
            if urgency == RouteUrgency.IMMEDIATE:
                score -= 30
            elif urgency == RouteUrgency.LOW:
                score += 25
            if spread > 0 and spread < 0.01:
                score += 10  # Tight spread favors limit
            if volatility > 0.04:
                score += 10  # Limit protects against adverse moves
            else:
                score += 5

        elif route_type == RouteType.TWAP.value:
            # TWAP: medium-large orders, moderate urgency
            if pct_of_adv > 0.02:
                score += 15
            if pct_of_liquidity > 0.2:
                score += 10
            if urgency == RouteUrgency.NORMAL:
                score += 15
            elif urgency == RouteUrgency.IMMEDIATE:
                score -= 15
            score += 5  # TWAP is generally safe

        elif route_type == RouteType.VWAP.value:
            # VWAP: larger orders, benchmark-aware
            if pct_of_adv > 0.03:
                score += 20
            if urgency == RouteUrgency.NORMAL:
                score += 10
            elif urgency == RouteUrgency.LOW:
                score += 15
            elif urgency == RouteUrgency.IMMEDIATE:
                score -= 20
            score += 10  # VWAP is often preferred for large orders

        elif route_type == RouteType.ICEBERG.value:
            # Iceberg: very large orders where visibility matters
            if pct_of_adv > 0.05:
                score += 25
            if quantity > 100000:
                score += 15
            if pct_of_liquidity > 0.5:
                score += 20
            if urgency == RouteUrgency.IMMEDIATE:
                score -= 10
            score -= 5  # Iceberg has complexity overhead

        elif route_type == RouteType.SMART.value:
            # SMART: adaptive, generally a safe default
            score += 10  # Adaptability bonus
            if volatility > config.volatility_threshold and config.fallback_route:
                score += 10  # Smart routing is most valuable in changing conditions
            score += 5  # General-purpose bonus

        # Historical performance bonus (up to 10 points)
        perf_key = (route_type, "")
        if perf_key in self.performance:
            perf = self.performance[perf_key]
            if perf.total_orders > 5:
                success_rate = perf.successful_orders / perf.total_orders
                score += success_rate * 10 - 5  # -5 to +5 based on success rate

        return max(0, round(score, 1))

    def _estimate_slippage(self, route_type: str, spread: float,
                           volatility: float, quantity: int) -> float:
        """Estimate expected slippage in bps."""
        base = spread * 10000 if spread > 0 else 5.0  # Convert spread to bps
        if route_type == RouteType.MARKET.value:
            return round(base * 1.5, 2)
        elif route_type == RouteType.LIMIT.value:
            return round(base * 0.3, 2)
        elif route_type in (RouteType.TWAP.value, RouteType.VWAP.value):
            return round(base * 0.6, 2)
        elif route_type == RouteType.ICEBERG.value:
            return round(base * 0.8, 2)
        elif route_type == RouteType.SMART.value:
            return round(base * 0.5, 2)
        return round(base, 2)

    def _estimate_fill_time(self, route_type: str, urgency: RouteUrgency,
                            quantity: int, pct_of_liquidity: float) -> int:
        """Estimate time to fill in seconds."""
        if urgency == RouteUrgency.IMMEDIATE:
            return 5
        if route_type == RouteType.MARKET.value:
            return 10
        elif route_type == RouteType.LIMIT.value:
            return 120
        elif route_type == RouteType.TWAP.value:
            return 300
        elif route_type == RouteType.VWAP.value:
            return 600
        elif route_type == RouteType.ICEBERG.value:
            return max(60, int(300 * pct_of_liquidity))
        elif route_type == RouteType.SMART.value:
            return 60
        return 30

    def _estimate_slices(self, route_type: str, quantity: int,
                         pct_of_adv: float) -> int:
        """Estimate how many slices this route would use."""
        if route_type == RouteType.MARKET.value:
            return 1
        elif route_type == RouteType.LIMIT.value:
            return max(1, min(5, int(quantity / 10000)))
        elif route_type == RouteType.TWAP.value:
            cfg = self.configs.get(route_type, RouteConfig.defaults_for(route_type))
            return cfg.num_slices
        elif route_type == RouteType.VWAP.value:
            cfg = self.configs.get(route_type, RouteConfig.defaults_for(route_type))
            return cfg.num_slices
        elif route_type == RouteType.ICEBERG.value:
            return max(2, int(pct_of_adv * 100))
        elif route_type == RouteType.SMART.value:
            return 3
        return 1

    def _build_reasoning(self, best_route: str, best_score: float,
                         rec: RouteRecommendation, warnings: list,
                         urgency: RouteUrgency) -> str:
        """Build human-readable reasoning for the route selection."""
        parts = [
            f"Selected {best_route} route (score={best_score})",
            f"Urgency: {urgency.value}",
        ]
        if rec != RouteRecommendation.EXECUTE_NOW:
            parts.append(f"Recommendation: {rec.value}")
        if warnings:
            parts.append("Warnings: " + "; ".join(warnings))
        return " | ".join(parts)

    @staticmethod
    def _resolve_urgency(urgency: str) -> RouteUrgency:
        if isinstance(urgency, RouteUrgency):
            return urgency
        for u in RouteUrgency:
            if u.value == urgency:
                return u
        return RouteUrgency.NORMAL

    def to_dict(self) -> dict:
        return {
            "configs": {k: v.to_dict() for k, v in self.configs.items()},
            "performance": [
                v.to_dict() for v in self.performance.values()
            ],
        }


# ---------------------------------------------------------------------------
# Deep Execution Router — Unified Router
# ---------------------------------------------------------------------------
class DeepExecutionRouter:
    """Unified execution router combining route selection, tracking,
    and integration with the Order Book.

    The DeepExecutionRouter is the top-level entry point for V4.7's
    execution routing subsystem. It:
      1. Receives orders from the pipeline
      2. Evaluates and selects the optimal route
      3. Assigns routes to orders (via Order Book)
      4. Tracks execution performance per route/symbol
      5. Provides routing reports and recommendations

    This is a planning/output component only — it never places real orders.
    """

    def __init__(self, order_book=None, selector: RouteSelector = None):
        from factor_lab.execution.order_book import OrderBook as _OB
        self.order_book = order_book or _OB()
        self.selector = selector or RouteSelector()
        self._routing_history: list[RouteResult] = []

    def route_order(self, symbol: str, quantity: int,
                    side: str = "buy",
                    urgency: str = "normal",
                    spread: float = 0.0,
                    volatility: float = 0.0,
                    bid_size: int = 0,
                    ask_size: int = 0,
                    avg_daily_volume: int = 0,
                    order_id: str = "",
                    price: float = 0.0,
                    signal_id: str = "",
                    proposal_id: str = "") -> RouteResult:
        """Evaluate and assign a route to an order.

        If an order_id is provided and exists in the book, live market
        conditions are read from the book. Otherwise, explicit parameters
        are used.

        Returns a RouteResult with the recommended route and reasoning.
        """
        # If order exists in book, use its data
        if order_id:
            book_order = self.order_book.get_order(order_id)
            if book_order:
                tob = self.order_book.get_top_of_book(book_order.symbol)
                spread = spread or tob.get("spread", 0.0)
                bid_size = bid_size or tob.get("total_bid_qty", 0)
                ask_size = ask_size or tob.get("total_ask_qty", 0)
                quantity = quantity or book_order.quantity
                side = side or book_order.side
                symbol = symbol or book_order.symbol
                price = price or tob.get("mid_price", 0.0)

        result = self.selector.evaluate(
            symbol=symbol,
            quantity=quantity,
            side=side,
            urgency=urgency,
            spread=spread,
            volatility=volatility,
            bid_size=bid_size,
            ask_size=ask_size,
            avg_daily_volume=avg_daily_volume,
            price=price,
        )

        # Attach order_id to the result
        if order_id:
            result.order_id = order_id

        # If order exists in book, assign the route
        if order_id and self.order_book.get_order(order_id):
            entry = self.order_book.get_order(order_id)
            if entry:
                entry.route = result.recommended_route
                entry.updated_at = datetime.now(CST).isoformat()

        self._routing_history.append(result)
        return result

    def record_execution_result(self, route_type: str, symbol: str,
                                 slippage_bps: float = 0.0,
                                 fill_time_seconds: float = 0.0,
                                 fill_pct: float = 1.0,
                                 success: bool = True):
        """Record an execution result to improve future routing."""
        self.selector.record_performance(
            route_type=route_type,
            symbol=symbol,
            slippage_bps=slippage_bps,
            fill_time_seconds=fill_time_seconds,
            fill_pct=fill_pct,
            success=success,
        )

    def get_routing_report(self, symbol: str = "") -> dict:
        """Generate a routing performance report."""
        if symbol:
            perf = {
                rt.value: self.selector.get_performance(rt.value, symbol)
                for rt in RouteType
            }
            perf = {k: v.to_dict() for k, v in perf.items() if v is not None}
        else:
            perf = {}
            for (rt, sym), p in self.selector.performance.items():
                if sym not in perf:
                    perf[sym] = {}
                perf[sym][rt] = p.to_dict()

        recent = [
            {
                "order_id": r.order_id,
                "symbol": r.symbol,
                "route": r.recommended_route,
                "confidence": r.confidence,
                "slippage_bps": r.estimated_slippage_bps,
                "warnings": r.warnings,
            }
            for r in self._routing_history[-50:]
        ]

        return {
            "total_routed": len(self._routing_history),
            "performance": perf,
            "recent_routes": recent,
        }

    def get_summary(self) -> dict:
        """Get a summary of the router's state."""
        return {
            "total_routed": len(self._routing_history),
            "configs": {k: v.to_dict() for k, v in self.selector.configs.items()},
            "performance_count": len(self.selector.performance),
            "book_summary": self.order_book.get_summary(),
        }

    def save(self, output_dir: str, name: str = "execution_router.json") -> str:
        """Persist router state to JSON."""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "summary": self.get_summary(),
                "routing_report": self.get_routing_report(),
            }, f, indent=2, ensure_ascii=False)
        return path
