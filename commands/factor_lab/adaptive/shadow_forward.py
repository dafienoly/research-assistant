"""Canonical-only Shadow Forward adapters.

The former module generated synthetic returns, fixed symbols, and fabricated
risk/order reports.  Those paths are retired.  This compatibility module keeps
the public names used by older callers, but every missing-data path is
fail-closed and no synthetic evidence is persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


class ShadowForwardEngine:
    """Read-only readiness adapter for the live readiness gate."""

    def __init__(self, state_path: str | Path | None = None):
        self.state_path = Path(state_path) if state_path else None

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "BLOCKED",
            "shadow_days": 0,
            "correlation_with_paper": 0.0,
            "deviation_pct": None,
            "reason": (
                "continuous canonical Shadow observations, paired fills and "
                "equity history are not available"
            ),
            "source": str(self.state_path) if self.state_path else None,
        }


def run_shadow_forward(
    run_id=None,
    latest=False,
    start_date=None,
    end_date=None,
    last_n=None,
) -> dict[str, Any]:
    """Retired legacy generator; never creates Shadow evidence."""
    return {
        "status": "BLOCKED",
        "error": (
            "legacy shadow-forward generator retired; canonical market marks, "
            "paired Paper/Shadow fills and continuous equity are required"
        ),
        "shadow_only": True,
        "auto_apply": False,
        "no_live_trade": True,
        "broker_adapter_called": False,
        "miniqmt_called": False,
    }


class StandingShadowForward:
    """Compatibility runner that computes only from injected real observations."""

    def __init__(
        self,
        strategy_name: str = "ret5_ma20_gate",
        output_dir: str | None = None,
        baseline_name: str = "equal_weight",
        universe_symbols: list[str] | None = None,
        top_n: int = 20,
    ):
        self.strategy_name = strategy_name
        self.baseline_name = baseline_name
        self.universe_symbols = universe_symbols or []
        self.top_n = top_n
        self.output_dir = Path(output_dir) if output_dir else None
        self.results: list[dict[str, Any]] = []

    def _fetch_universe(self, signal_date: str) -> list[str]:
        """Return only an explicitly supplied or canonical discovered universe."""
        return list(self.universe_symbols)

    def _fetch_strategy_candidates(self, signal_date: str) -> list[str]:
        """No fallback: candidates must come from a real versioned signal run."""
        return []

    def _compute_stock_returns(self, symbols: list[str], date: str) -> dict[str, float]:
        """Provider-specific loading belongs to DataHub; empty means blocked."""
        return {}

    def _fetch_csi300_return(self, date: str) -> float | None:
        """Provider-specific benchmark loading belongs to DataHub."""
        return None

    def run_daily(self, signal_date: str | None = None) -> dict[str, Any]:
        date = signal_date or datetime.now(CST).strftime("%Y-%m-%d")
        candidates = list(dict.fromkeys(self._fetch_strategy_candidates(date)))
        universe = list(dict.fromkeys(self._fetch_universe(date)))
        returns = self._compute_stock_returns(
            sorted(set(candidates + universe)), date
        )
        benchmark = self._fetch_csi300_return(date)
        missing = sorted(set(candidates + universe) - set(returns))
        shadow_return = (
            float(np.mean([returns[s] for s in candidates]))
            if candidates and all(s in returns for s in candidates)
            else None
        )
        equal_return = (
            float(np.mean([returns[s] for s in universe]))
            if universe and all(s in returns for s in universe)
            else None
        )
        complete = (
            shadow_return is not None
            and equal_return is not None
            and benchmark is not None
            and not missing
        )
        result = {
            "date": date,
            "status": "OK" if complete else "BLOCKED",
            "blocking_reason": None if complete else "incomplete_real_market_returns",
            "missing_symbols": missing,
            "shadow_return": round(shadow_return, 6) if complete else None,
            "equal_weight_return": round(equal_return, 6) if complete else None,
            "csi300_return": round(benchmark, 6) if complete else None,
            "excess_vs_equal": round(shadow_return - equal_return, 6) if complete else None,
            "excess_vs_csi300": round(shadow_return - benchmark, 6) if complete else None,
            "n_strategy_stocks": len(candidates),
            "n_universe": len(universe),
            "strategy_name": self.strategy_name,
            "baseline_name": self.baseline_name,
            "generated_at": datetime.now(CST).isoformat(),
            "evidence_status": "canonical_only",
        }
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.results.append(result)
        return result

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "OK" if self.results else "BLOCKED",
            "shadow_days": len(self.results),
            "correlation_with_paper": 0.0,
            "deviation_pct": None,
            "reason": None if self.results else "no continuous canonical Shadow observations",
        }

    def get_rolling_performance(self, window: int = 30) -> dict[str, Any]:
        return {
            "status": "BLOCKED",
            "window_days": window,
            "n_records": len(self.results),
            "reason": "continuous canonical Shadow history is incomplete",
        }

    def check_alert(self, consecutive_loss_days: int = 5, window: int = 30) -> dict[str, Any]:
        return {
            "status": "BLOCKED",
            "alert": False,
            "reason": "insufficient canonical Shadow history",
            "consecutive_loss_days": consecutive_loss_days,
            "window_days": window,
        }

    def generate_html_report(self, window: int = 30) -> str:
        raise RuntimeError("Shadow report blocked until canonical history is complete")

    def print_report(self, window: int = 30) -> None:
        print(self.get_rolling_performance(window))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "baseline_name": self.baseline_name,
            "n_records": len(self.results),
            "last_date": self.results[-1]["date"] if self.results else None,
            "status": "OK" if self.results else "BLOCKED",
            "evidence_status": "canonical_only",
        }
