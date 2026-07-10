"""Continuous Paper/Shadow orchestration using governed brokers only."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from .contracts import TradingMode, now_iso
from .execution import GovernedExecutionEngine, OrderDraft, SafetyContext


def summarize_execution_comparison(cycles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Expose comparison gaps without inventing fills or mark-to-market P/L."""
    runs = list(cycles)
    results = [result for run in runs for result in run.get("results", [])]
    blocked = [result.get("reason", "unknown") for result in results if result.get("status") == "BLOCKED"]
    return {
        "status": "MISSING",
        "orders_observed": len(results),
        "blocked_reasons": blocked,
        "paper_vs_shadow_gap": None,
        "backtest_vs_paper_gap": None,
        "slippage_estimate": None,
        "fill_quality": None,
        "missing_evidence": [
            "real market mark-to-market observations",
            "paired Paper and Shadow fills",
            "continuous account equity history",
        ],
        "real_broker_called": False,
    }


class PaperShadowLoop:
    def __init__(
        self,
        engine: GovernedExecutionEngine,
        broker: Any,
        order_source: Callable[[], Iterable[tuple[OrderDraft, SafetyContext]]],
    ) -> None:
        if engine.mode not in {TradingMode.PAPER, TradingMode.SHADOW}:
            raise ValueError("PaperShadowLoop accepts PAPER or SHADOW mode only")
        self.engine = engine
        self.broker = broker
        self.order_source = order_source

    def run_once(self) -> dict[str, Any]:
        results = [self.engine.submit(self.broker, order, context) for order, context in self.order_source()]
        return {
            "mode": self.engine.mode.value,
            "run_at": now_iso(),
            "orders_seen": len(results),
            "results": results,
            "real_broker_called": False,
        }

    def run_continuous(self, *, interval_seconds: int = 60, max_cycles: int | None = None) -> list[dict[str, Any]]:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        cycles: list[dict[str, Any]] = []
        count = 0
        while max_cycles is None or count < max_cycles:
            cycles.append(self.run_once())
            count += 1
            if max_cycles is not None and count >= max_cycles:
                break
            time.sleep(interval_seconds)
        return cycles
