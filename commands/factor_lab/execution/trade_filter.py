"""V4.6 Trade Filter & Slippage Control — Trade Filter Engine

Pre-execution trade filtering that blocks or warns on trades that
violate configurable risk policies.

Filter dimensions:
  1. PRICE_LIMIT       — 涨停不追买 / 跌停不能卖
  2. BOARD_TYPE        — ST / *ST / 退市整理期 / 科创板 / 创业板
  3. SUSPENSION        — 停牌
  4. VOLUME_LIQUIDITY  — 订单量占日均成交额比例过大
  5. POSITION_CONCENTRATION — 单票集中度 / 行业集中度
  6. PRICE_GAP         — 信号价距现价偏离过大
  7. MARKET_STATE      — 非交易时段 / 节假日
  8. MAX_ORDER_SIZE    — 单笔订单金额超限
  9. CUSTOM            — 自定义过滤

Design:
  - Filters are evaluated BEFORE the FillEngine executes a trade
  - Each filter has a severity (blocker/warning/info)
  - BLOCKER filters prevent trade execution
  - WARNING filters log but allow execution
  - INFO filters record for monitoring
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Optional

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Filter types
# ---------------------------------------------------------------------------
class FilterType(Enum):
    """Trade filter categories."""
    PRICE_LIMIT = "price_limit"
    BOARD_TYPE = "board_type"
    SUSPENSION = "suspension"
    VOLUME_LIQUIDITY = "volume_liquidity"
    POSITION_CONCENTRATION = "position_concentration"
    PRICE_GAP = "price_gap"
    MARKET_STATE = "market_state"
    MAX_ORDER_SIZE = "max_order_size"
    CUSTOM = "custom"


class FilterSeverity(Enum):
    """How a filter violation is treated."""
    BLOCKER = "blocker"   # Trade is rejected
    WARNING = "warning"   # Trade proceeds but warning logged
    INFO = "info"         # Only logged for monitoring


class FilterStatus(Enum):
    """Result status of a single filter check."""
    PASSED = "passed"
    BLOCKED = "blocked"
    WARNED = "warned"
    SKIPPED = "skipped"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Filter rule definition
# ---------------------------------------------------------------------------
@dataclass
class TradeFilterRule:
    """Definition of a single trade filter rule.

    Each rule checks one dimension of a trade and decides whether
    it should pass, warn, or be blocked.
    """
    name: str
    filter_type: str = FilterType.CUSTOM.value
    description: str = ""
    severity: str = FilterSeverity.BLOCKER.value
    enabled: bool = True
    threshold: float = 0.0
    message_template: str = "Trade filtered by {name}: {detail}"

    # Runtime state
    _last_result: str = FilterStatus.PASSED.value
    _last_checked_at: str = ""
    _consecutive_violations: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in list(d.keys()):
            if k.startswith("_"):
                d.pop(k)
        return d

    def clone(self) -> "TradeFilterRule":
        """Create a mutable copy with fresh runtime state."""
        return TradeFilterRule(
            name=self.name,
            filter_type=self.filter_type,
            description=self.description,
            severity=self.severity,
            enabled=self.enabled,
            threshold=self.threshold,
            message_template=self.message_template,
        )


# ---------------------------------------------------------------------------
# Filter result
# ---------------------------------------------------------------------------
@dataclass
class FilterResult:
    """Result of evaluating a single trade filter rule."""
    filter_name: str
    filter_type: str
    passed: bool = True
    severity: str = FilterSeverity.INFO.value
    status: str = FilterStatus.PASSED.value
    message: str = ""
    detail: str = ""
    threshold: float = 0.0
    actual_value: float = 0.0
    details: dict = field(default_factory=dict)
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(CST).isoformat()

    def is_blocked(self) -> bool:
        return self.status == FilterStatus.BLOCKED.value

    def is_warning(self) -> bool:
        return self.status == FilterStatus.WARNED.value

    def is_passed(self) -> bool:
        return self.status == FilterStatus.PASSED.value

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Aggregated filter report
# ---------------------------------------------------------------------------
@dataclass
class FilterReport:
    """Complete report of all filter checks for a trade."""
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    price: float = 0.0
    passed: bool = True
    blocked: bool = False
    n_checks: int = 0
    n_passed: int = 0
    n_blocked: int = 0
    n_warnings: int = 0
    n_skipped: int = 0
    results: list = field(default_factory=list)
    blocker_messages: list = field(default_factory=list)
    warning_messages: list = field(default_factory=list)
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "passed": self.passed,
            "blocked": self.blocked,
            "n_checks": self.n_checks,
            "n_passed": self.n_passed,
            "n_blocked": self.n_blocked,
            "n_warnings": self.n_warnings,
            "n_skipped": self.n_skipped,
            "results": [r.to_dict() for r in self.results],
            "blocker_messages": self.blocker_messages,
            "warning_messages": self.warning_messages,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# Trade context (what the filter evaluates)
# ---------------------------------------------------------------------------
@dataclass
class TradeContext:
    """Context for evaluating trade filters.

    Carries all information needed by filters about the trade,
    market conditions, and account state.
    """
    # Trade info
    symbol: str = ""
    side: str = ""          # "buy" | "sell"
    quantity: int = 0
    price: float = 0.0      # Proposed/reference price
    order_type: str = "market"  # "market" | "limit"
    limit_price: float = 0.0

    # Market data (from MarketDataSnapshot or similar)
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    avg_volume_20d: float = 0.0
    avg_amount_20d: float = 0.0
    volatility_20d: float = 0.0
    limit_up: float = 0.0
    limit_down: float = 0.0
    market_status: str = ""  # "available" | "stale" | "missing"
    board_type: str = ""     # "main" | "star" | "chinext" | "st" | "star_st" | "suspended"
    is_suspended: bool = False

    # Account context
    total_equity: float = 0.0
    cash: float = 0.0
    current_position_shares: int = 0
    current_position_cost: float = 0.0
    total_exposure: float = 0.0
    max_position_pct: float = 0.0    # Current max position percentage

    # Slippage context
    estimated_slippage_pct: float = 0.0

    # Extra metadata
    signal_price: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(CST).isoformat()


# ---------------------------------------------------------------------------
# Built-in filter rules
# ---------------------------------------------------------------------------
def build_default_trade_filter_rules() -> list[TradeFilterRule]:
    """Build the default set of V4.6 trade filter rules."""
    rules = []

    # ── PRICE_LIMIT — 涨停/跌停 ──────────────────────────────────────────
    rules.append(TradeFilterRule(
        name="buy_limit_up",
        filter_type=FilterType.PRICE_LIMIT.value,
        description="涨停不追买 — 当日涨幅已达涨停价时禁止买入",
        severity=FilterSeverity.BLOCKER.value,
        threshold=0.0,
        message_template="涨停禁止买入: 现价{price} = 涨停价{limit_up}",
    ))

    rules.append(TradeFilterRule(
        name="sell_limit_down",
        filter_type=FilterType.PRICE_LIMIT.value,
        description="跌停不能卖 — 当日跌幅已达跌停价时禁止卖出",
        severity=FilterSeverity.BLOCKER.value,
        threshold=0.0,
        message_template="跌停禁止卖出: 现价{price} = 跌停价{limit_down}",
    ))

    # ── BOARD_TYPE — 板块类型 ────────────────────────────────────────────
    rules.append(TradeFilterRule(
        name="st_stock_filter",
        filter_type=FilterType.BOARD_TYPE.value,
        description="ST / *ST 股票禁止买入",
        severity=FilterSeverity.BLOCKER.value,
        threshold=0.0,
        message_template="ST/*ST 股票禁止买入: {board_type}",
    ))

    rules.append(TradeFilterRule(
        name="delisting_filter",
        filter_type=FilterType.BOARD_TYPE.value,
        description="退市整理期股票禁止交易",
        severity=FilterSeverity.BLOCKER.value,
        threshold=0.0,
        message_template="退市整理期股票禁止交易",
    ))

    # ── SUSPENSION — 停牌 ───────────────────────────────────────────────
    rules.append(TradeFilterRule(
        name="suspension_filter",
        filter_type=FilterType.SUSPENSION.value,
        description="停牌股票禁止交易",
        severity=FilterSeverity.BLOCKER.value,
        threshold=0.0,
        message_template="停牌股票禁止交易: {symbol}",
    ))

    # ── VOLUME_LIQUIDITY — 成交量流动性 ──────────────────────────────────
    rules.append(TradeFilterRule(
        name="volume_liquidity_filter",
        filter_type=FilterType.VOLUME_LIQUIDITY.value,
        description="订单金额占日均成交额比例过大",
        severity=FilterSeverity.WARNING.value,
        threshold=0.1,  # 10% of avg daily amount
        message_template="订单金额{order_amount}超过日均成交额{avg_amount}的{threshold:.0%}",
    ))

    # ── POSITION_CONCENTRATION — 集中度 ──────────────────────────────────
    rules.append(TradeFilterRule(
        name="single_stock_concentration",
        filter_type=FilterType.POSITION_CONCENTRATION.value,
        description="单只股票持仓集中度上限",
        severity=FilterSeverity.WARNING.value,
        threshold=0.25,  # 25% max
        message_template="单票集中度{concentration:.1%}超过阈值{threshold:.0%}",
    ))

    # ── PRICE_GAP — 信号价偏离 ───────────────────────────────────────────
    rules.append(TradeFilterRule(
        name="price_gap_filter",
        filter_type=FilterType.PRICE_GAP.value,
        description="信号价与现价偏离过大",
        severity=FilterSeverity.WARNING.value,
        threshold=0.05,  # 5% gap
        message_template="信号价{signal_price}与现价{current_price}偏离{gap:.2%} > {threshold:.0%}",
    ))

    # ── MARKET_STATE — 交易时段 ──────────────────────────────────────────
    rules.append(TradeFilterRule(
        name="market_state_filter",
        filter_type=FilterType.MARKET_STATE.value,
        description="市场数据状态异常时禁止交易",
        severity=FilterSeverity.BLOCKER.value,
        threshold=0.0,
        message_template="市场数据状态异常: {market_status}",
    ))

    # ── MAX_ORDER_SIZE — 单笔规模上限 ────────────────────────────────────
    rules.append(TradeFilterRule(
        name="max_order_size_filter",
        filter_type=FilterType.MAX_ORDER_SIZE.value,
        description="单笔订单金额上限",
        severity=FilterSeverity.BLOCKER.value,
        threshold=500_000,  # ¥500k max per order
        message_template="单笔订单金额{order_amount}超过上限{threshold}",
    ))

    return rules


# ---------------------------------------------------------------------------
# Board type helpers
# ---------------------------------------------------------------------------
def detect_board_type(symbol: str, name: str = "") -> str:
    """Detect board type from symbol and/or name.

    Returns one of: "main", "star", "chinext", "st", "star_st", "delisting"
    """
    # ST/*ST detection
    if symbol.endswith("ST") or "*ST" in symbol:
        return "st"
    if "退" in name:
        return "delisting"

    # Board detection by symbol prefix
    if symbol.startswith("688"):
        return "star"
    if symbol.startswith(("300", "301")):
        return "chinext"
    if symbol.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "main"

    return "main"


def is_st_board(symbol: str, name: str = "") -> bool:
    """Check if a stock is ST / *ST."""
    board = detect_board_type(symbol, name)
    return board == "st"


def is_delisting(board: str) -> bool:
    """Check if board type is delisting."""
    return board == "delisting"


def is_suspended(symbol: str, market_status: str = "") -> bool:
    """Check if a stock is suspended.

    Args:
        symbol: Stock symbol
        market_status: Market data status string

    Returns True if market data is missing or indicates suspension.
    """
    if market_status == "suspended":
        return True
    return False


# ---------------------------------------------------------------------------
# Trade Filter Engine
# ---------------------------------------------------------------------------
class TradeFilterEngine:
    """Pre-execution trade filter engine.

    Evaluates trades against configurable filter rules before they
    are passed to the FillEngine.

    Usage:
        engine = TradeFilterEngine()
        report = engine.evaluate_trade(trade_context)
        if report.blocked:
            print(f"Trade blocked: {report.blocker_messages}")
        elif report.n_warnings > 0:
            print(f"Trade warnings: {report.warning_messages}")
    """

    def __init__(self, rules: Optional[list[TradeFilterRule]] = None,
                 name: str = "default"):
        self.name = name
        self._rules: dict[str, TradeFilterRule] = {}
        self._custom_evaluators: dict[str, Callable] = {}
        self._evaluation_history: list[FilterReport] = []

        # Load rules
        if rules is not None:
            for r in rules:
                self._rules[r.name] = r
        else:
            for r in build_default_trade_filter_rules():
                self._rules[r.name] = r

        # Register built-in evaluators
        self._register_builtin_evaluators()

    # -- Rule management ---------------------------------------------------

    @property
    def rules(self) -> list[TradeFilterRule]:
        return list(self._rules.values())

    def add_rule(self, rule: TradeFilterRule):
        """Add a filter rule."""
        self._rules[rule.name] = rule

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a filter rule by name."""
        if rule_name in self._rules:
            del self._rules[rule_name]
            return True
        return False

    def get_rule(self, rule_name: str) -> Optional[TradeFilterRule]:
        """Get a rule by name."""
        return self._rules.get(rule_name)

    def enable_rule(self, rule_name: str) -> bool:
        """Enable a rule."""
        rule = self._rules.get(rule_name)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable_rule(self, rule_name: str) -> bool:
        """Disable a rule."""
        rule = self._rules.get(rule_name)
        if rule:
            rule.enabled = False
            return True
        return False

    def register_custom_evaluator(self, rule_name: str,
                                   evaluator_fn: Callable) -> bool:
        """Register a custom evaluator function for a filter rule.

        The function receives (rule: TradeFilterRule, context: TradeContext)
        and returns FilterResult.
        """
        if rule_name in self._rules:
            self._custom_evaluators[rule_name] = evaluator_fn
            return True
        return False

    # -- Evaluation --------------------------------------------------------

    def evaluate_trade(self, context: TradeContext) -> FilterReport:
        """Evaluate a trade against all enabled filter rules.

        Args:
            context: TradeContext with trade, market, and account info

        Returns:
            FilterReport with all filter results
        """
        results: list[FilterResult] = []
        n_passed = 0
        n_blocked = 0
        n_warnings = 0
        n_skipped = 0
        blocker_messages: list[str] = []
        warning_messages: list[str] = []

        for rule in self._rules.values():
            if not rule.enabled:
                n_skipped += 1
                continue

            try:
                result = self._evaluate_rule(rule, context)
            except Exception as e:
                result = FilterResult(
                    filter_name=rule.name,
                    filter_type=rule.filter_type,
                    passed=False,
                    severity=FilterSeverity.BLOCKER.value,
                    status=FilterStatus.ERROR.value,
                    message=f"Filter evaluation error: {e}",
                    detail=str(e),
                )

            results.append(result)

            if result.status == FilterStatus.PASSED.value:
                n_passed += 1
            elif result.status == FilterStatus.BLOCKED.value:
                n_blocked += 1
                blocker_messages.append(result.message)
            elif result.status == FilterStatus.WARNED.value:
                n_warnings += 1
                warning_messages.append(result.message)
            elif result.status == FilterStatus.SKIPPED.value:
                n_skipped += 1

        passed = n_blocked == 0

        report = FilterReport(
            symbol=context.symbol,
            side=context.side,
            quantity=context.quantity,
            price=context.price,
            passed=passed,
            blocked=not passed,
            n_checks=len(results),
            n_passed=n_passed,
            n_blocked=n_blocked,
            n_warnings=n_warnings,
            n_skipped=n_skipped,
            results=results,
            blocker_messages=blocker_messages,
            warning_messages=warning_messages,
        )
        self._evaluation_history.append(report)
        return report

    def _evaluate_rule(self, rule: TradeFilterRule,
                       context: TradeContext) -> FilterResult:
        """Evaluate a single filter rule against trade context."""
        # Check for custom evaluator first
        if rule.name in self._custom_evaluators:
            result = self._custom_evaluators[rule.name](rule, context)
            self._update_rule_state(rule, result)
            return result

        # Built-in evaluator
        evaluator = self._builtin_evaluators.get(rule.name)
        if evaluator:
            result = evaluator(rule, context)
            self._update_rule_state(rule, result)
            return result

        # Unknown rule — skip
        return FilterResult(
            filter_name=rule.name,
            filter_type=rule.filter_type,
            passed=True,
            severity=FilterSeverity.INFO.value,
            status=FilterStatus.SKIPPED.value,
            message=f"No evaluator for rule: {rule.name}",
        )

    def _update_rule_state(self, rule: TradeFilterRule,
                           result: FilterResult):
        """Update rule runtime state after evaluation."""
        rule._last_checked_at = result.checked_at
        rule._last_result = result.status
        if result.is_blocked() or result.is_warning():
            rule._consecutive_violations += 1
        else:
            rule._consecutive_violations = 0

    # -- Built-in evaluators ----------------------------------------------

    _builtin_evaluators: dict = {}

    def _register_builtin_evaluators(self):
        """Register built-in evaluator functions."""
        self._builtin_evaluators = {
            "buy_limit_up": _eval_buy_limit_up,
            "sell_limit_down": _eval_sell_limit_down,
            "st_stock_filter": _eval_st_stock,
            "delisting_filter": _eval_delisting,
            "suspension_filter": _eval_suspension,
            "volume_liquidity_filter": _eval_volume_liquidity,
            "single_stock_concentration": _eval_concentration,
            "price_gap_filter": _eval_price_gap,
            "market_state_filter": _eval_market_state,
            "max_order_size_filter": _eval_max_order_size,
        }

    # -- Reports ----------------------------------------------------------

    def get_history(self, n: int = 50) -> list[dict]:
        """Get recent evaluation history."""
        return [r.to_dict() for r in self._evaluation_history[-n:]]

    def get_summary(self) -> dict:
        """Get engine activity summary."""
        total = len(self._evaluation_history)
        blocked = sum(1 for r in self._evaluation_history if r.blocked)
        warned = sum(1 for r in self._evaluation_history if r.n_warnings > 0)
        return {
            "name": self.name,
            "total_evaluations": total,
            "n_blocked": blocked,
            "n_warned": warned,
            "n_passed": total - blocked - warned,
            "active_rules": len([r for r in self._rules.values() if r.enabled]),
            "total_rules": len(self._rules),
        }

    def reset(self):
        """Reset evaluation history."""
        self._evaluation_history.clear()
        for rule in self._rules.values():
            rule._last_result = FilterStatus.PASSED.value
            rule._last_checked_at = ""
            rule._consecutive_violations = 0

    def to_dict(self) -> dict:
        """Full serialization."""
        return {
            "name": self.name,
            "summary": self.get_summary(),
            "rules": {name: rule.to_dict()
                      for name, rule in self._rules.items()},
            "recent_evaluations": self.get_history(5),
        }


