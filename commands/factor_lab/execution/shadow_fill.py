"""V4.1 Shadow Live Pipeline — Shadow Fill Engine & Slippage Simulation

Simulates order fills using market data and configurable slippage models.

Slippage models:
  1. FIXED_PCT       — fixed percentage of price (e.g., 0.1%)
  2. VOLUME_BASED    — proportional to order_size / avg_volume
  3. VOLATILITY_BASED — proportional to recent volatility
  4. HYBRID           — combination of volume and volatility

Fill strategies:
  - IMMEDIATE       — fill instantly at current price + slippage
  - PARTIAL         — fill in chunks over time (simulates partial fills)
  - REJECT_ON_LIMIT — reject if price exceeds limit (for limit orders)

Safety:
  - All fills are simulated — no real orders
  - Market data missing = rejection with clear error
  - Fill engine reports data lineage for every fill
"""

import math
import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Callable

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Slippage model types
# ---------------------------------------------------------------------------
class SlippageModel(Enum):
    FIXED_PCT = "fixed_pct"
    VOLUME_BASED = "volume_based"
    VOLATILITY_BASED = "volatility_based"
    HYBRID = "hybrid"
    NONE = "none"


class FillStrategy(Enum):
    IMMEDIATE = "immediate"        # Fill all at once
    PARTIAL = "partial"            # Fill in chunks (simulates real market)
    REJECT_ON_LIMIT = "reject_on_limit"  # For limit orders


class MarketDataStatus(Enum):
    AVAILABLE = "available"
    STALE = "stale"                # Data exists but is too old
    MISSING = "missing"            # No data for this symbol
    INSUFFICIENT = "insufficient"  # Not enough history for model


# ---------------------------------------------------------------------------
# Slippage config
# ---------------------------------------------------------------------------
@dataclass
class SlippageConfig:
    """Configuration for slippage simulation."""
    model: str = SlippageModel.FIXED_PCT.value
    fixed_pct: float = 0.001       # 0.1% default
    volume_basis: float = 0.5      # portion of order_ratio applied
    volatility_scalar: float = 0.1  # volatility contribution
    min_slippage: float = 0.0      # minimum slippage (yuan)
    max_slippage: float = 0.10     # maximum slippage (yuan) — ~涨停/跌停 limit
    max_slippage_pct: float = 0.05  # 5% max — soft cap
    fill_strategy: str = FillStrategy.IMMEDIATE.value
    partial_fill_chunks: int = 3    # For PARTIAL strategy
    partial_fill_interval_minutes: int = 5

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "fixed_pct": self.fixed_pct,
            "volume_basis": self.volume_basis,
            "volatility_scalar": self.volatility_scalar,
            "min_slippage": self.min_slippage,
            "max_slippage": self.max_slippage,
            "max_slippage_pct": self.max_slippage_pct,
            "fill_strategy": self.fill_strategy,
            "partial_fill_chunks": self.partial_fill_chunks,
            "partial_fill_interval_minutes": self.partial_fill_interval_minutes,
        }


# ---------------------------------------------------------------------------
# Market data snapshot (minimal)
# ---------------------------------------------------------------------------
@dataclass
class MarketDataSnapshot:
    """Minimal market data needed for fill simulation."""
    symbol: str = ""
    name: str = ""
    date: str = ""
    time: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    pre_close: float = 0.0
    volume: float = 0.0           # today's volume so far
    amount: float = 0.0           # today's turnover so far
    avg_volume_20d: float = 0.0    # 20-day average volume
    volatility_20d: float = 0.0    # 20-day daily return volatility
    limit_up: float = 0.0         # 涨停价
    limit_down: float = 0.0       # 跌停价
    status: str = MarketDataStatus.AVAILABLE.value
    source: str = ""               # Data source lineage
    timestamp: str = ""

    def is_tradable(self) -> tuple:
        """Check if the stock is tradable (not limit up/down, data available).

        Returns (tradable: bool, reason: str).
        """
        if self.status != MarketDataStatus.AVAILABLE.value:
            return False, f"Market data status: {self.status}"
        if self.limit_up > 0 and self.close >= self.limit_up:
            return False, "Limit up — cannot buy"
        if self.limit_down > 0 and self.close <= self.limit_down:
            return False, "Limit down — cannot sell"
        return True, ""


