"""V4.1 Shadow Live Pipeline — Shadow Orders & Order Manager

Manages the lifecycle of simulated orders in the shadow environment.

Order lifecycle:
  PENDING → (validate) → SUBMITTED → (match) → FILLED (or PARTIALLY_FILLED)
                                           → REJECTED
                → CANCELLED (from PENDING or SUBMITTED)

Key principles:
  - Orders never reach a real broker — sandbox only.
  - Fill simulation uses market data + slippage model.
  - Every state transition is immutable and auditable.
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
class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"             # Created but not yet submitted
    SUBMITTED = "submitted"         # Submitted to fill engine
    PARTIALLY_FILLED = "partially_filled"  # Some shares filled
    FILLED = "filled"               # Fully filled
    REJECTED = "rejected"           # Rejected by validation/engine
    CANCELLED = "cancelled"         # Cancelled before fill
    EXPIRED = "expired"             # Expired (e.g., end-of-day)


VALID_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED,
                            OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.CANCELLED,
                                   OrderStatus.EXPIRED},
    # FILLED, REJECTED, CANCELLED, EXPIRED are terminal
}


class OrderType(Enum):
    MARKET = "market"       # Execute at market price (with slippage)
    LIMIT = "limit"         # Execute at specified price or better
    TWAP = "twap"           # Time-weighted average price over period
    VWAP = "vwap"           # Volume-weighted average price


class RejectReason(Enum):
    INSUFFICIENT_CASH = "insufficient_cash"
    NO_POSITION = "no_position"
    INVALID_PRICE = "invalid_price"
    INVALID_QUANTITY = "invalid_quantity"
    ACCOUNT_FROZEN = "account_frozen"
    MARKET_CLOSED = "market_closed"
    PRICE_LIMIT = "price_limit"
    DUPLICATE_ORDER = "duplicate_order"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Order dataclass
# ---------------------------------------------------------------------------
@dataclass
class ShadowOrder:
    """A single shadow order — sandbox only, no real trading."""
    order_id: str = ""
    signal_id: str = ""             # Link back to source signal
    proposal_id: str = ""           # Link back to source proposal
    symbol: str = ""
    name: str = ""
    side: str = OrderSide.BUY.value
    order_type: str = OrderType.MARKET.value
    quantity: int = 0               # Requested quantity
    filled_quantity: int = 0        # Cumulatively filled
    remaining_quantity: int = 0     # Still open
    price: float = 0.0              # Requested price (0 for market orders)
    avg_fill_price: float = 0.0     # Average fill price
    limit_price: float = 0.0        # For limit orders
    slippage: float = 0.0           # Applied slippage per share
    commission: float = 0.0
    tax: float = 0.0
    status: str = OrderStatus.PENDING.value
    reject_reason: str = ""
    reject_detail: str = ""
    created_at: str = ""
    submitted_at: str = ""
    filled_at: str = ""
    updated_at: str = ""
    fills: list = field(default_factory=list)    # List of fill events
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.remaining_quantity and self.quantity > 0:
            self.remaining_quantity = self.quantity
        if not self.order_id:
            self.order_id = f"so_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.EXPIRED.value,
        )

    def validate(self) -> list:
        """Validate order fields. Returns list of error messages."""
        errors = []
        if not self.symbol:
            errors.append("symbol is required")
        if self.quantity <= 0:
            errors.append(f"quantity must be positive, got {self.quantity}")
        if self.quantity % 100 != 0:
            errors.append(f"quantity must be multiple of 100 (A-share lot), got {self.quantity}")
        if self.side not in (OrderSide.BUY.value, OrderSide.SELL.value):
            errors.append(f"invalid side: {self.side}")
        if self.order_type == OrderType.LIMIT.value and self.limit_price <= 0:
            errors.append("limit_price must be > 0 for limit orders")
        if self.price < 0:
            errors.append(f"price cannot be negative: {self.price}")
        return errors

    def transition(self, new_status: OrderStatus) -> dict:
        """Transition order to a new status.

        Returns success dict or error dict on invalid transition.
        """
        current = OrderStatus(self.status)
        target = new_status if isinstance(new_status, OrderStatus) else OrderStatus(new_status)

        if current in (OrderStatus.FILLED, OrderStatus.REJECTED,
                       OrderStatus.CANCELLED, OrderStatus.EXPIRED):
            return {
                "success": False,
                "error": f"Cannot transition from terminal status '{current.value}'",
            }

        if target not in VALID_TRANSITIONS.get(current, set()):
            return {
                "success": False,
                "error": f"Invalid transition: {current.value} → {target.value}",
            }

        self.status = target.value
        self.updated_at = datetime.now(CST).isoformat()

        if target == OrderStatus.SUBMITTED:
            self.submitted_at = self.updated_at
        elif target in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            self.filled_at = self.updated_at

        return {"success": True}

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Fill event
# ---------------------------------------------------------------------------
@dataclass
class FillEvent:
    """A single fill event within an order."""
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    shares: int = 0
    price: float = 0.0
    slippage: float = 0.0
    commission: float = 0.0
    tax: float = 0.0
    filled_at: str = ""

    def __post_init__(self):
        if not self.fill_id:
            self.fill_id = f"fill_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
        if not self.filled_at:
            self.filled_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Order manager
# ---------------------------------------------------------------------------
class ShadowOrderManager:
    """Manages shadow orders: creation, submission, fill tracking.

    This does NOT execute fills — that's the FillEngine's role.
    The order manager tracks state and history.
    """

    def __init__(self):
        self.orders: dict = {}          # order_id -> ShadowOrder
        self.order_history: list = []   # immutable history
        self._next_order_num = 1

    def create_order(self, symbol: str, side: str, quantity: int,
                     price: float = 0.0, order_type: str = "market",
                     signal_id: str = "", proposal_id: str = "",
                     name: str = "", limit_price: float = 0.0,
                     metadata: dict = None) -> ShadowOrder:
        """Create a new shadow order.

        Returns the created order (status=PENDING), or raises on validation error.
        """
        order = ShadowOrder(
            order_id=f"so_{self._next_order_num:06d}_{datetime.now(CST).strftime('%H%M%S_%f')}",
            signal_id=signal_id,
            proposal_id=proposal_id,
            symbol=symbol,
            name=name,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            limit_price=limit_price,
            metadata=metadata or {},
        )
        self._next_order_num += 1

        errors = order.validate()
        if errors:
            order.status = OrderStatus.REJECTED.value
            order.reject_reason = RejectReason.INVALID_QUANTITY.value
            order.reject_detail = "; ".join(errors)
            self.orders[order.order_id] = order
            return order

        self.orders[order.order_id] = order
        return order

    def get_order(self, order_id: str) -> Optional[ShadowOrder]:
        return self.orders.get(order_id)

    def get_orders_by_signal(self, signal_id: str) -> list:
        return [o for o in self.orders.values() if o.signal_id == signal_id]

    def get_orders_by_symbol(self, symbol: str) -> list:
        return [o for o in self.orders.values() if o.symbol == symbol]

    def submit_order(self, order_id: str) -> dict:
        """Submit a pending order to the fill engine."""
        order = self.orders.get(order_id)
        if not order:
            return {"success": False, "error": f"Order not found: {order_id}"}
        return order.transition(OrderStatus.SUBMITTED)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a pending or submitted order."""
        order = self.orders.get(order_id)
        if not order:
            return {"success": False, "error": f"Order not found: {order_id}"}
        if order.is_terminal():
            return {"success": False, "error": f"Order {order_id} already terminal: {order.status}"}

        return order.transition(OrderStatus.CANCELLED)

    def apply_fill(self, order_id: str, fill: FillEvent) -> dict:
        """Apply a fill event to an order.

        Updates order status and fill tracking.
        """
        order = self.orders.get(order_id)
        if not order:
            return {"success": False, "error": f"Order not found: {order_id}"}

        if order.is_terminal():
            return {"success": False, "error": f"Order {order_id} already terminal"}

        if fill.shares <= 0:
            return {"success": False, "error": "Fill shares must be positive"}

        # Record fill
        order.fills.append(fill.to_dict())

        # Update fill tracking
        old_filled = order.filled_quantity
        order.filled_quantity += fill.shares
        order.remaining_quantity = order.quantity - order.filled_quantity

        # Weighted average fill price
        old_notional = old_filled * order.avg_fill_price
        new_notional = fill.shares * fill.price
        if order.filled_quantity > 0:
            order.avg_fill_price = round((old_notional + new_notional) / order.filled_quantity, 4)

        order.commission = round(order.commission + fill.commission, 2)
        order.tax = round(order.tax + fill.tax, 2)
        order.slippage = round(order.slippage + fill.slippage, 2)

        # Update status
        if order.remaining_quantity <= 0:
            order.transition(OrderStatus.FILLED)
        else:
            order.transition(OrderStatus.PARTIALLY_FILLED)

        return {
            "success": True,
            "order_id": order_id,
            "filled_quantity": order.filled_quantity,
            "remaining_quantity": order.remaining_quantity,
            "status": order.status,
        }

    def reject_order(self, order_id: str, reason: str = "",
                     detail: str = "") -> dict:
        """Reject an order."""
        order = self.orders.get(order_id)
        if not order:
            return {"success": False, "error": f"Order not found: {order_id}"}
        if order.is_terminal():
            return {"success": False, "error": "Already terminal"}
        result = order.transition(OrderStatus.REJECTED)
        if result["success"]:
            order.reject_reason = reason or RejectReason.UNKNOWN.value
            order.reject_detail = detail
        return result

    def get_active_orders(self) -> list:
        """Get all orders that are not terminal."""
        return [
            o for o in self.orders.values()
            if not o.is_terminal()
        ]

    def get_summary(self) -> dict:
        """Get a summary of all orders."""
        status_counts = {}
        for o in self.orders.values():
            status_counts[o.status] = status_counts.get(o.status, 0) + 1
        return {
            "total_orders": len(self.orders),
            "active_orders": len(self.get_active_orders()),
            "by_status": status_counts,
        }

    def clear(self):
        """Clear all orders (for test reset)."""
        self.orders.clear()
        self.order_history.clear()

    def to_dict(self) -> dict:
        return {
            "orders": [o.to_dict() for o in self.orders.values()],
            "summary": self.get_summary(),
        }

    def save(self, output_dir: str, name: str = "shadow_orders.json"):
        """Persist all orders to JSON."""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return path