# ===========================================================================
# Built-in evaluator functions
# ===========================================================================

def _eval_buy_limit_up(rule: TradeFilterRule,
                       ctx: TradeContext) -> FilterResult:
    """涨停禁止买入：当日涨幅已达到涨停价时禁止买入"""
    if ctx.side != "buy":
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=True, severity=FilterSeverity.INFO.value,
            status=FilterStatus.PASSED.value,
            message="Not a buy order",
        )

    if ctx.limit_up > 0 and ctx.close >= ctx.limit_up:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message=f"涨停禁止买入: 现价{ctx.close} = 涨停价{ctx.limit_up}",
            detail=f"close={ctx.close} >= limit_up={ctx.limit_up}",
            threshold=ctx.limit_up,
            actual_value=ctx.close,
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Price within limit: close={ctx.close} < limit_up={ctx.limit_up}",
    )


def _eval_sell_limit_down(rule: TradeFilterRule,
                          ctx: TradeContext) -> FilterResult:
    """跌停不能卖：当日跌幅已达到跌停价时禁止卖出"""
    if ctx.side != "sell":
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=True, severity=FilterSeverity.INFO.value,
            status=FilterStatus.PASSED.value,
            message="Not a sell order",
        )

    if ctx.limit_down > 0 and ctx.close <= ctx.limit_down:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message=f"跌停禁止卖出: 现价{ctx.close} = 跌停价{ctx.limit_down}",
            detail=f"close={ctx.close} <= limit_down={ctx.limit_down}",
            threshold=ctx.limit_down,
            actual_value=ctx.close,
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Price within limit: close={ctx.close} > limit_down={ctx.limit_down}",
    )


