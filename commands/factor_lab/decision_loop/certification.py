"""Paper/Shadow/live-readiness certification for the decision closed loop."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .models import AdviceMode, Book, Position, QuoteSnapshot
from .profit_guard import ProfitGuard
from .storage import DecisionLoopStore


class DecisionLoopCertification:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()

    def replay_semiconductor_etf_gap_fade(self) -> dict:
        """Replay a +8% gap/flat morning followed by a -7% close."""
        with tempfile.TemporaryDirectory() as root:
            guard = ProfitGuard(DecisionLoopStore(root), structure_confirm_minutes=10)
            position = Position(
                symbol="SEMI_EQUIPMENT_ETF",
                name="科创半导体设备ETF回放",
                quantity=10_000,
                available_quantity=10_000,
                cost_price=1.0,
                instrument_type="etf",
                book=Book.CATALYST,
                theme="semiconductor_equipment",
            )
            base = datetime(2026, 7, 10, 9, 31).astimezone()
            path = [
                (base, 1.08, 1.075),
                (base + timedelta(hours=1), 1.08, 1.075),
                (base + timedelta(hours=3, minutes=29), 1.055, 1.07),
                (base + timedelta(hours=3, minutes=35), 1.045, 1.065),
                (base + timedelta(hours=3, minutes=46), 1.02, 1.06),
                (base + timedelta(hours=5, minutes=29), 0.93, 1.02),
            ]
            events = []
            for observed_at, price, vwap in path:
                events.extend(guard.evaluate(position, QuoteSnapshot(
                    symbol=position.symbol, last_price=price, vwap=vwap,
                    observed_at=observed_at, source="historical_replay", freshness_seconds=0,
                ), AdviceMode.EXECUTABLE))
            actions = [event.action for event in events]
            required = ["warn", "reduce_half", "exit_remaining"]
            passed = all(action in actions for action in required)
            return {
                "case": "semiconductor_etf_gap_flat_then_minus_7_close",
                "passed": passed,
                "actions": [event.model_dump(mode="json") for event in events],
                "assertions": {
                    "two_point_l2": "warn" in actions,
                    "three_point_reduce_half": "reduce_half" in actions,
                    "structure_break_10m_exit": "exit_remaining" in actions,
                    "duplicate_action_count": len(actions) == len(set(actions)),
                },
            }

    def evaluate(self) -> dict:
        base = Path(__file__).resolve().parents[3]
        replay = self.replay_semiconductor_etf_gap_fade()
        paper = self._artifact(base / "data/vnext/paper/latest.json")
        shadow = self._artifact(base / "data/vnext/shadow/latest.json")
        live_enabled = os.environ.get("QMT_LIVE_TRADING_ENABLED") == "1"
        result = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "stage_1_paper_replay": {
                "passed": replay["passed"] and paper.get("status") in {"OK", "PASS"},
                "replay": replay,
                "paper": paper,
            },
            "stage_2_shadow": {
                "passed": shadow.get("status") in {"OK", "PASS"} and bool(shadow.get("continuous_run_verified")),
                "artifact": shadow,
            },
            "stage_3_live_whitelist": {
                "passed": False,
                "live_enabled": live_enabled,
                "reason": "requires explicit small-value broker acceptance after stage 1 and 2",
            },
            "live_activation_allowed": False,
        }
        self.store.write_json("certification/latest.json", result)
        self.store.append_jsonl("certification/history.jsonl", result)
        return result

    @staticmethod
    def _artifact(path: Path) -> dict:
        try:
            import json
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "MISSING", "path": str(path)}
