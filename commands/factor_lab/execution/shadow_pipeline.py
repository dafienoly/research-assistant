"""V4.6 Shadow Live Pipeline — Shadow Pipeline Runner

Orchestrates the full shadow pipeline flow:
  1. Receive signal/proposal
  2. Create shadow orders
  3. **V4.6: Run trade filter checks** (price limit, board type, suspension, etc.)
  4. **V4.6: Run slippage estimation & budget control**
  5. Simulate fills with slippage
  6. Update shadow account
  7. Record in execution ledger
  8. Generate deviation reports

This is the central execution orchestrator for V4.1+V4.6.
All operations are sandbox-only — no real trades.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from factor_lab.execution.shadow_account import ShadowAccount, ShadowPosition
from factor_lab.execution.shadow_order import (
    ShadowOrder, ShadowOrderManager, OrderSide, OrderStatus,
    OrderType, FillEvent, RejectReason,
)
from factor_lab.execution.shadow_fill import (
    FillEngine, SlippageConfig, MarketDataSnapshot,
    SlippageModel, FillStrategy, MarketDataStatus,
)
from factor_lab.execution.shadow_ledger import (
    ShadowExecutionLedger, DeviationEntry,
)

# V4.6 Trade Filter & Slippage Control
from factor_lab.execution.trade_filter import (
    TradeFilterEngine, TradeFilterRule, TradeContext,
    FilterReport, FilterType,
)
from factor_lab.execution.slippage_control import (
    SlippageController, SlippageBudget, SlippageEstimator,
)

CST = timezone(timedelta(hours=8))


@dataclass
class ShadowPipelineConfig:
    """Configuration for the shadow pipeline runner.

    V4.6 additions:
      - enable_trade_filter: Enable V4.6 trade filter checks
      - trade_filter_rules: Custom trade filter rules (None = defaults)
      - enable_slippage_control: Enable V4.6 slippage budget/estimation
      - slippage_budget: SlippageBudget configuration
      - slippage_confidence_multiplier: Safety margin for slippage estimates
    """
    initial_cash: float = 1_000_000.0
    slippage_model: str = SlippageModel.FIXED_PCT.value
    slippage_pct: float = 0.001       # 0.1%
    fill_strategy: str = FillStrategy.IMMEDIATE.value
    commission_pct: float = 0.00025    # 0.025%
    stamp_tax_pct: float = 0.0005      # 0.05% (sell only)
    min_commission: float = 5.0
    output_dir: str = ""
    auto_generate_reports: bool = True
    no_live_trade: bool = True         # Safety flag — always True for shadow

    # V4.6 Trade Filter
    enable_trade_filter: bool = True
    trade_filter_rules: Optional[list] = None  # None = use defaults

    # V4.6 Slippage Control
    enable_slippage_control: bool = True
    slippage_budget: Optional[dict] = None    # None = use defaults
    slippage_confidence_multiplier: float = 1.0

    def to_dict(self) -> dict:
        d = asdict(self)
        # Skip complex fields in serialization
        d.pop("trade_filter_rules", None)
        d.pop("slippage_budget", None)
        return d


@dataclass
class ShadowPipelineResult:
    """Result of a shadow pipeline run.

    V4.6 additions:
      - filter_summary: Trade filter check summary
      - slippage_control_summary: Slippage control summary
      - filter_results: Per-trade filter reports
      - n_filter_blocked: Number of trades blocked by filters
      - n_slippage_blocked: Number of trades blocked by slippage budget
    """
    pipeline_id: str = ""
    run_id: str = ""
    version: str = "V4.6"
    status: str = "completed"  # completed, partial, failed
    config: dict = field(default_factory=dict)
    account_summary: dict = field(default_factory=dict)
    orders_summary: dict = field(default_factory=dict)
    fill_summary: dict = field(default_factory=dict)
    deviation_summary: dict = field(default_factory=dict)
    n_orders: int = 0
    n_filled: int = 0
    n_rejected: int = 0
    n_entries: int = 0
    total_trade_amount: float = 0.0
    total_slippage_cost: float = 0.0
    reports: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    safety_flags: dict = field(default_factory=lambda: {
        "auto_apply": False,
        "no_live_trade": True,
        "sandbox_only": True,
    })
    # V4.6 fields
    filter_summary: dict = field(default_factory=dict)
    slippage_control_summary: dict = field(default_factory=dict)
    filter_results: list = field(default_factory=list)
    n_filter_blocked: int = 0
    n_slippage_blocked: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class ShadowPipelineRunner:
    """V4.6 Shadow Live Pipeline — 影子实盘运行器

    Orchestrates shadow execution:
      1. Creates shadow account with initial cash
      2. Processes signals through order creation
      3. **V4.6: Runs trade filter checks before execution**
      4. **V4.6: Runs slippage estimation & budget control**
      5. Simulates fills with configurable slippage
      6. Tracks positions and PnL
      7. Generates deviation reports
      8. Produces a ShadowPipelineResult

    All operations are sandbox-only (no_live_trade=True).
    """

    def __init__(self, config: Optional[ShadowPipelineConfig] = None):
        self.config = config or ShadowPipelineConfig()
        self.account = ShadowAccount(
            initial_cash=self.config.initial_cash,
            cash=self.config.initial_cash,
        )
        self.order_manager = ShadowOrderManager()

        slippage_config = SlippageConfig(
            model=self.config.slippage_model,
            fixed_pct=self.config.slippage_pct,
            fill_strategy=self.config.fill_strategy,
        )
        self.fill_engine = FillEngine(slippage_config=slippage_config)
        self.ledger = ShadowExecutionLedger(
            output_dir=self.config.output_dir
        )
        self.result: Optional[ShadowPipelineResult] = None
        self.errors: list = []

        # V4.6 Trade Filter
        if self.config.enable_trade_filter:
            rules = self.config.trade_filter_rules
            self.trade_filter = TradeFilterEngine(rules=rules)
        else:
            self.trade_filter = None

        # V4.6 Slippage Control
        if self.config.enable_slippage_control:
            budget_dict = self.config.slippage_budget
            budget = SlippageBudget(**(budget_dict or {}))
            self.slippage_controller = SlippageController(
                slippage_config=slippage_config,
                budget=budget,
                confidence_multiplier=self.config.slippage_confidence_multiplier,
            )
        else:
            self.slippage_controller = None

    # -- Market data helpers ---------------------------------------------

    @staticmethod
    def make_market_snapshot(symbol: str, price: float,
                             volume: float = 1_000_000,
                             avg_volume: float = 2_000_000,
                             volatility: float = 0.02,
                             limit_up: float = 0.0,
                             limit_down: float = 0.0,
                             name: str = "",
                             date: str = "",
                             source: str = "simulated") -> MarketDataSnapshot:
        """Create a market data snapshot from known values.

        This is useful for tests and simulations where live data is unavailable.
        """
        return MarketDataSnapshot(
            symbol=symbol,
            name=name,
            date=date or datetime.now(CST).strftime("%Y-%m-%d"),
            time=datetime.now(CST).strftime("%H:%M:%S"),
            open=price,
            high=price * 1.02,
            low=price * 0.98,
            close=price,
            pre_close=price,
            volume=volume,
            amount=volume * price,
            avg_volume_20d=avg_volume,
            volatility_20d=volatility,
            limit_up=limit_up or round(price * 1.10, 2),
            limit_down=limit_down or round(price * 0.90, 2),
            source=source,
        )

    @staticmethod
    def make_market_missing(symbol: str) -> MarketDataSnapshot:
        """Create a market data snapshot for a missing-data scenario."""
        return MarketDataSnapshot(
            symbol=symbol,
            status=MarketDataStatus.MISSING.value,
            source="none",
        )

    # -- Core execution flow ---------------------------------------------

    def process_signal(self, signal_id: str, proposal_id: str,
                       trades: list) -> ShadowPipelineResult:
        """Process a list of trade instructions through the shadow pipeline.

        V4.6 additions:
          - Runs TradeFilterEngine before each trade
          - Runs SlippageController estimation + budget check before each trade
          - Trades blocked by filters are recorded and skipped

        Args:
            signal_id: ID of the source research signal
            proposal_id: ID of the source proposal
            trades: list of dicts with keys:
                - symbol: str
                - side: "buy" | "sell"
                - quantity: int (shares)
                - price: float (reference price)
                - name: str (optional)
                - signal_price: float (optional, price when signal generated)
                - market_data: MarketDataSnapshot (optional)
                - board_type: str (optional, for trade filter)
                - is_suspended: bool (optional, for trade filter)

        Returns:
            ShadowPipelineResult with full execution details
        """
        run_id = f"shadow_run_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
        started_at = datetime.now(CST).isoformat()

        self.fill_engine.reset()
        n_filled = 0
        n_rejected = 0
        n_filter_blocked = 0
        n_slippage_blocked = 0
        total_amount = 0.0
        filter_results_list = []

        for i, trade in enumerate(trades):
            symbol = trade.get("symbol", "")
            side = trade.get("side", "buy")
            quantity = trade.get("quantity", 0)
            price = trade.get("price", 0.0)
            name = trade.get("name", "")
            signal_price = trade.get("signal_price", price)
            market = trade.get("market_data")
            board_type = trade.get("board_type", "")
            is_suspended = trade.get("is_suspended", False)

            if not symbol or quantity <= 0:
                self.errors.append(f"Trade #{i}: invalid symbol={symbol} quantity={quantity}")
                n_rejected += 1
                continue

            # ── V4.6 Step 0: Run trade filter ────────────────────────
            if self.trade_filter is not None:
                ctx = TradeContext(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    signal_price=signal_price,
                    limit_up=(market.limit_up if market else 0.0),
                    limit_down=(market.limit_down if market else 0.0),
                    close=(market.close if market else 0.0),
                    market_status=(market.status if market else ""),
                    board_type=board_type or (
                        market.name if market else ""
                    ),
                    is_suspended=is_suspended or False,
                    avg_amount_20d=(
                        (market.avg_volume_20d * market.close)
                        if market and market.avg_volume_20d > 0
                        else 0.0
                    ),
                    total_equity=self.account.total_equity,
                    cash=self.account.cash,
                    current_position_shares=(
                        self.account.get_position(symbol).shares
                        if self.account.get_position(symbol)
                        else 0
                    ),
                    current_position_cost=(
                        self.account.get_position(symbol).avg_cost
                        if self.account.get_position(symbol)
                        else 0.0
                    ),
                    total_exposure=self.account.exposure,
                    estimated_slippage_pct=0.0,
                )

                filter_report = self.trade_filter.evaluate_trade(ctx)
                filter_results_list.append(filter_report)

                if filter_report.blocked:
                    self.errors.append(
                        f"Trade #{i} FILTER BLOCKED: {symbol} {side} {quantity} — "
                        f"{'; '.join(filter_report.blocker_messages)}"
                    )
                    n_filter_blocked += 1
                    n_rejected += 1
                    continue

            # ── V4.6 Step 0.5: Run slippage estimation & budget ─────
            if self.slippage_controller is not None:
                order_id = f"{signal_id}_{symbol}_{i}"
                slip_result = self.slippage_controller.check_trade(
                    order_id=order_id,
                    side=side,
                    quantity=quantity,
                    price=price,
                    market=market,
                )

                if not slip_result.get("allowed"):
                    self.errors.append(
                        f"Trade #{i} SLIPPAGE BLOCKED: {symbol} {side} {quantity} — "
                        f"{slip_result.get('reason', 'Slippage budget exceeded')}"
                    )
                    n_slippage_blocked += 1
                    n_rejected += 1
                    continue

            # 1. Create order
            order = self.order_manager.create_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                name=name,
                signal_id=signal_id,
                proposal_id=proposal_id,
            )

            # 2. Check if order rejected during creation
            if order.status == OrderStatus.REJECTED.value:
                self.errors.append(
                    f"Order rejected: {symbol} {side} {quantity} — {order.reject_reason}: {order.reject_detail}"
                )
                n_rejected += 1
                continue

            # 3. Submit order (pending -> submitted)
            self.order_manager.submit_order(order.order_id)

            # 4. Execute fill
            fill_result = self.fill_engine.execute_fill(
                order_side=side,
                order_quantity=quantity,
                order_price=price,
                symbol=symbol,
                market=market,
                name=name,
            )

            if not fill_result.get("success"):
                # Reject the order
                reason = fill_result.get("reject_reason", "unknown")
                detail = fill_result.get("reject_detail", "")
                self.order_manager.reject_order(order.order_id, reason, detail)
                self.errors.append(
                    f"Fill rejected: {symbol} {side} {quantity} — {reason}: {detail}"
                )
                n_rejected += 1
                continue

            # 5. Apply fills to order
            fills = fill_result.get("fills", [])
            for f in fills:
                fill_event = FillEvent(
                    order_id=order.order_id,
                    symbol=symbol,
                    side=side,
                    shares=f["shares"],
                    price=f["price"],
                    slippage=f["slippage"],
                    commission=f["commission"],
                    tax=f["tax"],
                )
                self.order_manager.apply_fill(order.order_id, fill_event)

                # 6. Apply fill to shadow account
                position_before = 0
                pos = self.account.get_position(symbol)
                if pos:
                    position_before = pos.shares

                cash_before = self.account.cash

                if side == "buy":
                    account_result = self.account.apply_buy(
                        symbol=symbol,
                        shares=f["shares"],
                        price=f["price"],
                        name=name,
                        commission=f["commission"],
                        tax=f["tax"],
                        slippage=f["slippage"],
                    )
                else:
                    account_result = self.account.apply_sell(
                        symbol=symbol,
                        shares=f["shares"],
                        price=f["price"],
                        name=name,
                        commission=f["commission"],
                        tax=f["tax"],
                        slippage=f["slippage"],
                    )

                if account_result.get("success"):
                    # Get position after
                    pos_after = self.account.get_position(symbol)
                    position_after = pos_after.shares if pos_after else 0

                    # 7. Record fill in slippage budget tracker
                    if self.slippage_controller is not None:
                        self.slippage_controller.record_fill(
                            order.order_id,
                            fill_value=f["shares"] * f["price"],
                            actual_slippage_yuan=f["slippage"] * f["shares"],
                        )

                    # 8. Record in ledger
                    if side == "buy":
                        self.ledger.record_buy(
                            symbol=symbol, name=name,
                            shares=f["shares"], price=f["price"],
                            signal_price=signal_price,
                            slippage=f["slippage"],
                            commission=f["commission"], tax=f["tax"],
                            cash_before=cash_before,
                            cash_after=self.account.cash,
                            position_before=position_before,
                            position_after=position_after,
                            order_id=order.order_id,
                            signal_id=signal_id,
                            proposal_id=proposal_id,
                        )
                    else:
                        self.ledger.record_sell(
                            symbol=symbol, name=name,
                            shares=f["shares"], price=f["price"],
                            signal_price=signal_price,
                            slippage=f["slippage"],
                            commission=f["commission"], tax=f["tax"],
                            cash_before=cash_before,
                            cash_after=self.account.cash,
                            position_before=position_before,
                            position_after=position_after,
                            order_id=order.order_id,
                            signal_id=signal_id,
                            proposal_id=proposal_id,
                        )

                    total_amount += f["shares"] * f["price"]
                    n_filled += 1

        # 9. Generate reports
        reports = {}
        if self.config.auto_generate_reports and self.config.output_dir:
            os.makedirs(self.config.output_dir, exist_ok=True)
            reports = self.ledger.generate_all_reports(self.config.output_dir)
            self.account.save(self.config.output_dir)
            self.order_manager.save(self.config.output_dir)

        # 10. Build result
        deviations = self.ledger.compute_deviations()
        dev_summary = self.ledger.deviation_summary(deviations)

        completed_at = datetime.now(CST).isoformat()
        status = "completed" if not self.errors else "partial"

        # V4.6 summaries
        filter_summary = {}
        if self.trade_filter is not None:
            filter_summary = self.trade_filter.get_summary()

        slippage_summary = {}
        if self.slippage_controller is not None:
            slippage_summary = self.slippage_controller.get_summary()

        self.result = ShadowPipelineResult(
            pipeline_id=f"shadow_pipe_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}",
            run_id=run_id,
            config=self.config.to_dict(),
            account_summary=self.account.summary(),
            orders_summary=self.order_manager.get_summary(),
            fill_summary=self.fill_engine.get_summary(),
            deviation_summary=dev_summary,
            n_orders=len(self.order_manager.orders),
            n_filled=n_filled,
            n_rejected=n_rejected,
            n_entries=len(self.ledger.entries),
            total_trade_amount=round(total_amount, 2),
            total_slippage_cost=dev_summary.get("total_slippage_cost", 0.0),
            reports=reports,
            errors=list(self.errors),
            started_at=started_at,
            completed_at=completed_at,
            # V4.6 fields
            filter_summary=filter_summary,
            slippage_control_summary=slippage_summary,
            filter_results=[r.to_dict() for r in filter_results_list],
            n_filter_blocked=n_filter_blocked,
            n_slippage_blocked=n_slippage_blocked,
        )
        return self.result

    def process_buy(self, symbol: str, quantity: int, price: float,
                    signal_price: float = 0.0, name: str = "",
                    signal_id: str = "", proposal_id: str = "",
                    market_data: Optional[MarketDataSnapshot] = None) -> dict:
        """Process a single buy through the shadow pipeline.

        Convenience method for single-trade execution.

        Returns execution result dict.
        """
        trades = [{
            "symbol": symbol,
            "side": "buy",
            "quantity": quantity,
            "price": price,
            "signal_price": signal_price or price,
            "name": name,
            "market_data": market_data,
        }]
        result = self.process_signal(signal_id, proposal_id, trades)
        return result.to_dict() if result else {"status": "failed"}

    def process_sell(self, symbol: str, quantity: int, price: float,
                     signal_price: float = 0.0, name: str = "",
                     signal_id: str = "", proposal_id: str = "",
                     market_data: Optional[MarketDataSnapshot] = None) -> dict:
        """Process a single sell through the shadow pipeline.

        Convenience method for single-trade execution.
        """
        trades = [{
            "symbol": symbol,
            "side": "sell",
            "quantity": quantity,
            "price": price,
            "signal_price": signal_price or price,
            "name": name,
            "market_data": market_data,
        }]
        result = self.process_signal(signal_id, proposal_id, trades)
        return result.to_dict() if result else {"status": "failed"}

    # -- Pipeline lifecycle ----------------------------------------------

    def reset(self, initial_cash: float = 0):
        """Reset the entire shadow pipeline to initial state."""
        cash = initial_cash or self.config.initial_cash
        self.account.reset(cash)
        self.order_manager.clear()
        self.fill_engine.reset()
        self.ledger.clear()
        self.errors.clear()
        self.result = None
        if self.trade_filter is not None:
            self.trade_filter.reset()
        if self.slippage_controller is not None:
            self.slippage_controller.reset()

    def to_dict(self) -> dict:
        """Serialize pipeline configuration as a design document."""
        doc = {
            "version": "V4.6",
            "pipeline": {
                "name": "Shadow Live Pipeline",
                "description": "影子实盘流水线 — 真实行情+模拟账户验证信号闭环",
                "auto_apply": False,
                "no_live_trade": True,
                "sandbox_only": True,
                "config": self.config.to_dict(),
            },
            "components": {
                "shadow_account": "小桌现金+持仓+盈亏追踪",
                "shadow_order_manager": "订单生命周期管理 (PENDING→FILLED/REJECTED/CANCELLED)",
                "fill_engine": "成交模拟 + 滑点模型 (fixed_pct/volume/volatility/hybrid)",
                "execution_ledger": "影子实盘账本 + 偏差统计",
                "trade_filter": "V4.6 交易过滤器: 涨停/ST/停牌/流动性/集中度/价差",
                "slippage_controller": "V4.6 滑点控制: 预算跟踪+预执行估算",
            },
            "safety_boundaries": {
                "auto_apply": False,
                "no_live_trade": True,
                "no_broker_adapter": True,
                "no_real_order_submission": True,
                "sandbox_environment": True,
            },
        }

        # Add V4.6 filter details if enabled
        if self.trade_filter is not None:
            doc["components"]["trade_filter_rules"] = [
                r.name for r in self.trade_filter.rules if r.enabled
            ]
        if self.slippage_controller is not None:
            doc["components"]["slippage_budget"] = \
                self.slippage_controller.budget_tracker.budget.to_dict()

        return doc