def _eval_st_stock(rule: TradeFilterRule,
                   ctx: TradeContext) -> FilterResult:
    """ST / *ST 股票禁止买入

    Checks ctx.board_type first (passed from upstream), then
    falls back to symbol-based detection.
    """
    is_st = (ctx.board_type == "st"
             or is_st_board(ctx.symbol, ctx.board_type))

    if is_st:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message=f"ST/*ST 股票禁止买入: 板块={ctx.board_type}",
            detail=f"symbol={ctx.symbol}, board_type={ctx.board_type}",
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
    )


def _eval_delisting(rule: TradeFilterRule,
                    ctx: TradeContext) -> FilterResult:
    """退市整理期股票禁止交易"""
    is_delist = (ctx.board_type == "delisting"
                 or detect_board_type(ctx.symbol, ctx.board_type) == "delisting")
    if is_delist:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message="退市整理期股票禁止交易",
            detail=f"symbol={ctx.symbol} is delisting",
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
    )


def _eval_suspension(rule: TradeFilterRule,
                     ctx: TradeContext) -> FilterResult:
    """停牌股票禁止交易"""
    if ctx.is_suspended:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message=f"停牌股票禁止交易: {ctx.symbol}",
            detail=f"symbol={ctx.symbol} is suspended",
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
    )


