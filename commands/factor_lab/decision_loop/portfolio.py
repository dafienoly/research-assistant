"""Three-book allocation constraints and portfolio hard-risk modes."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .models import Book, PortfolioRiskInput, PortfolioRiskResult, Position, RiskMode


DEFAULT_BUDGETS = {Book.CATALYST: 0.25, Book.SWING: 0.50, Book.CORE: 0.20}


def validate_allocations(positions: list[Position], equity: float, cash: float) -> dict:
    if equity <= 0:
        raise ValueError("equity must be positive")
    violations: list[dict] = []
    book_values: dict[Book, float] = defaultdict(float)
    symbol_values: dict[str, float] = defaultdict(float)
    symbol_types: dict[str, str] = {}
    theme_values: dict[str, float] = defaultdict(float)
    for position in positions:
        price = (
            position.market_price
            if position.market_price is not None
            else position.cost_price
        )
        value = position.quantity * price
        book_values[position.book] += value
        symbol_values[position.symbol] += value
        symbol_types[position.symbol] = position.instrument_type
        theme_values[position.theme] += value

    for book, limit in DEFAULT_BUDGETS.items():
        actual = book_values[book] / equity
        if actual > limit + 1e-9:
            violations.append(
                {
                    "rule": "book_budget",
                    "key": book.value,
                    "actual": actual,
                    "limit": limit,
                }
            )
    for symbol, value in symbol_values.items():
        limit = 0.30 if symbol_types[symbol] == "etf" else 0.15
        actual = value / equity
        if actual > limit + 1e-9:
            violations.append(
                {
                    "rule": "single_instrument",
                    "key": symbol,
                    "actual": actual,
                    "limit": limit,
                }
            )
    for theme, value in theme_values.items():
        actual = value / equity
        if actual > 0.70 + 1e-9:
            violations.append(
                {"rule": "theme_through", "key": theme, "actual": actual, "limit": 0.70}
            )
    cash_pct = cash / equity
    if cash_pct < 0.05 - 1e-9:
        violations.append(
            {"rule": "minimum_cash", "key": "cash", "actual": cash_pct, "limit": 0.05}
        )
    return {
        "valid": not violations,
        "violations": violations,
        "book_allocations": {book.value: book_values[book] / equity for book in Book},
        "cash_pct": cash_pct,
    }


def evaluate_portfolio_risk(
    values: PortfolioRiskInput, now: datetime | None = None
) -> PortfolioRiskResult:
    intraday = (values.equity / values.intraday_peak_equity - 1.0) * 100
    daily = (values.equity / values.previous_close_equity - 1.0) * 100
    rolling = (values.equity / values.rolling_20d_peak_equity - 1.0) * 100
    actions: list[str] = []
    if rolling <= -10.0:
        mode = RiskMode.REDUCE_ONLY
        actions.append("20日回撤达到10%，只允许减仓")
    elif daily <= -4.0:
        mode = RiskMode.REDUCE_HIGH_BETA
        actions.append("当日亏损达到4%，降低高Beta暴露")
    elif intraday <= -3.0:
        mode = RiskMode.NO_NEW_POSITIONS
        actions.extend(["禁止新开仓", "催化仓减半"])
    else:
        mode = RiskMode.NORMAL
    return PortfolioRiskResult(
        mode=mode,
        intraday_drawdown_pct=intraday,
        daily_return_pct=daily,
        rolling_20d_drawdown_pct=rolling,
        actions=actions,
        evaluated_at=now or datetime.now().astimezone(),
    )
