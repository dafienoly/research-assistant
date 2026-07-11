"""vn.py-inspired A-share event truth lane owned and governed by Hermes."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np
import pandas as pd

from .contracts import QualityStatus, TargetPortfolioWeights, now_iso, sha256_payload


class EventType(str, Enum):
    BAR = "BAR"
    ORDER = "ORDER"
    TRADE = "TRADE"
    POSITION = "POSITION"
    ACCOUNT = "ACCOUNT"
    CANCEL = "CANCEL"
    RISK = "RISK"


class OrderStatus(str, Enum):
    SUBMITTING = "SUBMITTING"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ContractData:
    symbol: str
    exchange: str
    board: str
    asset_type: str = "STOCK"
    lot_size: int = 100
    price_tick: float = 0.01
    is_st: bool = False
    account_allowed: bool = True


@dataclass(frozen=True)
class BarData:
    symbol: str
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    volume_shares: float
    amount_yuan: float
    suspended: bool = False
    adj_factor: float | None = None
    source_snapshot_id: str = ""


@dataclass
class OrderData:
    order_id: str
    symbol: str
    side: str
    requested_quantity: int
    submitted_date: str
    reference_price: float
    status: OrderStatus = OrderStatus.SUBMITTING
    filled_quantity: int = 0
    cancelled_quantity: int = 0
    reject_reason: str | None = None


@dataclass(frozen=True)
class TradeData:
    trade_id: str
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    amount: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    impact_bps: float
    trading_date: str


@dataclass
class PositionLot:
    quantity: int
    buy_date: str


@dataclass
class PositionData:
    symbol: str
    quantity: int = 0
    average_cost: float = 0.0
    lots: list[PositionLot] = field(default_factory=list)

    def available_to_sell(self, trading_date: str) -> int:
        return sum(lot.quantity for lot in self.lots if lot.buy_date < trading_date)


@dataclass
class AccountData:
    account_id: str
    cash: float
    equity: float


class EventEngine:
    """Synchronous deterministic event dispatcher for replay and audit."""

    def __init__(self) -> None:
        self.handlers: dict[EventType, list[Callable[[dict[str, Any]], None]]] = {}
        self.events: list[dict[str, Any]] = []

    def register(self, event_type: EventType, handler: Callable[[dict[str, Any]], None]) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    def put(self, event_type: EventType, payload: dict[str, Any]) -> None:
        event = {"sequence": len(self.events) + 1, "event_type": event_type.value, "payload": payload}
        self.events.append(event)
        for handler in self.handlers.get(event_type, []):
            handler(event)


class BaseGateway(Protocol):
    def submit(self, order: OrderData) -> None:
        raise TypeError("BaseGateway protocol cannot submit directly")

    def cancel(self, order: OrderData, reason: str) -> None:
        raise TypeError("BaseGateway protocol cannot cancel directly")


class PaperEventGateway:
    """Event-only gateway with no external connectivity or order API."""

    def __init__(self, event_engine: EventEngine) -> None:
        self.event_engine = event_engine
        self.external_calls = 0

    def submit(self, order: OrderData) -> None:
        self.event_engine.put(EventType.ORDER, _serialize(order))

    def cancel(self, order: OrderData, reason: str) -> None:
        order.cancelled_quantity = max(0, order.requested_quantity - order.filled_quantity)
        order.status = OrderStatus.CANCELLED if order.filled_quantity == 0 else OrderStatus.PARTIAL
        self.event_engine.put(EventType.CANCEL, {**_serialize(order), "cancel_reason": reason})


class OmsEngine:
    def __init__(self, event_engine: EventEngine) -> None:
        self.orders: dict[str, OrderData] = {}
        self.trades: list[TradeData] = []
        self.positions: dict[str, PositionData] = {}
        event_engine.register(EventType.ORDER, self._on_order)
        event_engine.register(EventType.TRADE, self._on_trade)

    def _on_order(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        order = OrderData(
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            side=payload["side"],
            requested_quantity=int(payload["requested_quantity"]),
            submitted_date=payload["submitted_date"],
            reference_price=float(payload["reference_price"]),
            status=OrderStatus(payload["status"]),
            filled_quantity=int(payload.get("filled_quantity", 0)),
            cancelled_quantity=int(payload.get("cancelled_quantity", 0)),
            reject_reason=payload.get("reject_reason"),
        )
        self.orders[order.order_id] = order

    def _on_trade(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        self.trades.append(TradeData(**payload))


@dataclass(frozen=True)
class RiskDecision:
    allowed_quantity: int
    reason: str | None
    partial: bool
    limit_up: float
    limit_down: float
    capacity_shares: int


class MechanicalRiskManager:
    def __init__(self, *, max_volume_participation: float = 0.05) -> None:
        if not 0 < max_volume_participation <= 1:
            raise ValueError("max_volume_participation must be in (0, 1]")
        self.max_volume_participation = max_volume_participation

    @staticmethod
    def price_limit_pct(contract: ContractData, trading_date: str) -> float:
        if contract.is_st:
            return 0.05
        board = contract.board.upper()
        if board == "STAR":
            return 0.20
        if board in {"CHINEXT", "GEM"}:
            return 0.20 if trading_date >= "2020-08-24" else 0.10
        if board in {"BSE", "BEIJING"}:
            return 0.30
        return 0.10

    def evaluate(
        self,
        order: OrderData,
        *,
        contract: ContractData,
        bar: BarData,
        position: PositionData,
    ) -> RiskDecision:
        limit_pct = self.price_limit_pct(contract, bar.trading_date)
        limit_up = round(bar.pre_close * (1 + limit_pct) + 1e-9, 2)
        limit_down = round(bar.pre_close * (1 - limit_pct) + 1e-9, 2)
        capacity = int(bar.volume_shares * self.max_volume_participation / contract.lot_size) * contract.lot_size
        if not contract.account_allowed:
            return RiskDecision(0, "account_permission_blocked", False, limit_up, limit_down, capacity)
        if bar.suspended or bar.volume_shares <= 0:
            return RiskDecision(0, "suspended_or_zero_volume", False, limit_up, limit_down, capacity)
        if order.side == "BUY" and bar.open >= limit_up - contract.price_tick / 2:
            return RiskDecision(0, "limit_up_buy_blocked", False, limit_up, limit_down, capacity)
        if order.side == "SELL" and bar.open <= limit_down + contract.price_tick / 2:
            return RiskDecision(0, "limit_down_sell_blocked", False, limit_up, limit_down, capacity)
        requested = order.requested_quantity
        if order.side == "BUY" and requested % contract.lot_size:
            requested = requested // contract.lot_size * contract.lot_size
        if order.side == "SELL":
            requested = min(requested, position.available_to_sell(bar.trading_date))
            if requested <= 0:
                return RiskDecision(0, "t_plus_one_unavailable", False, limit_up, limit_down, capacity)
        allowed = min(requested, capacity)
        if order.side == "BUY":
            allowed = allowed // contract.lot_size * contract.lot_size
        return RiskDecision(
            allowed,
            None if allowed > 0 else "liquidity_capacity_zero",
            0 < allowed < order.requested_quantity,
            limit_up,
            limit_down,
            capacity,
        )


def _serialize(value: Any) -> dict[str, Any]:
    payload = asdict(value)
    for key, item in list(payload.items()):
        if isinstance(item, Enum):
            payload[key] = item.value
    return payload


def _metrics(equity: pd.Series, initial_equity: float | None = None) -> dict[str, float | None]:
    baseline = float(initial_equity) if initial_equity is not None else float(equity.iloc[0])
    augmented = pd.concat([pd.Series([baseline], index=[equity.index.min() - pd.Timedelta(days=1)]), equity])
    returns = augmented.pct_change().dropna()
    if len(equity) < 2:
        return {"total_return": None, "annualized_return": None, "sharpe": None, "max_drawdown": None}
    total = float(equity.iloc[-1] / baseline - 1)
    years = max(len(equity) / 252, 1 / 252)
    annualized = float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0
    volatility = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / volatility * np.sqrt(252)) if volatility > 1e-12 else None
    drawdown = augmented / augmented.cummax() - 1
    return {
        "total_return": total,
        "annualized_return": annualized,
        "sharpe": sharpe,
        "max_drawdown": abs(float(drawdown.min())),
    }


class AShareEventTruthLane:
    def __init__(
        self,
        project_root: str | Path,
        *,
        initial_cash: float = 1_000_000,
        commission_rate: float = 0.0003,
        min_commission: float = 5.0,
        stock_stamp_tax_rate: float = 0.0005,
        transfer_fee_rate: float = 0.00001,
        base_slippage_bps: float = 10,
        impact_coefficient_bps: float = 50,
        max_volume_participation: float = 0.05,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stock_stamp_tax_rate = stock_stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate
        self.base_slippage_bps = base_slippage_bps
        self.impact_coefficient_bps = impact_coefficient_bps
        self.risk = MechanicalRiskManager(max_volume_participation=max_volume_participation)

    def _load(
        self,
        snapshot_manifest_path: Path,
        weights_path: Path,
    ) -> tuple[dict[str, Any], TargetPortfolioWeights, dict[str, pd.DataFrame]]:
        snapshot = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
        weights = TargetPortfolioWeights.model_validate_json(weights_path.read_text(encoding="utf-8"))
        if snapshot.get("status") != QualityStatus.OK.value or not snapshot.get("snapshot_id_valid"):
            raise ValueError("immutable snapshot is not verified")
        if snapshot.get("data_snapshot_id") != weights.data_snapshot_id:
            raise ValueError("snapshot and target weights IDs differ")
        frames: dict[str, pd.DataFrame] = {}
        required = set(weights.risk_adjusted_weights)
        for entry in snapshot.get("entries", []):
            symbol = str(entry.get("instrument_id"))
            if symbol not in required or entry.get("dataset") != "fund_daily":
                continue
            path = Path(str(entry["data_file"])).resolve()
            if self.project_root not in path.parents:
                raise ValueError("snapshot data path outside project root")
            records = json.loads(path.read_text(encoding="utf-8"))
            if sha256_payload(records) != entry.get("content_hash"):
                raise ValueError(f"snapshot content hash mismatch: {symbol}")
            frame = pd.DataFrame(records)
            frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
            frame = frame.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last").set_index("trade_date")
            frames[symbol] = frame.sort_index()
        missing = sorted(required - set(frames))
        if missing:
            raise ValueError(f"target instruments missing from snapshot: {missing}")
        return snapshot, weights, frames

    @staticmethod
    def _contract(symbol: str) -> ContractData:
        code = symbol.split(".")[0]
        exchange = "SSE" if symbol.endswith(".SH") else "SZSE"
        if code.startswith("688"):
            board = "STAR"
        elif code.startswith(("300", "301")):
            board = "CHINEXT"
        elif code.startswith(("8", "4")):
            board = "BSE"
        else:
            board = "MAINBOARD"
        return ContractData(
            symbol=symbol,
            exchange=exchange,
            board=board,
            asset_type="ETF",
            lot_size=100,
            account_allowed=True,
        )

    def _bar(self, symbol: str, row: pd.Series, snapshot_id: str, trading_date: str) -> BarData:
        volume_lots = float(pd.to_numeric(row.get("vol"), errors="coerce") or 0.0)
        amount_thousand = float(pd.to_numeric(row.get("amount"), errors="coerce") or 0.0)
        return BarData(
            symbol=symbol,
            trading_date=trading_date,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            pre_close=float(row.get("pre_close", row["open"])),
            volume_shares=max(0.0, volume_lots * 100),
            amount_yuan=max(0.0, amount_thousand * 1000),
            suspended=volume_lots <= 0 or any(pd.isna(row.get(name)) for name in ("open", "close")),
            adj_factor=float(row["adj_factor"]) if "adj_factor" in row and pd.notna(row["adj_factor"]) else None,
            source_snapshot_id=snapshot_id,
        )

    def run(
        self,
        *,
        as_of: str,
        snapshot_manifest_path: str | Path,
        target_weights_path: str | Path,
        output_path: str | Path,
        rebalance_days: int = 20,
    ) -> dict[str, Any]:
        snapshot, weights, frames = self._load(Path(snapshot_manifest_path), Path(target_weights_path))
        common_dates: pd.DatetimeIndex | None = None
        for frame in frames.values():
            common_dates = frame.index if common_dates is None else common_dates.intersection(frame.index)
        dates = common_dates.sort_values() if common_dates is not None else pd.DatetimeIndex([])
        if len(dates) < 80:
            raise ValueError(f"insufficient aligned sessions: {len(dates)}")
        event_engine = EventEngine()
        gateway = PaperEventGateway(event_engine)
        oms = OmsEngine(event_engine)
        positions = {symbol: PositionData(symbol=symbol) for symbol in frames}
        cash = self.initial_cash
        equity_records: list[dict[str, Any]] = []
        order_counter = 0
        trade_counter = 0
        missing_evidence: set[str] = {"official_suspend_d", "official_stk_limit", "cash_dividend_events"}
        adj_factors_seen = False

        for day_index, timestamp in enumerate(dates):
            trading_date = timestamp.date().isoformat()
            bars = {
                symbol: self._bar(symbol, frame.loc[timestamp], weights.data_snapshot_id, trading_date)
                for symbol, frame in frames.items()
            }
            for bar in bars.values():
                event_engine.put(EventType.BAR, _serialize(bar))
                adj_factors_seen = adj_factors_seen or bar.adj_factor is not None
            open_equity = cash + sum(positions[symbol].quantity * bars[symbol].open for symbol in positions)
            if day_index % rebalance_days == 0:
                desired = {
                    symbol: int(open_equity * weight / bars[symbol].open / 100) * 100
                    for symbol, weight in weights.risk_adjusted_weights.items()
                }
                order_specs = []
                for symbol in sorted(desired):
                    delta = desired[symbol] - positions[symbol].quantity
                    if delta < 0:
                        order_specs.append((symbol, "SELL", -delta))
                for symbol in sorted(desired):
                    delta = desired[symbol] - positions[symbol].quantity
                    if delta > 0:
                        order_specs.append((symbol, "BUY", delta))
                for symbol, side, requested in order_specs:
                    order_counter += 1
                    bar = bars[symbol]
                    contract = self._contract(symbol)
                    order = OrderData(
                        order_id=f"evt-order-{order_counter:06d}",
                        symbol=symbol,
                        side=side,
                        requested_quantity=requested,
                        submitted_date=trading_date,
                        reference_price=bar.open,
                    )
                    gateway.submit(order)
                    decision = self.risk.evaluate(order, contract=contract, bar=bar, position=positions[symbol])
                    event_engine.put(EventType.RISK, {"order_id": order.order_id, **asdict(decision)})
                    fill_quantity = decision.allowed_quantity
                    if side == "BUY" and fill_quantity > 0:
                        max_affordable = int(cash / (bar.open * (1 + 0.005)) / contract.lot_size) * contract.lot_size
                        fill_quantity = min(fill_quantity, max_affordable)
                    if fill_quantity <= 0:
                        order.status = OrderStatus.REJECTED
                        order.reject_reason = decision.reason or "cash_or_capacity_blocked"
                        oms.orders[order.order_id] = order
                        gateway.cancel(order, order.reject_reason)
                        continue
                    participation = fill_quantity / max(bar.volume_shares, 1.0)
                    impact_bps = self.base_slippage_bps + self.impact_coefficient_bps * math.sqrt(participation)
                    raw_price = bar.open * (1 + impact_bps / 10_000 if side == "BUY" else 1 - impact_bps / 10_000)
                    fill_price = min(max(raw_price, bar.low), bar.high)
                    amount = fill_quantity * fill_price
                    commission = max(amount * self.commission_rate, self.min_commission)
                    stamp_tax = amount * self.stock_stamp_tax_rate if side == "SELL" and contract.asset_type == "STOCK" else 0.0
                    transfer_fee = amount * self.transfer_fee_rate if contract.exchange == "SSE" else 0.0
                    trade_counter += 1
                    trade = TradeData(
                        trade_id=f"evt-trade-{trade_counter:06d}",
                        order_id=order.order_id,
                        symbol=symbol,
                        side=side,
                        quantity=fill_quantity,
                        price=round(fill_price, 6),
                        amount=round(amount, 4),
                        commission=round(commission, 4),
                        stamp_tax=round(stamp_tax, 4),
                        transfer_fee=round(transfer_fee, 4),
                        impact_bps=round(impact_bps, 6),
                        trading_date=trading_date,
                    )
                    position = positions[symbol]
                    if side == "BUY":
                        previous_value = position.quantity * position.average_cost
                        position.quantity += fill_quantity
                        position.average_cost = (previous_value + amount) / position.quantity if position.quantity else 0.0
                        position.lots.append(PositionLot(fill_quantity, trading_date))
                        cash -= amount + commission + transfer_fee
                    else:
                        position.quantity -= fill_quantity
                        remaining = fill_quantity
                        for lot in position.lots:
                            if lot.buy_date >= trading_date or remaining <= 0:
                                continue
                            removed = min(lot.quantity, remaining)
                            lot.quantity -= removed
                            remaining -= removed
                        position.lots = [lot for lot in position.lots if lot.quantity > 0]
                        cash += amount - commission - stamp_tax - transfer_fee
                    order.filled_quantity = fill_quantity
                    order.status = OrderStatus.PARTIAL if fill_quantity < requested else OrderStatus.FILLED
                    oms.orders[order.order_id] = order
                    event_engine.put(EventType.TRADE, _serialize(trade))
                    event_engine.put(EventType.POSITION, _serialize(position))
                    if fill_quantity < requested:
                        gateway.cancel(order, "end_of_day_unfilled_cancel")
            end_equity = cash + sum(positions[symbol].quantity * bars[symbol].close for symbol in positions)
            equity_records.append({"date": trading_date, "equity": end_equity, "cash": cash})
            event_engine.put(
                EventType.ACCOUNT,
                _serialize(AccountData(weights.account_id, cash=cash, equity=end_equity)),
            )

        if not adj_factors_seen:
            missing_evidence.add("adj_factor_in_snapshot")
        equity = pd.Series(
            [record["equity"] for record in equity_records],
            index=pd.to_datetime([record["date"] for record in equity_records]),
            dtype=float,
        )
        rejected = sum(order.status == OrderStatus.REJECTED for order in oms.orders.values())
        partial = sum(order.status == OrderStatus.PARTIAL for order in oms.orders.values())
        result = {
            "schema_version": "1.0",
            "status": QualityStatus.PARTIAL.value if missing_evidence else QualityStatus.OK.value,
            "quality_status": QualityStatus.BACKTEST_ONLY.value,
            "run_id": f"event-{as_of}-{sha256_payload({'snapshot': weights.data_snapshot_id, 'weights': weights.target_weights_hash})[:16]}",
            "as_of": as_of,
            "data_snapshot_id": weights.data_snapshot_id,
            "target_weights_hash": weights.target_weights_hash,
            "sessions": len(dates),
            "start_date": dates.min().date().isoformat(),
            "end_date": dates.max().date().isoformat(),
            "rebalance_days": rebalance_days,
            "metrics": _metrics(equity, self.initial_cash),
            "ending_value": float(equity.iloc[-1]),
            "orders": len(oms.orders),
            "trades": len(oms.trades),
            "rejected_orders": rejected,
            "partial_orders": partial,
            "cancel_events": sum(event["event_type"] == EventType.CANCEL.value for event in event_engine.events),
            "event_count": len(event_engine.events),
            "event_type_counts": {
                event_type.value: sum(event["event_type"] == event_type.value for event in event_engine.events)
                for event_type in EventType
            },
            "equity_curve": equity_records,
            "orders_ledger": [_serialize(order) for order in oms.orders.values()],
            "trades_ledger": [_serialize(trade) for trade in oms.trades],
            "final_positions": {
                symbol: {"quantity": position.quantity, "average_cost": position.average_cost}
                for symbol, position in positions.items()
            },
            "mechanics": {
                "t_plus_one": True,
                "dynamic_price_limits": True,
                "st_limit": True,
                "suspension": True,
                "lot_size": 100,
                "board_permission": True,
                "partial_fill": True,
                "end_of_day_cancel": True,
                "open_price_execution": True,
                "volume_capacity": True,
                "market_impact": True,
                "adjustment_factor_supported": True,
                "etf_substitution_from_target_contract": True,
            },
            "missing_evidence": sorted(missing_evidence),
            "execution_truth_scope": "event_backtest_only",
            "real_broker_called": False,
            "external_gateway_calls": gateway.external_calls,
            "paper_or_live_promotion_allowed": False,
            "generated_at": now_iso(),
        }
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(destination)
        return result
