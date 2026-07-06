"""V4.4 Kill Switch / Risk Sentinel — Global Circuit Breaker

The Kill Switch is a global circuit breaker that:
  1. Monitors sentinel state from RiskSentinel
  2. Can be triggered by any CRITICAL/BLOCKER rule violation
  3. Blocks ALL pipeline stages when triggered (priority over strategies)
  4. Requires manual release (with optional auto-recovery)
  5. Records all state transitions in the incident log

States:
  ARMED    — Normal operation, monitoring enabled
  TRIGGERED — Circuit breaker active, all actions blocked
  DISABLED — Kill switch disabled (maintenance/override, audited)
  RECOVERING — Auto-recovery in progress
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from factor_lab.risk.incident_log import IncidentLog, IncidentRecord

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Kill Switch State
# ---------------------------------------------------------------------------
class KillSwitchState(Enum):
    """Kill switch operational states."""
    ARMED = "armed"
    TRIGGERED = "triggered"
    DISABLED = "disabled"
    RECOVERING = "recovering"


# ---------------------------------------------------------------------------
# Kill Switch Status
# ---------------------------------------------------------------------------
@dataclass
class KillSwitchStatus:
    """Full status snapshot of the kill switch."""
    state: str = KillSwitchState.ARMED.value
    triggered_at: str = ""
    triggered_by_rule: str = ""
    triggered_by_incident: str = ""
    released_at: str = ""
    released_by: str = ""
    block_all_actions: bool = False
    block_reason: str = ""
    n_actions_blocked: int = 0
    n_incidents: int = 0
    auto_recovery_enabled: bool = True
    last_check_at: str = ""

    def is_triggered(self) -> bool:
        return self.state == KillSwitchState.TRIGGERED.value

    def is_blocked(self) -> bool:
        return self.state in (
            KillSwitchState.TRIGGERED.value,
            KillSwitchState.RECOVERING.value,
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Blocked Action Record
# ---------------------------------------------------------------------------
@dataclass
class BlockedActionRecord:
    """Record of an action blocked by the kill switch."""
    action_id: str = ""
    action_type: str = ""
    action_name: str = ""
    blocked_at: str = ""
    reason: str = ""
    source: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Kill Switch
# ---------------------------------------------------------------------------
class KillSwitch:
    """Global circuit breaker for all pipeline actions.

    Singleton-like — instantiate once and share across the pipeline.

    Usage:
        ks = KillSwitch(incident_log=log)
        ks.arm()

        # Later, when a violation is detected:
        ks.trigger("daily_loss", "Daily loss exceeded 2% threshold")

        # Before any action:
        if ks.is_blocked():
            print(f"Kill switch is {ks.status.state}: {ks.status.block_reason}")
            return

        # When resolved:
        ks.release("admin_user", "Risk resolved")
    """

    def __init__(self, incident_log: Optional[IncidentLog] = None,
                 auto_recovery: bool = True,
                 name: str = "global_kill_switch"):
        self.name = name
        self._state = KillSwitchState.ARMED
        self._incident_log = incident_log or IncidentLog()
        self._triggered_at: str = ""
        self._triggered_by_rule: str = ""
        self._triggered_by_incident: str = ""
        self._released_at: str = ""
        self._released_by: str = ""
        self._release_reason: str = ""
        self._auto_recovery = auto_recovery
        self._disabled_reason: str = ""
        self._disabled_by: str = ""
        self._blocked_actions: list[BlockedActionRecord] = []
        self._block_count: int = 0
        self._last_check_at: str = ""

    # -- State queries ---------------------------------------------------

    @property
    def state(self) -> str:
        return self._state.value

    @property
    def status(self) -> KillSwitchStatus:
        return KillSwitchStatus(
            state=self._state.value,
            triggered_at=self._triggered_at,
            triggered_by_rule=self._triggered_by_rule,
            triggered_by_incident=self._triggered_by_incident,
            released_at=self._released_at,
            released_by=self._released_by,
            block_all_actions=self.is_triggered(),
            block_reason=self._triggered_by_rule
            if self.is_triggered()
            else (self._disabled_reason if self._state == KillSwitchState.DISABLED else ""),
            n_actions_blocked=self._block_count,
            n_incidents=len(self._incident_log.incidents),
            auto_recovery_enabled=self._auto_recovery,
            last_check_at=self._last_check_at or datetime.now(CST).isoformat(),
        )

    def is_armed(self) -> bool:
        return self._state == KillSwitchState.ARMED

    def is_triggered(self) -> bool:
        return self._state == KillSwitchState.TRIGGERED

    def is_disabled(self) -> bool:
        return self._state == KillSwitchState.DISABLED

    def is_blocked(self) -> bool:
        """Check if actions should be blocked.

        Returns True if triggered or recovering.
        """
        return self._state in (
            KillSwitchState.TRIGGERED,
            KillSwitchState.RECOVERING,
        )

    # -- State transitions -----------------------------------------------

    def arm(self):
        """Arm the kill switch (normal monitoring state)."""
        old_state = self._state.value
        self._state = KillSwitchState.ARMED
        self._triggered_at = ""
        self._triggered_by_rule = ""
        self._triggered_by_incident = ""
        self._last_check_at = datetime.now(CST).isoformat()

        self._incident_log.record(
            rule_name="kill_switch",
            severity="info",
            message=f"Kill switch state transition: {old_state} → armed",
            category="system",
            tags=["kill_switch", "state_change"],
        )

    def trigger(self, rule_name: str,
                message: str = "",
                details: dict = None) -> IncidentRecord:
        """Trigger the kill switch — blocks all actions.

        Args:
            rule_name: The rule that triggered the kill switch
            message: Description of why it was triggered
            details: Additional context

        Returns:
            The incident record created
        """
        old_state = self._state.value
        self._state = KillSwitchState.TRIGGERED
        self._triggered_at = datetime.now(CST).isoformat()
        self._triggered_by_rule = rule_name
        self._last_check_at = self._triggered_at

        # Record incident
        incident = self._incident_log.record(
            rule_name=rule_name,
            severity="blocker",
            message=message or f"Kill switch triggered by rule: {rule_name}",
            category="system",
            source="kill_switch",
            details={
                "old_state": old_state,
                "new_state": KillSwitchState.TRIGGERED.value,
                **(details or {}),
            },
            tags=["kill_switch", "triggered"],
        )
        self._triggered_by_incident = incident.incident_id
        return incident

    def release(self, released_by: str = "system",
                reason: str = "",
                force: bool = False) -> bool:
        """Release the kill switch — restore to ARMED.

        Args:
            released_by: Who/what released it
            reason: Why it was released
            force: If False, only release if auto-recovery is enabled

        Returns:
            True if released, False if blocked by policy
        """
        if not self.is_triggered():
            return False

        if not self._auto_recovery and not force:
            return False

        old_state = self._state.value
        self._state = KillSwitchState.ARMED
        self._released_at = datetime.now(CST).isoformat()
        self._released_by = released_by
        self._release_reason = reason

        # Close the triggering incident
        if self._triggered_by_incident:
            self._incident_log.resolve(
                self._triggered_by_incident,
                resolution=reason or "Kill switch released",
                by=released_by,
            )

        self._incident_log.record(
            rule_name="kill_switch",
            severity="info",
            message=f"Kill switch released by {released_by}: {reason}",
            category="system",
            details={
                "old_state": old_state,
                "new_state": KillSwitchState.ARMED.value,
                "released_by": released_by,
            },
            tags=["kill_switch", "released"],
        )
        return True

    def disable(self, disabled_by: str = "admin",
                reason: str = "") -> bool:
        """Disable the kill switch (maintenance override).

        This is audited and should only be used for maintenance.
        """
        if self.is_disabled():
            return False

        old_state = self._state.value
        self._state = KillSwitchState.DISABLED
        self._disabled_by = disabled_by
        self._disabled_reason = reason
        self._last_check_at = datetime.now(CST).isoformat()

        self._incident_log.record(
            rule_name="kill_switch",
            severity="warning",
            message=f"Kill switch DISABLED by {disabled_by}: {reason}",
            category="system",
            details={
                "old_state": old_state,
                "new_state": KillSwitchState.DISABLED.value,
                "disabled_by": disabled_by,
            },
            tags=["kill_switch", "disabled"],
        )
        return True

    def enable(self) -> bool:
        """Re-enable the kill switch after being disabled."""
        if not self.is_disabled():
            return False

        old_state = self._state.value
        self._state = KillSwitchState.ARMED
        self._disabled_by = ""
        self._disabled_reason = ""
        self._last_check_at = datetime.now(CST).isoformat()

        self._incident_log.record(
            rule_name="kill_switch",
            severity="info",
            message=f"Kill switch re-enabled: {old_state} → armed",
            category="system",
            tags=["kill_switch", "enabled"],
        )
        return True

    # -- Action blocking -------------------------------------------------

    def check_action(self, action_type: str, action_name: str,
                     source: str = "", details: dict = None) -> dict:
        """Check if an action is allowed.

        This is the primary method called before any pipeline action.

        Args:
            action_type: Type of action (order, config, signal, etc.)
            action_name: Name of the specific action
            source: Source component
            details: Optional context

        Returns:
            dict with:
              - allowed: bool
              - blocked: bool
              - reason: str
              - kill_switch_state: str
        """
        self._last_check_at = datetime.now(CST).isoformat()

        if self.is_blocked():
            self._block_count += 1
            record = BlockedActionRecord(
                action_id=f"BLK_{self._block_count:06d}",
                action_type=action_type,
                action_name=action_name,
                blocked_at=datetime.now(CST).isoformat(),
                reason=f"Kill switch is {self._state.value}: "
                       f"{self._triggered_by_rule}",
                source=source,
                details=details or {},
            )
            self._blocked_actions.append(record)
            return {
                "allowed": False,
                "blocked": True,
                "reason": record.reason,
                "kill_switch_state": self._state.value,
            }

        return {
            "allowed": True,
            "blocked": False,
            "reason": "",
            "kill_switch_state": self._state.value,
        }

    # -- Recovery --------------------------------------------------------

    def start_recovery(self, recovery_plan: str = "") -> bool:
        """Start auto-recovery process (transition to RECOVERING)."""
        if not self.is_triggered():
            return False

        old_state = self._state.value
        self._state = KillSwitchState.RECOVERING
        self._last_check_at = datetime.now(CST).isoformat()

        self._incident_log.record(
            rule_name="kill_switch",
            severity="info",
            message=f"Kill switch recovery started: {recovery_plan}",
            category="system",
            details={
                "old_state": old_state,
                "new_state": KillSwitchState.RECOVERING.value,
                "recovery_plan": recovery_plan,
            },
            tags=["kill_switch", "recovery"],
        )
        return True

    def complete_recovery(self, released_by: str = "system",
                          reason: str = "") -> bool:
        """Complete recovery — return to ARMED."""
        if self._state != KillSwitchState.RECOVERING:
            return False

        self._state = KillSwitchState.ARMED
        self._released_at = datetime.now(CST).isoformat()
        self._released_by = released_by
        self._triggered_at = ""
        self._triggered_by_rule = ""

        self._incident_log.record(
            rule_name="kill_switch",
            severity="info",
            message=f"Kill switch recovery completed: {reason}",
            category="system",
            tags=["kill_switch", "recovery_complete"],
        )
        return True

    # -- Reports ---------------------------------------------------------

    def get_blocked_action_report(self) -> list[dict]:
        """Get a report of all blocked actions."""
        return [r.to_dict() for r in self._blocked_actions]

    def get_summary(self) -> dict:
        """Get a full summary of kill switch state."""
        return {
            "name": self.name,
            "state": self._state.value,
            "status": self.status.to_dict(),
            "recent_blocked": self._blocked_actions[-10:] if self._blocked_actions else [],
            "open_incidents": self._incident_log.summary(),
            "auto_recovery": self._auto_recovery,
        }

    def to_dict(self) -> dict:
        """Full serialization."""
        return {
            "name": self.name,
            "state": self._state.value,
            "triggered_at": self._triggered_at,
            "triggered_by_rule": self._triggered_by_rule,
            "triggered_by_incident": self._triggered_by_incident,
            "released_at": self._released_at,
            "released_by": self._released_by,
            "auto_recovery": self._auto_recovery,
            "n_actions_blocked": self._block_count,
            "blocked_actions": self.get_blocked_action_report(),
        }