def _eval_volume_liquidity(rule: TradeFilterRule,
                           ctx: TradeContext) -> FilterResult:
    """订单金额占日均成交额比例检查"""
    order_amount = ctx.price * ctx.quantity
    avg_amount = ctx.avg_amount_20d

    if avg_amount <= 0:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=True, severity=FilterSeverity.INFO.value,
            status=FilterStatus.SKIPPED.value,
            message="No avg amount data available, skipping",
        )

    ratio = order_amount / avg_amount
    if ratio > rule.threshold:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.WARNING.value,
            status=FilterStatus.WARNED.value,
            message=f"订单金额{order_amount:.0f}超过日均成交额{avg_amount:.0f}的{rule.threshold:.0%}",
            detail=f"order_amount={order_amount:.0f}, avg_amount={avg_amount:.0f}, ratio={ratio:.2%}",
            threshold=rule.threshold,
            actual_value=ratio,
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Liquidity OK: ratio={ratio:.2%} <= {rule.threshold:.0%}",
    )


def _eval_concentration(rule: TradeFilterRule,
                        ctx: TradeContext) -> FilterResult:
    """单只股票持仓集中度检查"""
    if ctx.total_equity <= 0:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=True, severity=FilterSeverity.INFO.value,
            status=FilterStatus.SKIPPED.value,
            message="No equity data, skipping",
        )

    # Calculate what the new position value would be after this trade
    order_value = ctx.price * ctx.quantity
    current_position_value = ctx.current_position_shares * ctx.current_position_cost

    if ctx.side == "buy":
        new_position_value = current_position_value + order_value
    else:
        new_position_value = max(0, current_position_value - order_value)

    concentration = new_position_value / ctx.total_equity

    if concentration > rule.threshold:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.WARNING.value,
            status=FilterStatus.WARNED.value,
            message=f"单票集中度{concentration:.1%}超过阈值{rule.threshold:.0%}",
            detail=f"concentration={concentration:.4f}, threshold={rule.threshold}",
            threshold=rule.threshold,
            actual_value=concentration,
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Concentration OK: {concentration:.1%} <= {rule.threshold:.0%}",
    )


