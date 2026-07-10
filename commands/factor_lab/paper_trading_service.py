"""Paper Trading Service — V7.7 纸面交易引擎

管理虚拟账户、持仓、订单簿和成交模拟。
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional
import uuid

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class PaperAccount:
    """虚拟账户"""
    account_id: str = "paper_default"
    cash: float = 1_000_000.0
    initial_cash: float = 1_000_000.0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "cash": round(self.cash, 2),
            "initial_cash": self.initial_cash,
            "total_value": round(self.total_value, 2),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 4),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def positions(self) -> dict:
        return _get_service()._positions

    @property
    def market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.market_value

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def realized_pnl(self) -> float:
        return sum(p.total_cost_basis for p in self.positions.values()) * -1

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.initial_cash

    @property
    def total_pnl_pct(self) -> float:
        if self.initial_cash == 0:
            return 0.0
        return (self.total_value - self.initial_cash) / self.initial_cash

    def record_update(self):
        self.updated_at = datetime.now(CST).isoformat()


@dataclass
class PaperPosition:
    """虚拟持仓"""
    symbol: str
    shares: int = 0
    avg_cost: float = 0.0
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    @property
    def total_cost_basis(self) -> float:
        return self.cost_basis

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.market_value - self.cost_basis) / self.cost_basis

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "shares": self.shares,
            "avg_cost": round(self.avg_cost, 4),
            "current_price": round(self.current_price, 4),
            "market_value": round(self.market_value, 2),
            "cost_basis": round(self.cost_basis, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 4),
        }


@dataclass
class PaperOrder:
    """模拟订单"""
    order_id: str = ""
    symbol: str = ""
    side: str = "buy"        # buy / sell
    order_type: str = "limit"  # limit / market
    price: float = 0.0
    quantity: int = 0
    filled_quantity: int = 0
    status: str = "pending"  # pending / filled / partial / canceled / rejected
    reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "price": round(self.price, 4),
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "remaining": self.remaining,
            "status": self.status,
            "reason": self.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class PaperFill:
    """模拟成交记录"""
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = "buy"
    fill_price: float = 0.0
    fill_quantity: int = 0
    fill_amount: float = 0.0
    fee: float = 0.0
    tax: float = 0.0
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "fill_price": round(self.fill_price, 4),
            "fill_quantity": self.fill_quantity,
            "fill_amount": round(self.fill_amount, 2),
            "fee": round(self.fee, 2),
            "tax": round(self.tax, 2),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 交易引擎
# ---------------------------------------------------------------------------

FEE_RATE = 0.0003      # 佣金费率
STAMP_RATE = 0.0005    # 印花税 (仅卖出)
SLIPPAGE_BPS = 5       # 滑点 (bps)


class PaperTradingService:
    """纸面交易引擎 — 管理虚拟账户、订单簿和成交模拟

    所有操作在内存中进行，不会产生真实交易。
    """

    def __init__(self, initial_cash: float = 1_000_000.0):
        now = datetime.now(CST).isoformat()
        self._account = PaperAccount(
            cash=initial_cash,
            initial_cash=initial_cash,
            created_at=now,
            updated_at=now,
        )
        self._positions: dict[str, PaperPosition] = {}
        self._orders: list[PaperOrder] = []
        self._fills: list[PaperFill] = []
        self._next_order_id = 1
        self._next_fill_id = 1

    # ── Account ──────────────────────────────────────────────────────

    def get_account(self) -> PaperAccount:
        """获取虚拟账户快照"""
        return self._account

    def get_balance(self) -> dict:
        """获取账户余额汇总"""
        return self._account.to_dict()

    # ── Positions ────────────────────────────────────────────────────

    def get_positions(self, symbol: str = "") -> list[dict]:
        """获取持仓列表。可指定 symbol 过滤。"""
        if symbol:
            pos = self._positions.get(symbol)
            return [pos.to_dict()] if pos else []
        return [p.to_dict() for p in self._positions.values() if p.shares > 0]

    def update_price(self, symbol: str, price: float):
        """更新持仓标的的最新价格 (用于计算未实现盈亏)"""
        if symbol in self._positions:
            self._positions[symbol].current_price = price

    # ── Orders ───────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "limit",
    ) -> dict:
        """下模拟订单

        返回订单 dict。同步尝试模拟成交。
        """
        side = side.lower()
        order_type = order_type.lower()

        # 校验
        if side not in ("buy", "sell"):
            return {"error": f"不支持的指令方向: {side}", "order_id": ""}
        if quantity <= 0:
            return {"error": "数量必须大于 0", "order_id": ""}
        if order_type not in ("limit", "market"):
            return {"error": f"不支持的订单类型: {order_type}", "order_id": ""}
        if price <= 0:
            return {"error": "价格必须大于 0", "order_id": ""}

        # 卖出检查
        if side == "sell":
            pos = self._positions.get(symbol)
            current_shares = pos.shares if pos else 0
            if quantity > current_shares:
                return {
                    "error": f"持仓不足: 持有 {current_shares} 股, 请求卖出 {quantity} 股",
                    "order_id": "",
                }

        # 检查可用资金 (仅限价买单)
        if side == "buy" and order_type == "limit":
            required = quantity * price * (1 + FEE_RATE)
            if required > self._account.cash:
                can_buy = int(self._account.cash / (price * (1 + FEE_RATE)) / 100) * 100
                if can_buy < 100:
                    return {"error": "现金不足", "order_id": ""}
                # 如果是 partial，调整数量
                quantity = can_buy

        now = datetime.now(CST).isoformat()
        order_id = f"paper_{self._next_order_id:04d}"
        self._next_order_id += 1

        order = PaperOrder(
            order_id=order_id,
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            created_at=now,
            updated_at=now,
        )

        # 尝试模拟成交
        self._try_fill(order)

        self._orders.append(order)
        self._account.record_update()
        return order.to_dict()

    def cancel_order(self, order_id: str) -> dict:
        """取消未成交订单"""
        for order in self._orders:
            if order.order_id == order_id:
                if order.status in ("filled", "canceled", "rejected"):
                    return {"error": f"订单状态为 {order.status}, 不可撤销"}
                order.status = "canceled"
                order.updated_at = datetime.now(CST).isoformat()
                self._account.record_update()
                return order.to_dict()
        return {"error": f"订单不存在: {order_id}"}

    def get_orders(
        self,
        status: str = "",
        symbol: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """获取订单列表"""
        result = []
        for o in self._orders:
            if status and o.status != status:
                continue
            if symbol and o.symbol != symbol.upper():
                continue
            result.append(o.to_dict())
        result.reverse()
        return result[:limit]

    def get_fills(
        self,
        symbol: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """获取成交记录"""
        result = []
        for f in self._fills:
            if symbol and f.symbol != symbol.upper():
                continue
            result.append(f.to_dict())
        result.reverse()
        return result[:limit]

    # ── Dashboard ────────────────────────────────────────────────────

    def get_dashboard(self) -> dict:
        """聚合 Paper Dashboard 数据 — 供 /api/paper/dashboard 端点"""
        try:
            import numpy as np
        except ImportError:
            np = None

        bal = self._account.to_dict()
        orders = self.get_orders(limit=500)
        fills = self.get_fills(limit=500)

        n_pending = sum(1 for o in orders if o.get("status") == "pending")
        n_completed = sum(1 for o in orders if o.get("status") in ("filled", "partial"))
        n_filled = len(fills)
        total_orders = len(orders) or 1
        fill_rate = round(n_filled / total_orders * 100, 1)

        total_pnl = bal.get("total_pnl", 0)
        initial_capital = bal.get("initial_cash", 1_000_000)
        total_return_pct = round((total_pnl / initial_capital) * 100, 2) if initial_capital else 0

        # 从成交记录提取 PnL 序列
        pnl_values = []
        for f in fills:
            pnl = f.get("pnl", 0) or 0
            pnl_values.append(pnl)

        sharpe = 0.0
        volatility = 0.0
        max_drawdown = 0.0
        win_rate = 0.0
        annualized_return = 0.0

        if np is not None and len(pnl_values) >= 5:
            arr = np.array(pnl_values, dtype=float)
            if arr.std() > 0:
                daily_returns = arr / initial_capital
                volatility = round(float(arr.std()) * 100, 2)
                sharpe = round(float(daily_returns.mean() / daily_returns.std() * np.sqrt(252)), 2) if daily_returns.std() > 0 else 0
                annualized_return = round(float(daily_returns.mean() * 252 * 100), 2)
                cum = np.cumprod(1 + daily_returns)
                peak = np.maximum.accumulate(cum)
                dd = (cum - peak) / peak
                max_drawdown = round(float(np.min(dd)) * 100, 2)
                wins = int((arr > 0).sum())
                win_rate = round(wins / len(arr) * 100, 1)

        n_trading_days = 1
        created = bal.get("created_at", "")
        if created:
            try:
                start = datetime.fromisoformat(created)
                n_trading_days = max(1, (datetime.now(CST) - start).days)
            except Exception:
                pass

        return {
            "period": f"近{n_trading_days}天",
            "n_trading_days": n_trading_days,
            "n_pending": n_pending,
            "n_completed": n_completed,
            "paper_total_return_pct": total_return_pct,
            "paper_annualized_return_pct": annualized_return,
            "paper_volatility_pct": volatility,
            "paper_sharpe": sharpe,
            "paper_max_drawdown_pct": max_drawdown,
            "paper_win_rate_pct": win_rate,
            "execution_quality": {
                "filled": n_filled,
                "partial_filled": n_completed - n_filled,
                "blocked": n_pending,
                "fill_rate": fill_rate,
            },
            "status": "active",
            "no_real_trade": n_filled == 0,
        }

    # ── 内部成交模拟 ─────────────────────────────────────────────────

    def _try_fill(self, order: PaperOrder):
        """尝试模拟成交

        限价单: 买单以 price 成交, 卖单以 price 成交
        市价单: 以当前价格成交
        """
        base_price = order.price

        if order.side == "buy":
            self._fill_buy(order, base_price)
        else:
            self._fill_sell(order, base_price)

    def _fill_buy(self, order: PaperOrder, fill_price: float):
        """模拟买入成交"""
        quantity = order.quantity
        amount = quantity * fill_price
        fee = round(amount * FEE_RATE, 2)
        total_cost = amount + fee

        if total_cost > self._account.cash:
            can_buy = int(self._account.cash / (fill_price * (1 + FEE_RATE)) / 100) * 100
            if can_buy < 100:
                order.status = "rejected"
                order.reason = "现金不足"
                order.updated_at = datetime.now(CST).isoformat()
                return
            quantity = can_buy

        amount = quantity * fill_price
        fee = round(amount * FEE_RATE, 2)
        total_cost = amount + fee

        # 扣现金
        self._account.cash -= total_cost

        # 更新持仓
        if order.symbol in self._positions:
            pos = self._positions[order.symbol]
            total_shares = pos.shares + quantity
            total_cost_basis = pos.cost_basis + (quantity * fill_price)
            pos.avg_cost = total_cost_basis / total_shares if total_shares > 0 else 0
            pos.shares = total_shares
            pos.current_price = fill_price
        else:
            self._positions[order.symbol] = PaperPosition(
                symbol=order.symbol,
                shares=quantity,
                avg_cost=fill_price,
                current_price=fill_price,
            )

        # 记录成交
        now = datetime.now(CST).isoformat()
        fill = PaperFill(
            fill_id=f"fill_{self._next_fill_id:04d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side="buy",
            fill_price=fill_price,
            fill_quantity=quantity,
            fill_amount=amount,
            fee=fee,
            tax=0.0,
            created_at=now,
        )
        self._next_fill_id += 1
        self._fills.append(fill)

        order.filled_quantity = quantity
        order.status = "filled" if quantity == order.quantity else "partial"
        order.updated_at = now

    def _fill_sell(self, order: PaperOrder, fill_price: float):
        """模拟卖出成交"""
        quantity = order.quantity

        pos = self._positions.get(order.symbol)
        current_shares = pos.shares if pos else 0
        if quantity > current_shares:
            quantity = current_shares
            if quantity <= 0:
                order.status = "rejected"
                order.reason = "无可卖持仓"
                order.updated_at = datetime.now(CST).isoformat()
                return

        amount = quantity * fill_price
        fee = round(amount * FEE_RATE, 2)
        tax = round(amount * STAMP_RATE, 2)
        net_amount = amount - fee - tax

        # 加现金
        self._account.cash += net_amount

        # 更新持仓
        if order.symbol in self._positions:
            pos = self._positions[order.symbol]
            pos.shares -= quantity
            pos.current_price = fill_price
            if pos.shares <= 0:
                del self._positions[order.symbol]

        # 记录成交
        now = datetime.now(CST).isoformat()
        fill = PaperFill(
            fill_id=f"fill_{self._next_fill_id:04d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side="sell",
            fill_price=fill_price,
            fill_quantity=quantity,
            fill_amount=amount,
            fee=fee,
            tax=tax,
            created_at=now,
        )
        self._next_fill_id += 1
        self._fills.append(fill)

        order.filled_quantity = quantity
        order.status = "filled" if quantity == order.quantity else "partial"
        order.updated_at = now

    # ── 重置 ─────────────────────────────────────────────────────────

    def reset(self, initial_cash: float = 1_000_000.0):
        """重置服务到初始状态"""
        now = datetime.now(CST).isoformat()
        self._account = PaperAccount(
            cash=initial_cash,
            initial_cash=initial_cash,
            created_at=now,
            updated_at=now,
        )
        self._positions.clear()
        self._orders.clear()
        self._fills.clear()
        self._next_order_id = 1
        self._next_fill_id = 1


# ---------------------------------------------------------------------------
# 单例管理
# ---------------------------------------------------------------------------

_service_instance: Optional[PaperTradingService] = None


def _get_service() -> PaperTradingService:
    """返回全局 PaperTradingService 单例（供测试 monkeypatch）"""
    global _service_instance
    if _service_instance is None:
        _service_instance = PaperTradingService()
    return _service_instance


def _reset_service():
    """重置单例（测试用）"""
    global _service_instance
    _service_instance = None
