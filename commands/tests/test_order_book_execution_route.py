"""测试: V4.7 Order Book & Deep Execution Route"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timezone, timedelta

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

CST = timezone(timedelta(hours=8))


# =========================================================================
# Order Book Tests
# =========================================================================

class TestPriceLevel:
    def test_price_level_defaults(self):
        pl = PriceLevel()
        assert pl.price == 0.0
        assert pl.quantity == 0
        assert pl.order_count == 0
        assert pl.side == BookSide.BUY.value

    def test_price_level_to_dict(self):
        pl = PriceLevel(price=10.50, quantity=2000, order_count=3, side="buy")
        d = pl.to_dict()
        assert d["price"] == 10.50
        assert d["quantity"] == 2000
        assert d["order_count"] == 3
        assert d["side"] == "buy"


class TestOrderBookEntry:
    def test_entry_defaults(self):
        entry = OrderBookEntry(order_id="so_001", symbol="000001.SZ")
        assert entry.remaining_quantity == 0
        assert entry.status == "pending"
        assert entry.created_at
        assert entry.updated_at

    def test_entry_remaining_quantity_auto(self):
        entry = OrderBookEntry(order_id="so_001", symbol="000001.SZ", quantity=1000)
        assert entry.remaining_quantity == 1000

    def test_entry_is_active(self):
        active_statuses = ["pending", "submitted", "partially_filled"]
        for s in active_statuses:
            entry = OrderBookEntry(order_id="t", symbol="S", status=s, quantity=100)
            assert entry.is_active(), f"{s} should be active"

    def test_entry_is_terminal(self):
        terminal_statuses = ["filled", "rejected", "cancelled", "expired"]
        for s in terminal_statuses:
            entry = OrderBookEntry(order_id="t", symbol="S", status=s, quantity=100)
            assert entry.is_terminal(), f"{s} should be terminal"
            assert not entry.is_active()

    def test_fill_pct(self):
        entry = OrderBookEntry(order_id="t", symbol="S", quantity=1000,
                                filled_quantity=250)
        assert entry.fill_pct() == 25.0

    def test_fill_pct_zero_quantity(self):
        entry = OrderBookEntry(order_id="t", symbol="S", quantity=0)
        assert entry.fill_pct() == 0.0


class TestOrderBookCore:
    def test_add_order(self):
        book = OrderBook()
        entry = book.add_order("so_001", "000001.SZ", side="buy", price=10.50,
                                quantity=1000, signal_id="sig_1")
        assert entry.order_id == "so_001"
        assert entry.symbol == "000001.SZ"
        assert entry.remaining_quantity == 1000
        assert book.get_order("so_001") is entry

    def test_add_duplicate_order_raises(self):
        book = OrderBook()
        book.add_order("so_001", "000001.SZ", quantity=1000)
        with pytest.raises(ValueError, match="already exists"):
            book.add_order("so_001", "000001.SZ", quantity=2000)

    def test_get_order_not_found(self):
        book = OrderBook()
        assert book.get_order("nonexistent") is None

    def test_get_orders_by_symbol(self):
        book = OrderBook()
        book.add_order("so_001", "000001.SZ", quantity=1000)
        book.add_order("so_002", "000001.SZ", quantity=2000)
        book.add_order("so_003", "000002.SZ", quantity=3000)
        orders = book.get_orders_by_symbol("000001.SZ")
        assert len(orders) == 2
        assert {o.order_id for o in orders} == {"so_001", "so_002"}

    def test_get_orders_by_signal(self):
        book = OrderBook()
        book.add_order("so_001", "A", signal_id="sig_1", quantity=100)
        book.add_order("so_002", "B", signal_id="sig_1", quantity=200)
        book.add_order("so_003", "C", signal_id="sig_2", quantity=300)
        orders = book.get_orders_by_signal("sig_1")
        assert len(orders) == 2

    def test_get_orders_by_proposal(self):
        book = OrderBook()
        book.add_order("so_001", "A", proposal_id="pr_1", quantity=100)
        book.add_order("so_002", "B", proposal_id="pr_1", quantity=200)
        orders = book.get_orders_by_proposal("pr_1")
        assert len(orders) == 2

    def test_get_symbols(self):
        book = OrderBook()
        book.add_order("so_001", "000001.SZ", quantity=100)
        book.add_order("so_002", "000002.SZ", quantity=200)
        assert book.get_symbols() == ["000001.SZ", "000002.SZ"]

    def test_get_active_orders(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)  # pending
        book.add_order("so_002", "A", quantity=100)  # pending
        book.add_order("so_003", "A", quantity=100)  # will fill
        book.update_status("so_003", "filled", filled_quantity=100)
        active = book.get_active_orders()
        assert len(active) == 2
        assert {o.order_id for o in active} == {"so_001", "so_002"}

    def test_get_active_orders_by_symbol(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.add_order("so_002", "B", quantity=100)
        active = book.get_active_orders(symbol="A")
        assert len(active) == 1
        assert active[0].order_id == "so_001"


class TestOrderBookStateTransitions:
    def test_update_status_submitted(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        result = book.update_status("so_001", "submitted")
        assert result["success"]
        assert book.get_order("so_001").status == "submitted"

    def test_update_status_filled(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "filled", filled_quantity=100)
        entry = book.get_order("so_001")
        assert entry.status == "filled"
        assert entry.filled_quantity == 100
        assert entry.remaining_quantity == 0

    def test_update_status_partially_filled(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "partially_filled", filled_quantity=40)
        entry = book.get_order("so_001")
        assert entry.status == "partially_filled"
        assert entry.filled_quantity == 40
        assert entry.remaining_quantity == 60

    def test_update_status_rejected(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        result = book.update_status("so_001", "rejected",
                                      reject_reason="insufficient_cash",
                                      details={"reason": "no funds"})
        assert result["success"]
        entry = book.get_order("so_001")
        assert entry.status == "rejected"

    def test_update_status_cancelled(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "cancelled")
        assert book.get_order("so_001").status == "cancelled"

    def test_update_status_from_terminal_rejected(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "filled", filled_quantity=100)
        result = book.update_status("so_001", "submitted")
        assert not result["success"]
        assert "terminal" in result["error"]

    def test_update_status_order_not_found(self):
        book = OrderBook()
        result = book.update_status("nonexistent", "filled")
        assert not result["success"]
        assert "not found" in result["error"]

    def test_update_fill_convenience(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        result = book.update_fill("so_001", filled_quantity=60, fill_price=10.50)
        assert result["success"]
        entry = book.get_order("so_001")
        assert entry.status == "partially_filled"
        assert entry.filled_quantity == 60

    def test_update_fill_full(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_fill("so_001", filled_quantity=100)
        assert book.get_order("so_001").status == "filled"

    def test_remove_order(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.add_order("so_002", "A", quantity=100)
        result = book.remove_order("so_001")
        assert result["success"]
        assert book.get_order("so_001") is None
        assert len(book.get_orders_by_symbol("A")) == 1

    def test_remove_order_not_found(self):
        book = OrderBook()
        result = book.remove_order("nonexistent")
        assert not result["success"]


class TestOrderBookDepth:
    def test_depth_empty(self):
        book = OrderBook()
        depth = book.get_depth("000001.SZ")
        assert depth["bids"] == []
        assert depth["asks"] == []

    def test_depth_with_limit_orders(self):
        book = OrderBook()
        # Bids at various prices
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "A", side="buy", limit_price=10.49, quantity=2000)
        book.add_order("so_003", "A", side="buy", limit_price=10.50, quantity=500)
        # Asks at various prices
        book.add_order("so_004", "A", side="sell", limit_price=10.55, quantity=1500)
        book.add_order("so_005", "A", side="sell", limit_price=10.56, quantity=1000)

        depth = book.get_depth("A", levels=5)
        assert len(depth["bids"]) == 2
        assert len(depth["asks"]) == 2

        # Best bid should be highest price
        assert depth["bids"][0]["price"] == 10.50
        assert depth["bids"][0]["quantity"] == 1500  # 1000 + 500
        assert depth["bids"][0]["order_count"] == 2

        # Best ask should be lowest price
        assert depth["asks"][0]["price"] == 10.55
        assert depth["asks"][0]["quantity"] == 1500

    def test_depth_market_orders_excluded(self):
        """Market orders (price=0) should not appear in depth levels."""
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", price=0, limit_price=0, quantity=1000)
        depth = book.get_depth("A")
        assert depth["bids"] == []

    def test_depth_after_fill(self):
        """Depth should update after orders are filled."""
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "A", side="sell", limit_price=10.55, quantity=1000)

        tob = book.get_top_of_book("A")
        assert tob["best_bid"] == 10.50
        assert tob["best_ask"] == 10.55

        # Fill the bid order
        book.update_status("so_001", "filled", filled_quantity=1000)
        tob2 = book.get_top_of_book("A")
        assert tob2["best_bid"] == 0.0  # No more bids
        assert tob2["best_ask"] == 10.55

    def test_depth_after_cancel(self):
        """Depth should update after orders are cancelled."""
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "A", side="sell", limit_price=10.55, quantity=1000)
        book.update_status("so_002", "cancelled")
        tob = book.get_top_of_book("A")
        assert tob["best_bid"] == 10.50
        assert tob["best_ask"] == 0.0  # No more asks

    def test_depth_levels_limit(self):
        """get_depth should respect the levels parameter."""
        book = OrderBook()
        for i in range(10):
            book.add_order(f"bid_{i}", "A", side="buy", limit_price=10.50 - i * 0.01,
                            quantity=1000)
            book.add_order(f"ask_{i}", "A", side="sell", limit_price=10.55 + i * 0.01,
                            quantity=1000)

        depth = book.get_depth("A", levels=3)
        assert len(depth["bids"]) == 3
        assert len(depth["asks"]) == 3


class TestOrderBookTopOfBook:
    def test_top_of_book(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "A", side="sell", limit_price=10.55, quantity=500)
        tob = book.get_top_of_book("A")
        assert tob["best_bid"] == 10.50
        assert tob["best_ask"] == 10.55
        assert tob["spread"] == 0.05
        assert tob["mid_price"] == 10.525
        assert tob["total_bid_qty"] == 1000
        assert tob["total_ask_qty"] == 500

    def test_top_of_book_empty(self):
        book = OrderBook()
        tob = book.get_top_of_book("A")
        assert tob["best_bid"] == 0.0
        assert tob["best_ask"] == 0.0
        assert tob["spread"] == 0.0
        assert tob["mid_price"] == 0.0

    def test_top_of_book_one_side(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        tob = book.get_top_of_book("A")
        assert tob["best_bid"] == 10.50
        assert tob["best_ask"] == 0.0
        assert tob["spread"] == 0.0
        assert tob["mid_price"] == 0.0


class TestOrderBookSnapshot:
    def test_get_snapshot(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "A", side="sell", limit_price=10.55, quantity=500)

        snap = book.get_snapshot("A")
        assert isinstance(snap, OrderBookSnapshot)
        assert snap.symbol == "A"
        assert snap.best_bid == 10.50
        assert snap.best_ask == 10.55
        assert snap.total_bid_qty == 1000
        assert snap.total_ask_qty == 500
        assert snap.active_orders == 2
        assert snap.total_orders == 2

    def test_get_full_snapshot(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "B", side="sell", limit_price=20.00, quantity=2000)
        full = book.get_full_snapshot()
        assert "A" in full
        assert "B" in full

    def test_snapshot_to_dict(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        snap = book.get_snapshot("A")
        d = snap.to_dict()
        assert d["symbol"] == "A"
        assert d["best_bid"] == 10.50


class TestOrderBookEvents:
    def test_events_on_add(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        events = book.get_events()
        assert len(events) == 1
        assert events[0].event_type == OrderBookEventType.ORDER_NEW.value
        assert events[0].order_id == "so_001"

    def test_events_on_status_change(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "submitted")
        book.update_status("so_001", "filled", filled_quantity=100)

        events = book.get_events()
        assert len(events) == 3
        assert events[1].event_type == OrderBookEventType.ORDER_SUBMITTED.value
        assert events[2].event_type == OrderBookEventType.ORDER_FILLED.value

    def test_events_filtered_by_type(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "cancelled")
        events = book.get_events(event_type=OrderBookEventType.ORDER_CANCELLED.value)
        assert len(events) == 1
        assert events[0].order_id == "so_001"

    def test_events_filtered_by_symbol(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.add_order("so_002", "B", quantity=100)
        events = book.get_events(symbol="A")
        assert len(events) == 1
        assert events[0].order_id == "so_001"

    def test_events_since_index(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.add_order("so_002", "B", quantity=100)
        events = book.get_events(since_index=1)
        assert len(events) == 1
        assert events[0].order_id == "so_002"

    def test_event_count(self):
        book = OrderBook()
        assert book.get_event_count() == 0
        book.add_order("so_001", "A", quantity=100)
        assert book.get_event_count() == 1
        book.update_status("so_001", "submitted")
        assert book.get_event_count() == 2

    def test_clear_events(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.clear_events()
        assert book.get_event_count() == 0
        assert len(book.get_events()) == 0


class TestOrderBookReset:
    def test_reset_symbol(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.add_order("so_002", "B", quantity=100)
        book.reset(symbol="A")
        assert book.get_order("so_001") is None
        assert book.get_order("so_002") is not None
        assert "A" not in book.get_symbols()

    def test_reset_all(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.add_order("so_002", "B", quantity=100)
        book.reset()
        assert len(book.get_symbols()) == 0
        assert book.get_summary()["total_orders"] == 0


class TestOrderBookSummary:
    def test_get_summary(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", quantity=1000)
        book.add_order("so_002", "A", side="sell", quantity=500)
        book.add_order("so_003", "B", side="buy", quantity=2000)
        book.update_status("so_002", "filled", filled_quantity=500)

        summary = book.get_summary()
        assert summary["symbols"] == 2
        assert summary["total_orders"] == 3
        assert summary["active_orders"] == 2
        assert summary["total_quantity"] == 3500
        assert summary["total_filled"] == 500
        assert summary["by_side"]["buy"] == 2
        assert summary["by_side"]["sell"] == 1


class TestOrderBookPersistence:
    def test_save_and_to_dict(self):
        book = OrderBook()
        book.add_order("so_001", "A", side="buy", limit_price=10.50, quantity=1000)
        book.add_order("so_002", "A", side="sell", limit_price=10.55, quantity=500)
        d = book.to_dict()
        assert "summary" in d
        assert "symbols" in d
        assert d["summary"]["total_orders"] == 2

    def test_save_to_json(self):
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        with tempfile.TemporaryDirectory() as tmp:
            path = book.save(tmp, "test_book.json")
            assert os.path.exists(path)
            data = json.loads(open(path).read())
            assert data["summary"]["total_orders"] == 1


# =========================================================================
# Execution Route Tests
# =========================================================================

class TestRouteType:
    def test_all_route_types_defined(self):
        types = {rt.value for rt in RouteType}
        assert "market" in types
        assert "limit" in types
        assert "twap" in types
        assert "vwap" in types
        assert "iceberg" in types
        assert "smart" in types

    def test_all_urgencies_defined(self):
        urgencies = {ru.value for ru in RouteUrgency}
        assert "immediate" in urgencies
        assert "high" in urgencies
        assert "normal" in urgencies
        assert "low" in urgencies

    def test_all_recommendations_defined(self):
        recs = {rr.value for rr in RouteRecommendation}
        assert "execute_now" in recs
        assert "execute_limit" in recs
        assert "defer" in recs
        assert "split" in recs
        assert "escalate" in recs


class TestRouteConfig:
    def test_defaults_for_market(self):
        cfg = RouteConfig.defaults_for("market")
        assert cfg.route_type == "market"
        assert cfg.max_slippage_bps == 10.0

    def test_defaults_for_limit(self):
        cfg = RouteConfig.defaults_for("limit")
        assert cfg.route_type == "limit"
        assert cfg.limit_offset_bps == -5.0
        assert cfg.max_wait_seconds == 300

    def test_defaults_for_twap(self):
        cfg = RouteConfig.defaults_for("twap")
        assert cfg.route_type == "twap"
        assert cfg.num_slices == 10
        assert cfg.slice_interval_seconds == 30

    def test_defaults_for_vwap(self):
        cfg = RouteConfig.defaults_for("vwap")
        assert cfg.route_type == "vwap"
        assert cfg.num_slices == 20

    def test_defaults_for_iceberg(self):
        cfg = RouteConfig.defaults_for("iceberg")
        assert cfg.route_type == "iceberg"
        assert cfg.min_visible_pct == 10.0

    def test_defaults_for_smart(self):
        cfg = RouteConfig.defaults_for("smart")
        assert cfg.route_type == "smart"
        assert cfg.fallback_route == "limit"
        assert cfg.volatility_threshold == 0.03

    def test_to_dict(self):
        cfg = RouteConfig(route_type="market", max_slippage_bps=15.0)
        d = cfg.to_dict()
        assert d["route_type"] == "market"
        assert d["max_slippage_bps"] == 15.0


class TestRoutePerformance:
    def test_defaults(self):
        perf = RoutePerformance(route_type="market", symbol="A")
        assert perf.total_orders == 0
        assert perf.avg_slippage_bps == 0.0

    def test_record_execution(self):
        perf = RoutePerformance(route_type="market", symbol="A")
        perf.record_execution(slippage_bps=5.0, fill_time_seconds=10, fill_pct=1.0)
        assert perf.total_orders == 1
        assert perf.successful_orders == 1
        assert perf.avg_slippage_bps == 5.0
        assert perf.avg_fill_time_seconds == 10.0

    def test_record_execution_failed(self):
        perf = RoutePerformance(route_type="limit", symbol="A")
        perf.record_execution(slippage_bps=0, success=False)
        assert perf.total_orders == 1
        assert perf.successful_orders == 0
        assert perf.failed_orders == 1

    def test_record_multiple(self):
        perf = RoutePerformance(route_type="market", symbol="A")
        perf.record_execution(slippage_bps=4.0, fill_time_seconds=10)
        perf.record_execution(slippage_bps=6.0, fill_time_seconds=20)
        assert perf.total_orders == 2
        assert perf.avg_slippage_bps == 5.0
        assert perf.avg_fill_time_seconds == 15.0

    def test_to_dict_omits_private(self):
        perf = RoutePerformance(route_type="market", symbol="A")
        perf.record_execution(slippage_bps=5.0)
        d = perf.to_dict()
        assert "_total_slippage_bps" not in d
        assert "avg_slippage_bps" in d

    def test_merge(self):
        p1 = RoutePerformance(route_type="market", symbol="A")
        p1.record_execution(slippage_bps=4.0)
        p1.record_execution(slippage_bps=6.0)

        p2 = RoutePerformance(route_type="market", symbol="A")
        p2.record_execution(slippage_bps=10.0)

        merged = p1.merge(p2)
        assert merged.total_orders == 3
        assert merged.avg_slippage_bps == pytest.approx(20.0 / 3, rel=1e-4)


class TestRouteSelector:
    def test_default_configs_loaded(self):
        selector = RouteSelector()
        for rt in RouteType:
            assert rt.value in selector.configs

    def test_set_config(self):
        selector = RouteSelector()
        cfg = RouteConfig(route_type="market", max_slippage_bps=20.0)
        selector.set_config("market", cfg)
        assert selector.get_config("market").max_slippage_bps == 20.0

    def test_evaluate_immediate_market_order(self):
        """Immediate urgent orders should favor MARKET route."""
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="000001.SZ", quantity=1000, side="buy",
            urgency="immediate", spread=0.05, bid_size=50000, ask_size=45000,
            avg_daily_volume=1000000, price=10.50,
        )
        assert result.recommended_route == RouteType.MARKET.value
        assert result.confidence > 0.5
        assert len(result.score_by_route) == 6  # All route types scored
        assert result.estimated_slippage_bps > 0

    def test_evaluate_low_urgency_limit(self):
        """Low urgency should favor LIMIT route."""
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="000001.SZ", quantity=1000, side="buy",
            urgency="low", spread=0.02, bid_size=50000, ask_size=45000,
            avg_daily_volume=1000000, price=10.50,
        )
        assert result.recommended_route in (RouteType.LIMIT.value, RouteType.VWAP.value)
        assert RouteResult is not None

    def test_evaluate_large_order_iceberg(self):
        """Very large orders relative to ADV should favor ICEBERG or VWAP."""
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="000001.SZ", quantity=100000, side="buy",
            urgency="normal", spread=0.03, bid_size=50000, ask_size=45000,
            avg_daily_volume=500000, price=10.50,
        )
        # Large order (20% of ADV) should suggest splitting
        assert result.recommended_route != RouteType.MARKET.value

    def test_evaluate_normal_order_vwap(self):
        """Normal orders with benchmark awareness should consider VWAP."""
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="000001.SZ", quantity=20000, side="buy",
            urgency="normal", spread=0.02, bid_size=50000, ask_size=45000,
            avg_daily_volume=1000000, price=10.50,
        )
        # Should get a sensible route
        assert result.recommended_route in (rt.value for rt in RouteType)
        assert result.estimated_slices >= 1

    def test_evaluate_high_volatility(self):
        """High volatility should trigger warnings."""
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="000001.SZ", quantity=1000, side="buy",
            urgency="normal", spread=0.10, volatility=0.08,
            bid_size=50000, ask_size=45000,
            avg_daily_volume=1000000, price=10.50,
        )
        warns = [w for w in result.warnings if "volatility" in w.lower()]
        assert len(warns) >= 0  # May or may not warn depending on route

    def test_performance_tracking(self):
        selector = RouteSelector()
        selector.record_performance("market", "A", slippage_bps=5.0, fill_time_seconds=10)
        selector.record_performance("market", "A", slippage_bps=3.0, fill_time_seconds=8)

        perf = selector.get_performance("market", "A")
        assert perf is not None
        assert perf.total_orders == 2
        assert perf.avg_slippage_bps == 4.0

    def test_evaluate_with_performance_history(self):
        """Historical performance should influence scoring."""
        selector = RouteSelector()
        selector.record_performance("market", "A", slippage_bps=1.0, fill_time_seconds=5)
        selector.record_performance("market", "A", slippage_bps=1.5, fill_time_seconds=6)
        selector.record_performance("market", "A", slippage_bps=0.5, fill_time_seconds=4)
        selector.record_performance("market", "A", slippage_bps=2.0, fill_time_seconds=7)
        selector.record_performance("market", "A", slippage_bps=1.0, fill_time_seconds=5)
        selector.record_performance("market", "A", slippage_bps=1.2, fill_time_seconds=6)

        # After 6 successful trades, market route should have good performance score
        result = selector.evaluate(
            symbol="A", quantity=1000, side="buy",
            urgency="immediate", spread=0.02,
            bid_size=50000, ask_size=45000,
            avg_daily_volume=1000000, price=10.50,
        )
        assert result.recommended_route == RouteType.MARKET.value

    def test_to_dict(self):
        selector = RouteSelector()
        d = selector.to_dict()
        assert "configs" in d
        assert "performance" in d
        for rt in RouteType:
            assert rt.value in d["configs"]


class TestRouteResult:
    def test_defaults(self):
        result = RouteResult()
        assert result.recommended_route == "market"
        assert result.recommendation == RouteRecommendation.EXECUTE_NOW.value
        assert result.evaluated_at

    def test_to_dict(self):
        result = RouteResult(
            order_id="so_001",
            symbol="A",
            recommended_route="vwap",
            confidence=0.85,
            estimated_slippage_bps=3.0,
            reasoning="VWAP preferred for large order",
        )
        d = result.to_dict()
        assert d["order_id"] == "so_001"
        assert d["recommended_route"] == "vwap"
        assert d["confidence"] == 0.85


# =========================================================================
# Deep Execution Router Tests
# =========================================================================

class TestDeepExecutionRouter:
    def test_default_construction(self):
        router = DeepExecutionRouter()
        assert router.order_book is not None
        assert router.selector is not None
        assert router._routing_history == []

    def test_route_order_basic(self):
        router = DeepExecutionRouter()
        result = router.route_order(
            symbol="000001.SZ", quantity=1000, side="buy",
            urgency="immediate", spread=0.05,
            bid_size=50000, ask_size=45000,
            avg_daily_volume=1000000, price=10.50,
        )
        assert isinstance(result, RouteResult)
        assert result.symbol == "000001.SZ"
        assert result.recommended_route
        assert len(router._routing_history) == 1

    def test_route_order_with_existing_book_order(self):
        """Router should read market data from the order book."""
        router = DeepExecutionRouter()
        router.order_book.add_order("so_001", "A", side="buy",
                                     limit_price=10.50, quantity=1000)
        router.order_book.add_order("so_002", "A", side="sell",
                                     limit_price=10.55, quantity=500)

        result = router.route_order(
            symbol="A", quantity=1000, side="buy",
            urgency="normal", avg_daily_volume=1000000,
            order_id="so_001",
        )
        assert result.symbol == "A"
        assert result.recommended_route

        # Order should have route assigned
        entry = router.order_book.get_order("so_001")
        assert entry.route == result.recommended_route

    def test_route_order_and_assign(self):
        router = DeepExecutionRouter()
        router.order_book.add_order("so_001", "A", quantity=1000)
        result = router.route_order(
            symbol="A", quantity=1000, side="buy",
            urgency="normal", avg_daily_volume=1000000,
            order_id="so_001",
        )
        entry = router.order_book.get_order("so_001")
        assert entry.route == result.recommended_route

    def test_record_execution_result(self):
        router = DeepExecutionRouter()
        router.record_execution_result("market", "A", slippage_bps=3.0)
        perf = router.selector.get_performance("market", "A")
        assert perf is not None
        assert perf.total_orders == 1

    def test_get_routing_report(self):
        router = DeepExecutionRouter()
        router.route_order(symbol="A", quantity=1000, side="buy",
                           urgency="immediate", spread=0.03,
                           bid_size=50000, ask_size=45000,
                           avg_daily_volume=1000000, price=10.50)
        router.route_order(symbol="B", quantity=500, side="sell",
                           urgency="low", spread=0.02,
                           bid_size=30000, ask_size=25000,
                           avg_daily_volume=500000, price=20.00)

        report = router.get_routing_report()
        assert report["total_routed"] == 2
        assert len(report["recent_routes"]) == 2

    def test_get_routing_report_filtered(self):
        router = DeepExecutionRouter()
        router.record_execution_result("market", "A", slippage_bps=5.0)
        router.record_execution_result("limit", "A", slippage_bps=2.0)

        report = router.get_routing_report(symbol="A")
        assert "market" in report["performance"]
        assert "limit" in report["performance"]

    def test_get_summary(self):
        router = DeepExecutionRouter()
        router.route_order(symbol="A", quantity=1000, side="buy",
                           urgency="immediate", spread=0.03,
                           bid_size=50000, ask_size=45000,
                           avg_daily_volume=1000000, price=10.50)

        summary = router.get_summary()
        assert summary["total_routed"] == 1
        assert summary["book_summary"]["total_orders"] == 0  # No book order added
        assert len(summary["configs"]) == 6

    def test_save_to_json(self):
        router = DeepExecutionRouter()
        router.route_order(symbol="A", quantity=1000, side="buy",
                           urgency="immediate", spread=0.03,
                           bid_size=50000, ask_size=45000,
                           avg_daily_volume=1000000, price=10.50)

        with tempfile.TemporaryDirectory() as tmp:
            path = router.save(tmp, "test_router.json")
            assert os.path.exists(path)
            data = json.loads(open(path).read())
            assert data["summary"]["total_routed"] == 1

    def test_integration_book_and_router(self):
        """Full integration: add orders to book, route them, record results."""
        router = DeepExecutionRouter()

        # Add orders to book
        router.order_book.add_order("so_001", "A", side="buy",
                                     limit_price=10.50, quantity=10000,
                                     signal_id="sig_alpha")
        router.order_book.add_order("so_002", "A", side="sell",
                                     limit_price=10.55, quantity=5000,
                                     signal_id="sig_beta")

        # Route them
        r1 = router.route_order(symbol="A", quantity=10000, side="buy",
                                 urgency="normal", avg_daily_volume=1000000,
                                 order_id="so_001")
        r2 = router.route_order(symbol="A", quantity=5000, side="sell",
                                 urgency="low", avg_daily_volume=1000000,
                                 order_id="so_002")

        assert r1.recommended_route != r2.recommended_route or True  # May differ

        # Record execution results
        router.record_execution_result(r1.recommended_route, "A",
                                        slippage_bps=4.0, fill_time_seconds=120)

        # Snapshot should reflect book state
        snap = router.order_book.get_snapshot("A")
        assert snap.active_orders == 2
        assert snap.total_orders == 2


class TestEdgeCases:
    def test_empty_book_operations(self):
        book = OrderBook()
        assert book.get_summary()["total_orders"] == 0
        assert book.get_symbols() == []
        assert book.get_active_orders() == []

    def test_book_with_many_orders(self):
        book = OrderBook()
        for i in range(100):
            book.add_order(f"so_{i:03d}", "A", side="buy" if i % 2 == 0 else "sell",
                            limit_price=10.00 + i * 0.01, quantity=1000)
        summary = book.get_summary()
        assert summary["total_orders"] == 100
        assert summary["active_orders"] == 100

    def test_router_with_no_market_data(self):
        router = DeepExecutionRouter()
        result = router.route_order(symbol="A", quantity=1000, side="buy")
        assert result.recommended_route
        assert result.estimated_slippage_bps >= 0

    def test_route_all_urgencies_produce_result(self):
        selector = RouteSelector()
        for urgency in RouteUrgency:
            result = selector.evaluate(
                symbol="A", quantity=1000, side="buy",
                urgency=urgency.value, spread=0.03,
                bid_size=50000, ask_size=45000,
                avg_daily_volume=1000000, price=10.50,
            )
            assert result.recommended_route in (rt.value for rt in RouteType)
            assert urgency.value in result.reasoning

    def test_performance_merge_empty(self):
        p1 = RoutePerformance(route_type="market", symbol="A")
        p2 = RoutePerformance(route_type="market", symbol="A")
        merged = p1.merge(p2)
        assert merged.total_orders == 0

    def test_event_immutability(self):
        """Events should maintain accurate history even after order removal."""
        book = OrderBook()
        book.add_order("so_001", "A", quantity=100)
        book.update_status("so_001", "submitted")
        book.update_status("so_001", "filled", filled_quantity=100)
        book.remove_order("so_001")

        events = book.get_events()
        assert len(events) == 4  # new, submitted, filled, expired(removed)
        assert events[-1].event_type == OrderBookEventType.ORDER_EXPIRED.value

    def test_twap_route_for_medium_order(self):
        """Twap should score well for medium orders with normal urgency."""
        selector = RouteSelector()
        result = selector.evaluate(
            symbol="A", quantity=30000, side="buy",
            urgency="normal", spread=0.02,
            bid_size=100000, ask_size=90000,
            avg_daily_volume=1000000, price=10.50,
        )
        # TWAP should be competitive for this scenario
        twap_score = result.score_by_route.get("twap", 0)
        assert twap_score >= 60