def _eval_price_gap(rule: TradeFilterRule,
                    ctx: TradeContext) -> FilterResult:
    """信号价与现价偏离过大检查"""
    if ctx.signal_price <= 0 or ctx.price <= 0:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=True, severity=FilterSeverity.INFO.value,
            status=FilterStatus.SKIPPED.value,
            message="No price data, skipping",
        )

    gap = abs(ctx.price - ctx.signal_price) / ctx.signal_price
    if gap > rule.threshold:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.WARNING.value,
            status=FilterStatus.WARNED.value,
            message=f"信号价{ctx.signal_price}与现价{ctx.price}偏离{gap:.2%} > {rule.threshold:.0%}",
            detail=f"signal_price={ctx.signal_price}, current_price={ctx.price}, gap={gap:.4f}",
            threshold=rule.threshold,
            actual_value=gap,
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Price gap OK: {gap:.2%} <= {rule.threshold:.0%}",
    )


def _eval_market_state(rule: TradeFilterRule,
                       ctx: TradeContext) -> FilterResult:
    """市场数据状态异常时禁止交易"""
    if ctx.market_status in ("missing", "stale", "suspended", "error"):
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message=f"市场数据状态异常: {ctx.market_status}",
            detail=f"market_status={ctx.market_status}",
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Market state OK: {ctx.market_status}",
    )


def _eval_max_order_size(rule: TradeFilterRule,
                         ctx: TradeContext) -> FilterResult:
    """单笔订单金额上限检查"""
    order_amount = ctx.price * ctx.quantity
    if order_amount > rule.threshold:
        return FilterResult(
            filter_name=rule.name, filter_type=rule.filter_type,
            passed=False, severity=FilterSeverity.BLOCKER.value,
            status=FilterStatus.BLOCKED.value,
            message=f"单笔订单金额{order_amount:.0f}超过上限{rule.threshold:.0f}",
            detail=f"order_amount={order_amount:.0f}, threshold={rule.threshold}",
            threshold=rule.threshold,
            actual_value=order_amount,
        )

    return FilterResult(
        filter_name=rule.name, filter_type=rule.filter_type,
        passed=True, severity=FilterSeverity.INFO.value,
        status=FilterStatus.PASSED.value,
        message=f"Order size OK: {order_amount:.0f} <= {rule.threshold:.0f}",
    )
