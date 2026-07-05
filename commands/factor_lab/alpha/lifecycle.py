"""Alpha Lifecycle V3.0 — 状态管理"""
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

ALPHA_LIFECYCLE = [
    "draft",
    "registered",
    "backtest_ready",
    "backtested",
    "walk_forward_ready",
    "paper_ready",
    "paper_active",
    "promotion_candidate",
    "live_ready",
    "live_active",
    "retired",
    "rejected",
]

TRANSITIONS = {
    "draft": ["registered", "retired", "rejected"],
    "registered": ["backtest_ready", "retired", "rejected"],
    "backtest_ready": ["backtested", "retired", "rejected"],
    "backtested": ["walk_forward_ready", "paper_ready", "retired", "rejected"],
    "walk_forward_ready": ["paper_ready", "retired", "rejected"],
    "paper_ready": ["paper_active", "retired", "rejected"],
    "paper_active": ["promotion_candidate", "retired", "rejected"],
    "promotion_candidate": ["live_ready", "retired", "rejected"],
    "live_ready": ["live_active", "retired", "rejected"],
    "live_active": ["retired", "rejected"],
    "retired": [],
    "rejected": [],
}


class AlphaLifecycle:
    def __init__(self, alpha_dir: str):
        self.alpha_dir = alpha_dir

    def can_transition(self, current: str, target: str) -> bool:
        return target in TRANSITIONS.get(current, [])

    def transition(self, current: str, target: str) -> dict:
        if not self.can_transition(current, target):
            return {"error": f"Invalid transition: {current} -> {target}", "success": False}
        return {
            "from": current,
            "to": target,
            "timestamp": datetime.now(CST).isoformat(),
            "success": True,
        }