# ---------------------------------------------------------------------------
# Fill engine
# ---------------------------------------------------------------------------
class FillEngine:
    """Simulates order fills using market data and slippage models.

    The engine does NOT place real orders — it simulates what WOULD
    happen if an order were executed under current market conditions.
    """

    def __init__(self, slippage_config: Optional[SlippageConfig] = None):
        self.slippage_config = slippage_config or SlippageConfig()
        self.fill_history: list = []
        self.rejected_orders: list = []

    def compute_slippage(self, order_price: float, shares: int,
                         market: Optional[MarketDataSnapshot] = None,
                         model: str = "") -> tuple:
        """Compute slippage for an order.

        Args:
            order_price: the reference price
            shares: order quantity
            market: current market data snapshot
            model: override slippage model

        Returns:
            (slippage_per_share, model_used, metadata_dict)
        """
        model = model or self.slippage_config.model
        slip_per_share = 0.0
        meta = {"model": model}

        if model == SlippageModel.NONE.value:
            return 0.0, model, meta

        if model == SlippageModel.FIXED_PCT.value:
            slip_per_share = order_price * self.slippage_config.fixed_pct
            meta["pct"] = self.slippage_config.fixed_pct

        elif model == SlippageModel.VOLUME_BASED.value:
            if market and market.avg_volume_20d > 0:
                order_ratio = shares / market.avg_volume_20d
                # Larger orders cause more slippage
                slip_pct = min(order_ratio * self.slippage_config.volume_basis,
                               self.slippage_config.max_slippage_pct)
                slip_per_share = order_price * slip_pct
                meta["order_ratio"] = order_ratio
                meta["slip_pct"] = slip_pct
            else:
                # Fall back to fixed pct if no volume data
                slip_per_share = order_price * self.slippage_config.fixed_pct
                meta["fallback"] = "no_volume_data"
                meta["slip_pct"] = self.slippage_config.fixed_pct

        elif model == SlippageModel.VOLATILITY_BASED.value:
            if market and market.volatility_20d > 0:
                vol_factor = min(market.volatility_20d * self.slippage_config.volatility_scalar,
                                 self.slippage_config.max_slippage_pct)
                slip_per_share = order_price * vol_factor
                meta["volatility_20d"] = market.volatility_20d
                meta["vol_factor"] = vol_factor
            else:
                slip_per_share = order_price * self.slippage_config.fixed_pct
                meta["fallback"] = "no_volatility_data"
                meta["slip_pct"] = self.slippage_config.fixed_pct

        elif model == SlippageModel.HYBRID.value:
            # Combine volume and volatility effects
            vol_slip = 0.0
            vola_slip = 0.0
            if market and market.avg_volume_20d > 0:
                order_ratio = shares / market.avg_volume_20d
                vol_slip = min(order_ratio * self.slippage_config.volume_basis,
                               self.slippage_config.max_slippage_pct)
                meta["order_ratio"] = order_ratio
            if market and market.volatility_20d > 0:
                vola_slip = min(market.volatility_20d * self.slippage_config.volatility_scalar,
                                self.slippage_config.max_slippage_pct)
                meta["volatility_20d"] = market.volatility_20d
            combined_pct = min(vol_slip + vola_slip, self.slippage_config.max_slippage_pct)
            slip_per_share = order_price * combined_pct
            meta["combined_pct"] = combined_pct

        # Clamp to min/max
        slip_per_share = max(slip_per_share, self.slippage_config.min_slippage)
        slip_per_share = min(slip_per_share, self.slippage_config.max_slippage)
        slip_per_share = round(slip_per_share, 4)
        meta["slippage_per_share"] = slip_per_share

        return slip_per_share, model, meta

    def execute_fill(self, order_side: str, order_quantity: int,
                     order_price: float, symbol: str = "",
                     market: Optional[MarketDataSnapshot] = None,
                     order_type: str = "market",
                     limit_price: float = 0.0,
                     name: str = "") -> dict:
        """Simulate a single fill execution.

        Args:
            order_side: 'buy' or 'sell'
            order_quantity: number of shares
            order_price: reference/indicated price
            symbol: stock symbol (for reporting)
            market: current market data snapshot
            order_type: 'market', 'limit', etc.
            limit_price: for limit orders
            name: stock name

        Returns:
            dict with fill results (success, fills, rejection info)
        """
        # 1. Check market data availability
        if market is None:
            return self._reject_result(
                symbol, order_side, order_quantity, order_price,
                "market_data_missing", "No market data provided",
            )

        if market.status != MarketDataStatus.AVAILABLE.value:
            return self._reject_result(
                symbol, order_side, order_quantity, order_price,
                f"market_data_{market.status}", f"Market data status: {market.status}",
            )

        # 2. Check tradability
        tradable, reason = market.is_tradable()
        if not tradable and order_type == "market":
            return self._reject_result(
                symbol, order_side, order_quantity, order_price,
                "not_tradable", reason,
            )

        # 3. Determine fill price
        base_price = market.close
        if order_side == "buy":
            # Buy at ask side — higher of close or indicated
            base_price = max(base_price, order_price) if order_price > 0 else base_price
        else:
            # Sell at bid side — lower of close or indicated
            base_price = min(base_price, order_price) if order_price > 0 else base_price

        # 4. Check limit price constraint
        if order_type == "limit" and limit_price > 0:
            if order_side == "buy" and base_price > limit_price:
                return self._reject_result(
                    symbol, order_side, order_quantity, order_price,
                    "price_limit_exceeded",
                    f"Buy limit ¥{limit_price:.2f} < fill price ¥{base_price:.2f}",
                )
            if order_side == "sell" and base_price < limit_price:
                return self._reject_result(
                    symbol, order_side, order_quantity, order_price,
                    "price_limit_exceeded",
                    f"Sell limit ¥{limit_price:.2f} > fill price ¥{base_price:.2f}",
                )

        # 5. Compute slippage
        slippage_per_share, model_used, slip_meta = self.compute_slippage(
            base_price, order_quantity, market
        )

        # 6. Compute fill price (post-slippage)
        if order_side == "buy":
            fill_price = round(base_price + slippage_per_share, 2)
        else:
            fill_price = round(base_price - slippage_per_share, 2)

        fill_price = max(fill_price, 0.01)  # Minimum price

        # 7. Determine fill strategy
        fills = []
        fill_strategy = self.slippage_config.fill_strategy

        if fill_strategy == FillStrategy.IMMEDIATE.value:
            fills.append(self._make_fill(
                order_side, fill_price, order_quantity, slippage_per_share,
                symbol, name, fill_strategy,
            ))

        elif fill_strategy == FillStrategy.PARTIAL.value:
            chunks = self.slippage_config.partial_fill_chunks
            base_chunk = order_quantity // chunks
            remainder = order_quantity % chunks
            for i in range(chunks):
                chunk_shares = base_chunk + (1 if i < remainder else 0)
                if chunk_shares == 0:
                    continue
                # Later chunks may have more slippage (market impact)
                chunk_slip = slippage_per_share * (1 + i * 0.2)
                chunk_price = (fill_price + chunk_slip) if order_side == "buy" else (fill_price - chunk_slip)
                chunk_price = max(chunk_price, 0.01)
                fills.append(self._make_fill(
                    order_side, round(chunk_price, 2), chunk_shares,
                    round(chunk_slip, 4), symbol, name, fill_strategy,
                ))

        elif fill_strategy == FillStrategy.REJECT_ON_LIMIT.value:
            fills.append(self._make_fill(
                order_side, fill_price, order_quantity, slippage_per_share,
                symbol, name, fill_strategy,
            ))

        # 8. Record and return
        result = {
            "success": True,
            "symbol": symbol,
            "side": order_side,
            "total_quantity": order_quantity,
            "fills": fills,
            "base_price": base_price,
            "slippage_per_share": slippage_per_share,
            "slippage_model": model_used,
            "slippage_metadata": slip_meta,
            "fill_strategy": fill_strategy,
            "market_data_source": market.source,
            "market_data_date": market.date,
            "filled_at": datetime.now(CST).isoformat(),
        }
        self.fill_history.append(result)
        return result

    def _make_fill(self, side: str, price: float, shares: int,
                   slippage: float, symbol: str, name: str,
                   strategy: str) -> dict:
        """Create a fill event dict."""
        commission = self._calc_commission(price, shares)
        tax = self._calc_tax(side, price, shares)
        return {
            "symbol": symbol,
            "name": name,
            "side": side,
            "shares": shares,
            "price": price,
            "slippage": slippage,
            "commission": commission,
            "tax": tax,
            "fill_strategy": strategy,
            "amount": round(shares * price, 2),
        }

    def _calc_commission(self, price: float, shares: int) -> float:
        """Calculate commission (approximate A-share: 0.025% min ¥5)."""
        commission = round(price * shares * 0.00025, 2)
        return max(commission, 5.0)

    def _calc_tax(self, side: str, price: float, shares: int) -> float:
        """Calculate stamp tax (A-share: 0.05% on sell only)."""
        if side == "sell":
            return round(price * shares * 0.0005, 2)
        return 0.0

    def _reject_result(self, symbol: str, side: str, quantity: int,
                       price: float, reason: str, detail: str) -> dict:
        """Create a rejection result dict."""
        result = {
            "success": False,
            "symbol": symbol,
            "side": side,
            "total_quantity": quantity,
            "fills": [],
            "reject_reason": reason,
            "reject_detail": detail,
            "filled_at": datetime.now(CST).isoformat(),
        }
        self.rejected_orders.append(result)
        self.fill_history.append(result)
        return result

    def compute_commission(self, price: float, shares: int) -> float:
        """Public method to compute commission."""
        return self._calc_commission(price, shares)

    def compute_tax(self, side: str, price: float, shares: int) -> float:
        """Public method to compute stamp tax."""
        return self._calc_tax(side, price, shares)

    def get_summary(self) -> dict:
        """Get engine activity summary."""
        successful = [f for f in self.fill_history if f.get("success")]
        rejected = [f for f in self.fill_history if not f.get("success")]
        total_fills = sum(len(f.get("fills", [])) for f in successful)
        return {
            "total_attempts": len(self.fill_history),
            "successful_fills": len(successful),
            "rejected": len(rejected),
            "total_fill_events": total_fills,
            "slippage_model": self.slippage_config.model,
        }

    def reset(self):
        """Reset fill history (for test clean-up)."""
        self.fill_history.clear()
        self.rejected_orders.clear()
