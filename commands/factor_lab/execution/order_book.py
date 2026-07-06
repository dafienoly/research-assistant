"""V4.7 Order Book & Deep Execution Route — Centralized Order Book

Central order book that aggregates and tracks all order activity across
the execution pipeline. Provides real-time depth, symbol-level aggregation,
event streaming, and snapshot capabilities.

Core capabilities:
  1. PriceLevel         — Quantity tracked at a specific price/side
  2. OrderBookEntry     — A live order tracked in the book
  3. OrderBookEvent     — Immutable event for audit trail
  4. OrderBook          — Central book: depth, aggregation, snapshots, events

Design:
  - The OrderBook is the single source of truth for order state across all
    pipeline stages (proposal → approval → shadow → live readiness).
  - Every state change produces an immutable OrderBookEvent in the audit trail.
  - Depth is maintained as sorted bid/ask levels per symbol, recalculated
    from the underlying orders.
  - The book can generate point-in-time snapshots for reporting and checkpoint.
  - Integrates with ShadowOrderManager, TradeFilterEngine, and RouteSelector.
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
class BookSide(Enum):
    """Side of the order book."""
    BUY = "buy"
    SELL = "sell"


class OrderBookEventType(Enum):
    """Types of events that can occur in the order book."""
    ORDER_NEW = "order_new"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_PARTIALLY_FILLED = "order_partially_filled"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_EXPIRED = "order_expired"
    ORDER_MODIFIED = "order_modified"
    BOOK_SNAPSHOT = "book_snapshot"
    BOOK_RESET = "book_reset"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class PriceLevel:
    """Quantity available at a specific price on one side of the book.

    bid level example: price=10.50, quantity=2000 (2000 shares bid at ¥10.50)
    ask level example: price=10.55, quantity=1500 (1500 shares offered at ¥10.55)
    """
    price: float = 0.0
    quantity: int = 0          # Total shares at this level
    order_count: int = 0       # Number of orders at this level
    side: str = BookSide.BUY.value

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderBookEntry:
    """A single order tracked in the book.

    Mirrors relevant fields from ShadowOrder but adds book-specific
    tracking fields for depth and aggregation.
    """
    order_id: str = ""
    signal_id: str = ""
    proposal_id: str = ""
    symbol: str = ""
    name: str = ""
    side: str = BookSide.BUY.value
    price: float = 0.0              # Requested price (0 for market)
    limit_price: float = 0.0        # For limit orders
    quantity: int = 0               # Original requested quantity
    filled_quantity: int = 0        # Cumulatively filled
    remaining_quantity: int = 0     # Still open
    status: str = "pending"         # Mirrors OrderStatus values
    route: str = ""                 # Execution route assigned
    created_at: str = ""
    updated_at: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.remaining_quantity and self.quantity > 0:
            self.remaining_quantity = self.quantity
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def is_active(self) -> bool:
        """An entry is active if it can still receive fills."""
        return self.status in ("pending", "submitted", "partially_filled")

    def is_terminal(self) -> bool:
        return self.status in ("filled", "rejected", "cancelled", "expired")

    def fill_pct(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return round(self.filled_quantity / self.quantity * 100, 2)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderBookEvent:
    """Immutable event recording a state change in the order book.

    Every order book mutation produces one event. Events are append-only
    and form the complete audit trail.
    """
    event_id: str = ""
    event_type: str = ""
    symbol: str = ""
    order_id: str = ""
    timestamp: str = ""
    previous_status: str = ""
    new_status: str = ""
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"obe_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
        if not self.timestamp:
            self.timestamp = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Book snapshot
# ---------------------------------------------------------------------------
@dataclass
class OrderBookSnapshot:
    """Point-in-time snapshot of the order book for one symbol.

    Includes top-of-book, full depth, and summary statistics.
    """
    symbol: str = ""
    generated_at: str = ""
    bid_levels: list = field(default_factory=list)     # PriceLevel dicts
    ask_levels: list = field(default_factory=list)     # PriceLevel dicts
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    mid_price: float = 0.0
    total_bid_qty: int = 0
    total_ask_qty: int = 0
    active_orders: int = 0
    total_orders: int = 0
    events_since_snapshot: int = 0

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Order Book
# ---------------------------------------------------------------------------
class OrderBook:
    """Centralized order book that aggregates orders across all symbols.

    The book is the single source of truth for all order state in the
    execution pipeline. It provides:
      - Per-symbol depth with sorted price levels
      - Top-of-book (best bid/ask, spread, mid-price)
      - Order lookup by ID, symbol, or signal
      - Immutable event audit trail
      - Point-in-time snapshots

    Usage:
        book = OrderBook()
        book.add_order(order_id="so_001", symbol="000001.SZ", side="buy",
                       price=10.50, quantity=1000)
        book.update_fill(order_id="so_001", filled_qty=500)
        snapshot = book.get_snapshot("000001.SZ")
    """

    def __init__(self):
        # Primary storage: order_id -> OrderBookEntry
        self._entries: dict[str, OrderBookEntry] = {}

        # Index: symbol -> list of order_ids
        self._by_symbol: dict[str, list[str]] = {}

        # Index: signal_id -> list of order_ids
        self._by_signal: dict[str, list[str]] = {}

        # Index: proposal_id -> list of order_ids
        self._by_proposal: dict[str, list[str]] = {}

        # Depth cache: (symbol, side) -> [(price, total_qty, order_count)]
        # Rebuilt lazily on mutation
        self._depth_cache: dict[tuple[str, str], list[tuple[float, int, int]]] = {}
        self._depth_dirty: bool = True

        # Immutable event audit trail
        self._events: list[OrderBookEvent] = []
        self._next_event_num: int = 1

        # Summary
        self._event_count: int = 0

    # -----------------------------------------------------------------------
    # Core mutations
    # -----------------------------------------------------------------------
    def add_order(self, order_id: str, symbol: str,
                  side: str = BookSide.BUY.value,
                  price: float = 0.0,
                  limit_price: float = 0.0,
                  quantity: int = 0,
                  signal_id: str = "",
                  proposal_id: str = "",
                  name: str = "",
                  route: str = "",
                  status: str = "pending",
                  metadata: dict = None) -> OrderBookEntry:
        """Add a new order to the book.

        Returns the created OrderBookEntry. Fires an ORDER_NEW event.
        """
        if order_id in self._entries:
            raise ValueError(f"Order {order_id} already exists in book")

        entry = OrderBookEntry(
            order_id=order_id,
            signal_id=signal_id,
            proposal_id=proposal_id,
            symbol=symbol,
            name=name,
            side=side,
            price=price,
            limit_price=limit_price,
            quantity=quantity,
            remaining_quantity=quantity,
            status=status,
            route=route,
            metadata=metadata or {},
        )

        self._entries[order_id] = entry
        self._by_symbol.setdefault(symbol, []).append(order_id)
        if signal_id:
            self._by_signal.setdefault(signal_id, []).append(order_id)
        if proposal_id:
            self._by_proposal.setdefault(proposal_id, []).append(order_id)

        self._mark_depth_dirty()
        self._emit_event(OrderBookEventType.ORDER_NEW.value, symbol, order_id,
                         previous_status="", new_status=status,
                         details={"price": price, "quantity": quantity, "side": side})
        return entry

    def update_status(self, order_id: str, new_status: str,
                      filled_quantity: int = 0,
                      reject_reason: str = "",
                      details: dict = None) -> dict:
        """Update the status of an existing order.

        Supports: submitted, partially_filled, filled, rejected, cancelled, expired.
        Fires the corresponding event type.
        """
        entry = self._entries.get(order_id)
        if not entry:
            return {"success": False, "error": f"Order {order_id} not found"}

        if entry.is_terminal() and new_status not in ("", entry.status):
            return {
                "success": False,
                "error": f"Order {order_id} already terminal: {entry.status}",
            }

        old_status = entry.status
        was_active = entry.is_active()

        entry.status = new_status
        entry.updated_at = datetime.now(CST).isoformat()

        if filled_quantity > 0:
            entry.filled_quantity = filled_quantity
            entry.remaining_quantity = max(0, entry.quantity - filled_quantity)

        # Map status -> event type
        event_map = {
            "submitted": OrderBookEventType.ORDER_SUBMITTED,
            "partially_filled": OrderBookEventType.ORDER_PARTIALLY_FILLED,
            "filled": OrderBookEventType.ORDER_FILLED,
            "rejected": OrderBookEventType.ORDER_REJECTED,
            "cancelled": OrderBookEventType.ORDER_CANCELLED,
            "expired": OrderBookEventType.ORDER_EXPIRED,
        }
        etype = event_map.get(new_status, OrderBookEventType.ORDER_MODIFIED)

        evt_details = dict(details or {})
        if reject_reason:
            evt_details["reject_reason"] = reject_reason
        if filled_quantity > 0:
            evt_details["filled_quantity"] = filled_quantity

        self._mark_depth_dirty()
        self._emit_event(etype.value, entry.symbol, order_id,
                         previous_status=old_status, new_status=new_status,
                         details=evt_details)
        return {"success": True, "previous_status": old_status, "new_status": new_status}

    def update_fill(self, order_id: str, filled_quantity: int,
                    fill_price: float = 0.0, shares_filled: int = 0) -> dict:
        """Update fill state for a partially or fully filled order.

        This is a convenience wrapper around update_status that also tracks
        fill details.
        """
        entry = self._entries.get(order_id)
        if not entry:
            return {"success": False, "error": f"Order {order_id} not found"}

        new_filled = filled_quantity or (entry.filled_quantity + shares_filled)
        if new_filled > entry.quantity:
            new_filled = entry.quantity

        new_status = "filled" if new_filled >= entry.quantity else "partially_filled"
        return self.update_status(
            order_id, new_status,
            filled_quantity=new_filled,
            details={"fill_price": fill_price, "shares_filled": shares_filled or new_filled},
        )

    def remove_order(self, order_id: str) -> dict:
        """Remove an order from the book entirely (e.g., expired and purged).

        This is the only destructive operation — use sparingly.
        """
        entry = self._entries.pop(order_id, None)
        if not entry:
            return {"success": False, "error": f"Order {order_id} not found"}

        # Clean indices
        for idx in (self._by_symbol, self._by_signal, self._by_proposal):
            for key in list(idx.keys()):
                if order_id in idx[key]:
                    idx[key] = [oid for oid in idx[key] if oid != order_id]
                    if not idx[key]:
                        del idx[key]

        self._mark_depth_dirty()
        self._emit_event(OrderBookEventType.ORDER_EXPIRED.value, entry.symbol, order_id,
                         previous_status=entry.status, new_status="removed",
                         details={"reason": "removed_from_book"})
        return {"success": True}

    # -----------------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------------
    def get_order(self, order_id: str) -> Optional[OrderBookEntry]:
        return self._entries.get(order_id)

    def get_orders_by_symbol(self, symbol: str) -> list[OrderBookEntry]:
        ids = self._by_symbol.get(symbol, [])
        return [self._entries[oid] for oid in ids if oid in self._entries]

    def get_orders_by_signal(self, signal_id: str) -> list[OrderBookEntry]:
        ids = self._by_signal.get(signal_id, [])
        return [self._entries[oid] for oid in ids if oid in self._entries]

    def get_orders_by_proposal(self, proposal_id: str) -> list[OrderBookEntry]:
        ids = self._by_proposal.get(proposal_id, [])
        return [self._entries[oid] for oid in ids if oid in self._entries]

    def get_active_orders(self, symbol: str = "") -> list[OrderBookEntry]:
        """Get all non-terminal orders, optionally filtered by symbol."""
        if symbol:
            return [e for e in self.get_orders_by_symbol(symbol) if e.is_active()]
        return [e for e in self._entries.values() if e.is_active()]

    def get_symbols(self) -> list[str]:
        return sorted(self._by_symbol.keys())

    # -----------------------------------------------------------------------
    # Depth / Market data
    # -----------------------------------------------------------------------
    def _build_depth(self, symbol: str) -> None:
        """Build bid/ask price levels for a symbol from active orders."""
        bids: dict[float, int] = {}    # price -> total quantity
        bid_counts: dict[float, int] = {}
        asks: dict[float, int] = {}
        ask_counts: dict[float, int] = {}

        for entry in self._entries.values():
            if entry.symbol != symbol:
                continue
            if not entry.is_active():
                continue
            if entry.remaining_quantity <= 0:
                continue

            # Use limit_price for limit orders, price for others
            level_price = entry.limit_price if entry.limit_price > 0 else entry.price
            if level_price <= 0:
                continue  # Market orders don't contribute to depth

            qty = entry.remaining_quantity
            if entry.side == BookSide.BUY.value:
                bids[level_price] = bids.get(level_price, 0) + qty
                bid_counts[level_price] = bid_counts.get(level_price, 0) + 1
            else:
                asks[level_price] = asks.get(level_price, 0) + qty
                ask_counts[level_price] = ask_counts.get(level_price, 0) + 1

        # Sort: bids descending (best bid = highest price), asks ascending
        sorted_bids = sorted(
            [(p, bids[p], bid_counts[p]) for p in bids],
            key=lambda x: -x[0],
        )
        sorted_asks = sorted(
            [(p, asks[p], ask_counts[p]) for p in asks],
            key=lambda x: x[0],
        )

        self._depth_cache[(symbol, BookSide.BUY.value)] = sorted_bids
        self._depth_cache[(symbol, BookSide.SELL.value)] = sorted_asks

    def _mark_depth_dirty(self):
        self._depth_dirty = True

    def get_depth(self, symbol: str, levels: int = 5) -> dict:
        """Get top-N price levels for both sides of the book.

        Returns:
            {"bids": [PriceLevel.dict, ...], "asks": [PriceLevel.dict, ...]}
        """
        if self._depth_dirty:
            self._build_depth(symbol)
            self._depth_dirty = False

        bids_raw = self._depth_cache.get((symbol, BookSide.BUY.value), [])
        asks_raw = self._depth_cache.get((symbol, BookSide.SELL.value), [])

        bids = [
            PriceLevel(price=p, quantity=q, order_count=c, side=BookSide.BUY.value).to_dict()
            for p, q, c in bids_raw[:levels]
        ]
        asks = [
            PriceLevel(price=p, quantity=q, order_count=c, side=BookSide.SELL.value).to_dict()
            for p, q, c in asks_raw[:levels]
        ]
        return {"bids": bids, "asks": asks}

    def get_top_of_book(self, symbol: str) -> dict:
        """Get best bid, best ask, spread, and mid-price."""
        depth = self.get_depth(symbol, levels=1)
        best_bid = depth["bids"][0]["price"] if depth["bids"] else 0.0
        best_ask = depth["asks"][0]["price"] if depth["asks"] else 0.0
        spread = round(best_ask - best_bid, 4) if best_bid > 0 and best_ask > 0 else 0.0
        mid = round((best_bid + best_ask) / 2, 4) if best_bid > 0 and best_ask > 0 else 0.0
        total_bid_qty = sum(depth["bids"][i]["quantity"] for i in range(len(depth["bids"])))
        total_ask_qty = sum(depth["asks"][i]["quantity"] for i in range(len(depth["asks"])))
        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "mid_price": mid,
            "total_bid_qty": total_bid_qty,
            "total_ask_qty": total_ask_qty,
        }

    # -----------------------------------------------------------------------
    # Snapshots
    # -----------------------------------------------------------------------
    def get_snapshot(self, symbol: str) -> OrderBookSnapshot:
        """Generate a point-in-time snapshot for one symbol."""
        depth = self.get_depth(symbol, levels=20)
        tob = self.get_top_of_book(symbol)
        active = self.get_active_orders(symbol)
        all_symbol_orders = self.get_orders_by_symbol(symbol)

        snap = OrderBookSnapshot(
            symbol=symbol,
            bid_levels=depth["bids"],
            ask_levels=depth["asks"],
            best_bid=tob["best_bid"],
            best_ask=tob["best_ask"],
            spread=tob["spread"],
            mid_price=tob["mid_price"],
            total_bid_qty=tob["total_bid_qty"],
            total_ask_qty=tob["total_ask_qty"],
            active_orders=len(active),
            total_orders=len(all_symbol_orders),
            events_since_snapshot=self._event_count,
        )
        return snap

    def get_full_snapshot(self) -> dict:
        """Generate snapshot for all symbols in the book."""
        return {
            symbol: self.get_snapshot(symbol).to_dict()
            for symbol in self.get_symbols()
        }

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    def get_summary(self) -> dict:
        """Get summary statistics across the entire book."""
        status_counts = {}
        side_counts = {"buy": 0, "sell": 0}
        total_qty = 0
        total_filled = 0

        for entry in self._entries.values():
            status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
            if entry.side in side_counts:
                side_counts[entry.side] += 1
            total_qty += entry.quantity
            total_filled += entry.filled_quantity

        return {
            "symbols": len(self._by_symbol),
            "total_orders": len(self._entries),
            "active_orders": len(self.get_active_orders()),
            "total_quantity": total_qty,
            "total_filled": total_filled,
            "by_status": status_counts,
            "by_side": side_counts,
            "events": self._event_count,
        }

    # -----------------------------------------------------------------------
    # Event audit trail
    # -----------------------------------------------------------------------
    def _emit_event(self, event_type: str, symbol: str, order_id: str,
                    previous_status: str = "", new_status: str = "",
                    details: dict = None):
        event = OrderBookEvent(
            event_id=f"obe_{self._next_event_num:06d}_{datetime.now(CST).strftime('%H%M%S_%f')}",
            event_type=event_type,
            symbol=symbol,
            order_id=order_id,
            previous_status=previous_status,
            new_status=new_status,
            details=details or {},
        )
        self._events.append(event)
        self._next_event_num += 1
        self._event_count += 1

    def get_events(self, since_index: int = 0,
                   event_type: str = "",
                   symbol: str = "") -> list[OrderBookEvent]:
        """Get events from the audit trail, optionally filtered."""
        events = self._events[since_index:]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if symbol:
            events = [e for e in events if e.symbol == symbol]
        return events

    def get_event_count(self) -> int:
        return self._event_count

    # -----------------------------------------------------------------------
    # State management
    # -----------------------------------------------------------------------
    def reset(self, symbol: str = "") -> dict:
        """Reset orders for one symbol or the entire book.

        Emits a BOOK_RESET event.
        """
        if symbol:
            order_ids = self._by_symbol.pop(symbol, [])
            for oid in order_ids:
                self._entries.pop(oid, None)
            self._emit_event(OrderBookEventType.BOOK_RESET.value, symbol, "",
                             details={"symbol": symbol})
        else:
            self._entries.clear()
            self._by_symbol.clear()
            self._by_signal.clear()
            self._by_proposal.clear()
            self._depth_cache.clear()
            self._emit_event(OrderBookEventType.BOOK_RESET.value, "*", "",
                             details={"full_reset": True})

        self._mark_depth_dirty()
        return {"success": True, "symbol": symbol or "*all"}

    def clear_events(self):
        """Clear the event audit trail (for testing/cleanup)."""
        self._events.clear()
        self._event_count = 0

    # -----------------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "summary": self.get_summary(),
            "symbols": {
                sym: {
                    "orders": [e.to_dict() for e in self.get_orders_by_symbol(sym)],
                    "top_of_book": self.get_top_of_book(sym),
                }
                for sym in self.get_symbols()
            },
            "events": [e.to_dict() for e in self._events[-100:]],  # Last 100 events
        }

    def save(self, output_dir: str, name: str = "order_book.json") -> str:
        """Persist the entire book to JSON."""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return path
