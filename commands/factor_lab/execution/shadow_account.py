"""V4.1 Shadow Live Pipeline — Shadow Account

Simulated account that tracks cash, positions, and PnL as if
real trades were executed. No real money, no real broker interaction.

Key invariants:
  - Cash + position_market_value = total_equity
  - total_equity - total_cost_basis = total_pnl
  - All operations are idempotent (replaying same orders produces same state)
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Account status
# ---------------------------------------------------------------------------
class AccountStatus(Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Shadow position
# ---------------------------------------------------------------------------
@dataclass
class ShadowPosition:
    """A single stock position in the shadow account."""
    symbol: str = ""
    name: str = ""
    shares: int = 0
    avg_cost: float = 0.0          # weighted average entry cost
    current_price: float = 0.0     # latest market price
    market_value: float = 0.0
    cost_basis: float = 0.0        # total cost = shares * avg_cost
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0      # cumulative realized PnL from closed portions
    pnl_pct: float = 0.0
    day_change: float = 0.0        # daily change in market_value
    day_change_pct: float = 0.0
    updated_at: str = ""

    def recalc(self):
        """Recalculate derived fields after price or quantity change."""
        self.cost_basis = round(self.shares * self.avg_cost, 2)
        self.market_value = round(self.shares * self.current_price, 2)
        self.unrealized_pnl = round(self.market_value - self.cost_basis, 2)
        if self.cost_basis > 0:
            self.pnl_pct = round(self.unrealized_pnl / self.cost_basis * 100, 4)
        else:
            self.pnl_pct = 0.0
        self.updated_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Shadow account
# ---------------------------------------------------------------------------
_DEFAULT_INITIAL_CASH = 1_000_000.0  # ¥1M initial capital

@dataclass
class ShadowAccount:
    """Simulated trading account for shadow pipeline.

    Tracks cash balance, positions, and daily PnL.
    No real money is involved — sandbox only.
    """
    account_id: str = ""
    initial_cash: float = _DEFAULT_INITIAL_CASH
    cash: float = _DEFAULT_INITIAL_CASH
    positions: dict = field(default_factory=dict)         # symbol -> ShadowPosition
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_commission: float = 0.0
    total_tax: float = 0.0
    total_slippage_cost: float = 0.0
    status: str = AccountStatus.ACTIVE.value
    created_at: str = ""
    updated_at: str = ""
    trade_count: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.account_id:
            self.account_id = f"shadow_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        # Ensure cash starts equal to initial_cash on fresh creation
        # (the load() classmethod will override this after construction)
        if self.cash == _DEFAULT_INITIAL_CASH and self.initial_cash != _DEFAULT_INITIAL_CASH:
            self.cash = self.initial_cash

    # -- Property helpers ------------------------------------------------

    @property
    def position_count(self) -> int:
        """Number of positions with shares > 0."""
        return sum(1 for p in self.positions.values() if p.shares > 0)

    @property
    def total_market_value(self) -> float:
        return round(sum(
            p.market_value for p in self.positions.values()
        ), 2)

    @property
    def total_cost_basis(self) -> float:
        return round(sum(
            p.cost_basis for p in self.positions.values()
        ), 2)

    @property
    def total_equity(self) -> float:
        """Total account equity = cash + market value of all positions."""
        return round(self.cash + self.total_market_value, 2)

    @property
    def total_pnl(self) -> float:
        return round(self.total_realized_pnl + self.total_unrealized_pnl, 2)

    @property
    def total_pnl_pct(self) -> float:
        """Return on initial capital."""
        if self.initial_cash > 0:
            return round(self.total_pnl / self.initial_cash * 100, 4)
        return 0.0

    @property
    def cash_ratio(self) -> float:
        """Cash as a fraction of total equity."""
        if self.total_equity > 0:
            return round(self.cash / self.total_equity, 4)
        return 1.0

    @property
    def exposure(self) -> float:
        """Market value as fraction of total equity."""
        if self.total_equity > 0:
            return round(self.total_market_value / self.total_equity, 4)
        return 0.0

    # -- Core operations ------------------------------------------------

    def get_position(self, symbol: str) -> Optional[ShadowPosition]:
        """Get current position for a symbol, or None if no position exists."""
        pos = self.positions.get(symbol)
        if pos and pos.shares > 0:
            return pos
        return None

    def _ensure_position(self, symbol: str, name: str = "") -> ShadowPosition:
        """Get or create a position entry."""
        if symbol not in self.positions:
            self.positions[symbol] = ShadowPosition(symbol=symbol, name=name)
        if name and not self.positions[symbol].name:
            self.positions[symbol].name = name
        return self.positions[symbol]

    def apply_buy(self, symbol: str, shares: int, price: float,
                  name: str = "", commission: float = 0.0,
                  tax: float = 0.0, slippage: float = 0.0) -> dict:
        """Execute a shadow buy (fill price inclusive of slippage).

        Returns a dict with execution details, or error dict on failure.
        """
        if self.status != AccountStatus.ACTIVE.value:
            return {"success": False, "error": f"Account status is '{self.status}'"}

        if shares <= 0:
            return {"success": False, "error": f"Invalid shares: {shares}"}

        effective_price = price + slippage  # slippage increases buy cost
        total_cost = round(shares * effective_price + commission + tax, 2)

        if total_cost > self.cash:
            return {
                "success": False,
                "error": f"Insufficient cash: need ¥{total_cost:.2f}, have ¥{self.cash:.2f}",
                "required": total_cost,
                "available": self.cash,
            }

        # Update position
        pos = self._ensure_position(symbol, name)
        # Weighted average cost
        old_cost = pos.avg_cost * pos.shares
        new_cost = effective_price * shares
        total_shares = pos.shares + shares
        pos.avg_cost = round((old_cost + new_cost) / total_shares, 4) if total_shares > 0 else 0.0
        pos.shares = total_shares
        pos.current_price = effective_price  # mark at fill price
        pos.recalc()

        # Update account
        self.cash = round(self.cash - total_cost, 2)
        self.total_commission = round(self.total_commission + commission, 2)
        self.total_tax = round(self.total_tax + tax, 2)
        self.total_slippage_cost = round(self.total_slippage_cost + slippage * shares, 2)
        self.trade_count += 1
        self.updated_at = datetime.now(CST).isoformat()

        return {
            "success": True,
            "action": "buy",
            "symbol": symbol,
            "shares": shares,
            "price": effective_price,
            "commission": commission,
            "tax": tax,
            "slippage": slippage,
            "total_cost": total_cost,
            "cash_after": self.cash,
        }

    def apply_sell(self, symbol: str, shares: int, price: float,
                   name: str = "", commission: float = 0.0,
                   tax: float = 0.0, slippage: float = 0.0) -> dict:
        """Execute a shadow sell (fill price inclusive of slippage).

        Returns a dict with execution details, or error dict on failure.
        """
        if self.status != AccountStatus.ACTIVE.value:
            return {"success": False, "error": f"Account status is '{self.status}'"}

        if shares <= 0:
            return {"success": False, "error": f"Invalid shares: {shares}"}

        pos = self.get_position(symbol)
        if not pos:
            return {"success": False, "error": f"No position for {symbol}"}

        sell_shares = min(shares, pos.shares)
        if sell_shares < shares:
            # Partial fill at position limit
            pass

        effective_price = price - slippage  # slippage reduces sell proceeds
        proceeds = round(sell_shares * effective_price - commission - tax, 2)

        # Update position
        if sell_shares >= pos.shares:
            # Fully closed — realize all remaining PnL
            realized = round(
                (effective_price - pos.avg_cost) * pos.shares - commission - tax,
                2
            )
            pos.realized_pnl = round(pos.realized_pnl + realized, 2)
            self.total_realized_pnl = round(self.total_realized_pnl + realized, 2)
            pos.shares = 0
            pos.avg_cost = 0.0
            pos.current_price = effective_price
            pos.recalc()
        else:
            # Partial close
            realized = round(
                (effective_price - pos.avg_cost) * sell_shares - commission - tax,
                2
            )
            pos.realized_pnl = round(pos.realized_pnl + realized, 2)
            pos.shares -= sell_shares
            pos.current_price = effective_price
            pos.recalc()
            self.total_realized_pnl = round(self.total_realized_pnl + realized, 2)

        # Update account cash
        self.cash = round(self.cash + proceeds, 2)
        self.total_commission = round(self.total_commission + commission, 2)
        self.total_tax = round(self.total_tax + tax, 2)
        self.total_slippage_cost = round(self.total_slippage_cost + slippage * sell_shares, 2)
        self.trade_count += 1
        self.updated_at = datetime.now(CST).isoformat()

        return {
            "success": True,
            "action": "sell",
            "symbol": symbol,
            "shares": sell_shares,
            "price": effective_price,
            "commission": commission,
            "tax": tax,
            "slippage": slippage,
            "proceeds": proceeds,
            "realized_pnl": realized,
            "cash_after": self.cash,
        }

    def mark_to_market(self, prices: dict) -> dict:
        """Update all positions with current market prices.

        Args:
            prices: dict of symbol -> current_price

        Returns:
            dict with summary of mark changes
        """
        total_unrealized_before = self.total_unrealized_pnl
        n_updated = 0

        for symbol, price in prices.items():
            pos = self.positions.get(symbol)
            if pos and pos.shares > 0:
                pos.current_price = price
                pos.recalc()
                n_updated += 1

        self._recalc_unrealized()
        self.updated_at = datetime.now(CST).isoformat()

        return {
            "success": True,
            "n_updated": n_updated,
            "total_unrealized_pnl_before": total_unrealized_before,
            "total_unrealized_pnl_after": self.total_unrealized_pnl,
            "change": round(self.total_unrealized_pnl - total_unrealized_before, 2),
        }

    def _recalc_unrealized(self):
        """Recalculate total unrealized PnL from all positions."""
        self.total_unrealized_pnl = round(sum(
            p.unrealized_pnl for p in self.positions.values()
        ), 2)

    def freeze(self) -> dict:
        """Freeze the account — no further trades allowed."""
        self.status = AccountStatus.FROZEN.value
        self.updated_at = datetime.now(CST).isoformat()
        return {"success": True, "status": self.status}

    def reset(self, initial_cash: float = _DEFAULT_INITIAL_CASH):
        """Reset account to initial state."""
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions.clear()
        self.total_realized_pnl = 0.0
        self.total_unrealized_pnl = 0.0
        self.total_commission = 0.0
        self.total_tax = 0.0
        self.total_slippage_cost = 0.0
        self.status = AccountStatus.ACTIVE.value
        self.trade_count = 0
        self.updated_at = datetime.now(CST).isoformat()

    # -- Reporting -------------------------------------------------------

    def summary(self) -> dict:
        """Produce a concise account summary."""
        return {
            "account_id": self.account_id,
            "status": self.status,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "total_market_value": self.total_market_value,
            "total_equity": self.total_equity,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "total_realized_pnl": self.total_realized_pnl,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "total_commission": self.total_commission,
            "total_tax": self.total_tax,
            "total_slippage_cost": self.total_slippage_cost,
            "position_count": self.position_count,
            "trade_count": self.trade_count,
            "cash_ratio": self.cash_ratio,
            "exposure": self.exposure,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def positions_summary(self) -> list:
        """List all active positions."""
        return [
            p.to_dict() for p in self.positions.values() if p.shares > 0
        ]

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "positions": self.positions_summary(),
        }

    def save(self, output_dir: str, name: str = "shadow_account.json"):
        """Persist account state to a JSON file."""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, path: str) -> "ShadowAccount":
        """Load account state from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        positions = {}
        for p_data in data.pop("positions", []):
            pos = ShadowPosition(**p_data)
            positions[pos.symbol] = pos
        return cls(positions=positions, **{
            k: v for k, v in data.items()
            if k in ("account_id", "initial_cash", "cash", "total_realized_pnl",
                     "total_unrealized_pnl", "total_commission", "total_tax",
                     "total_slippage_cost", "status", "created_at", "updated_at",
                     "trade_count", "metadata")
        })
