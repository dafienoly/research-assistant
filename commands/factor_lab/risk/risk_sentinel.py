"""V4.4 Kill Switch / Risk Sentinel — Risk Sentinel

The Risk Sentinel is the unified risk monitoring system that:
  1. Runs periodic checks across all risk dimensions (data, account, execution, loss, system)
  2. Evaluates risk rules via the RuleEvaluator
  3. Triggers the Kill Switch on CRITICAL/BLOCKER violations
  4. Records all events in the IncidentLog
  5. Produces a unified sentinel status

Monitoring dimensions:
  - DATA:      Data freshness, price missing rate, connectivity
  - ACCOUNT:   Account health, balance, position concentration
  - EXECUTION: Order failures, slippage, fill deviations
  - LOSS:      Daily loss, drawdown, overtrading
  - SYSTEM:    Pipeline consistency

The sentinel runs as a background check — it does NOT block actions itself.
Instead, it reports violations and lets the Kill Switch enforce blocking.
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from factor_lab.risk.risk_rules import (
    RiskRule, RuleCheckResult, RuleEvaluator, RuleCategory,
    RuleSeverity, RuleStatus, build_default_rules,
)
from factor_lab.risk.incident_log import IncidentLog, IncidentRecord
from factor_lab.risk.kill_switch import KillSwitch
from factor_lab.data_health import health_check

CST = timezone(timedelta(hours=8))
STATE_DIR = Path("/mnt/d/HermesData/risk_sentinel")


# ---------------------------------------------------------------------------
# Sentinel Status
# ---------------------------------------------------------------------------
@dataclass
class SentinelStatus:
    """Full status of the risk sentinel after a check cycle."""
    status: str = "healthy"  # healthy / degraded / critical / blocked
    last_check_at: str = ""
    n_rules_checked: int = 0
    n_violations: int = 0
    n_blockers: int = 0
    n_open_incidents: int = 0
    kill_switch_state: str = "armed"
    dimensions: dict = field(default_factory=lambda: {
        "data": {"status": "healthy", "violations": 0},
        "account": {"status": "healthy", "violations": 0},
        "execution": {"status": "healthy", "violations": 0},
        "loss": {"status": "healthy", "violations": 0},
        "system": {"status": "healthy", "violations": 0},
    })
    checks: list = field(default_factory=list)
    incident_summary: dict = field(default_factory=dict)

    def is_healthy(self) -> bool:
        return self.status == "healthy"

    def is_blocked(self) -> bool:
        return self.status == "blocked" or self.kill_switch_state == "triggered"

    def is_critical(self) -> bool:
        return self.status in ("critical", "blocked")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Sentinel Check Cycle
# ---------------------------------------------------------------------------
@dataclass
class SentinelCheck:
    """Record of a single sentinel check cycle."""
    cycle_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    n_rules: int = 0
    n_violations: int = 0
    n_blockers: int = 0
    kill_switch_triggered: bool = False
    incidents_created: int = 0
    status: str = "healthy"
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Risk Sentinel
# ---------------------------------------------------------------------------
class RiskSentinel:
    """Unified risk monitoring sentinel.

    Orchestrates rule evaluation, incident recording, and kill switch
    triggering across all risk dimensions.

    Usage:
        sentinel = RiskSentinel()
        sentinel.arm()

        # Run a full check cycle
        result = sentinel.check_all(contexts={...})

        # Check a specific dimension
        result = sentinel.check_dimension("data", context)

        # Get status
        status = sentinel.get_status()
    """

    def __init__(self,
                 rules: Optional[list[RiskRule]] = None,
                 incident_log: Optional[IncidentLog] = None,
                 kill_switch: Optional[KillSwitch] = None,
                 auto_trigger_kill_switch: bool = True,
                 name: str = "default",
                 anomaly_detector: Optional["DataAnomalyDetector"] = None):
        """Initialize the risk sentinel.

        Args:
            rules: List of RiskRule to evaluate. If None, uses defaults.
            incident_log: IncidentLog instance. If None, creates one.
            kill_switch: KillSwitch instance. If None, creates one.
            auto_trigger_kill_switch: If True, automatically triggers
                kill switch on BLOCKER violations.
            name: Sentinel name for identification.
            anomaly_detector: DataAnomalyDetector instance (V3.5.4).
        """
        self.name = name
        self._rules: dict[str, RiskRule] = {}
        self._evaluator = RuleEvaluator()
        self._incident_log = incident_log or IncidentLog()
        self._kill_switch = kill_switch or KillSwitch(
            incident_log=self._incident_log,
        )
        self._auto_trigger = auto_trigger_kill_switch
        self._checks: list[SentinelCheck] = []
        self._last_status: Optional[SentinelStatus] = None
        self._check_counter: int = 0
        self.anomaly_detector = anomaly_detector  # V3.5.4
        self.last_market_ts: Optional[datetime] = None  # V3.5.4

        # Daemon mode (background thread)
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._interval: int = 30
        self._daemon_lock: threading.Lock = threading.Lock()

        # Load rules
        if rules is not None:
            for r in rules:
                self._rules[r.name] = r
        else:
            for r in build_default_rules():
                self._rules[r.name] = r

    # -- Properties ------------------------------------------------------

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    @property
    def incident_log(self) -> IncidentLog:
        return self._incident_log

    @property
    def rules(self) -> list[RiskRule]:
        return list(self._rules.values())

    # -- Rule management -------------------------------------------------

    def add_rule(self, rule: RiskRule):
        """Add a risk rule to the sentinel."""
        self._rules[rule.name] = rule

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a risk rule by name."""
        if rule_name in self._rules:
            del self._rules[rule_name]
            return True
        return False

    def get_rule(self, rule_name: str) -> Optional[RiskRule]:
        """Get a rule by name."""
        return self._rules.get(rule_name)

    def enable_rule(self, rule_name: str) -> bool:
        """Enable a rule by name."""
        rule = self._rules.get(rule_name)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable_rule(self, rule_name: str) -> bool:
        """Disable a rule by name."""
        rule = self._rules.get(rule_name)
        if rule:
            rule.enabled = False
            return True
        return False

    def register_custom_evaluator(self, rule_name: str,
                                  fn) -> bool:
        """Register a custom evaluator function for a rule."""
        if rule_name in self._rules:
            self._evaluator.register_evaluator(rule_name, fn)
            return True
        return False

    # -- Sentinel operations ---------------------------------------------

    def arm(self):
        """Arm the sentinel — enable monitoring and arm the kill switch."""
        self._kill_switch.arm()

    def check_all(self, contexts: dict[str, Any] = None) -> SentinelStatus:
        """Run a full check cycle across ALL dimensions.

        Args:
            contexts: Dict mapping dimension names to context data.
                      E.g. {"data": {...}, "account": {...}}

        Returns:
            SentinelStatus with full check results.
        """
        self._check_counter += 1
        contexts = contexts or {}
        started_at = datetime.now(CST).isoformat()

        check = SentinelCheck(
            cycle_id=f"CHK_{self._check_counter:06d}_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}",
            started_at=started_at,
        )

        all_results: list[RuleCheckResult] = []
        dimension_results: dict[str, list[RuleCheckResult]] = {
            dim: [] for dim in ["data", "account", "execution", "loss", "system"]
        }
        incidents_created = 0
        kill_switch_triggered = False

        # Evaluate each dimension
        for rule in self._rules.values():
            if not rule.enabled:
                continue

            context = contexts.get(rule.category, {})
            result = self._evaluator.evaluate(rule, context)
            all_results.append(result)

            if rule.category in dimension_results:
                dimension_results[rule.category].append(result)

            # Handle violations
            if result.is_violation():
                # Record incident for violations
                incident = self._incident_log.record(
                    rule_name=result.rule_name,
                    severity=result.severity,
                    message=result.message,
                    category=result.category,
                    source="risk_sentinel",
                    details={
                        "threshold": result.threshold,
                        "actual_value": result.actual_value,
                        "consecutive_failures": result.consecutive_failures,
                        "triggered_by": result.triggered_by,
                    },
                    tags=[result.rule_name, result.category, result.status],
                )
                incidents_created += 1

                # Auto-trigger kill switch on BLOCKER
                if (self._auto_trigger
                        and result.severity == RuleSeverity.BLOCKER.value
                        and not self._kill_switch.is_triggered()):
                    self._kill_switch.trigger(
                        rule_name=result.rule_name,
                        message=result.message,
                        details={
                            "check_cycle": check.cycle_id,
                            "actual_value": result.actual_value,
                            "threshold": result.threshold,
                        },
                    )
                    kill_switch_triggered = True

        # Build dimension status
        dim_status = {}
        for dim, results in dimension_results.items():
            violations = [r for r in results if r.is_violation()]
            blockers = [r for r in violations if r.is_blocker()]
            if blockers:
                dim_status[dim] = "blocked"
            elif violations:
                dim_status[dim] = "violated"
            else:
                dim_status[dim] = "healthy"

        # Compute overall status
        n_violations = sum(1 for r in all_results if r.is_violation())
        n_blockers = sum(1 for r in all_results if r.is_blocker())
        n_total = len(all_results)

        if self._kill_switch.is_triggered():
            overall_status = "blocked"
        elif n_blockers > 0:
            overall_status = "critical"
        elif n_violations > 0:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        completed_at = datetime.now(CST).isoformat()

        # Update check record
        check.n_rules = n_total
        check.n_violations = n_violations
        check.n_blockers = n_blockers
        check.kill_switch_triggered = kill_switch_triggered
        check.incidents_created = incidents_created
        check.status = overall_status
        check.completed_at = completed_at
        self._checks.append(check)

        # Build status
        self._last_status = SentinelStatus(
            status=overall_status,
            last_check_at=completed_at,
            n_rules_checked=n_total,
            n_violations=n_violations,
            n_blockers=n_blockers,
            n_open_incidents=len(self._incident_log.get_open_incidents()),
            kill_switch_state=self._kill_switch.state,
            dimensions={
                dim: {"status": dim_status.get(dim, "unknown"),
                       "violations": len([
                           r for r in all_results
                           if r.category == dim and r.is_violation()
                       ])}
                for dim in ["data", "account", "execution", "loss", "system"]
            },
            checks=[r.to_dict() for r in all_results
                    if r.is_violation()],
            incident_summary=self._incident_log.summary(),
        )

        return self._last_status

    def check_dimension(self, dimension: str,
                        context: Any = None) -> dict[str, Any]:
        """Check a single risk dimension.

        Args:
            dimension: One of "data", "account", "execution", "loss", "system"
            context: Context data for rule evaluation

        Returns:
            dict with dimension check results
        """
        context = context or {}
        dimension_rules = [
            r for r in self._rules.values()
            if r.category == dimension and r.enabled
        ]

        results = self._evaluator.evaluate_rules(dimension_rules, context)
        violations = [r for r in results if r.is_violation()]
        blockers = [r for r in violations if r.is_blocker()]

        for result in violations:
            self._incident_log.record(
                rule_name=result.rule_name,
                severity=result.severity,
                message=result.message,
                category=dimension,
                source="risk_sentinel",
            )

        if blockers and self._auto_trigger:
            self._kill_switch.trigger(
                rule_name=violations[0].rule_name,
                message=f"Dimension {dimension} has {len(blockers)} blocker(s)",
            )

        return {
            "dimension": dimension,
            "status": (
                "blocked" if blockers
                else "violated" if violations
                else "passed"
            ),
            "n_rules": len(dimension_rules),
            "n_violations": len(violations),
            "n_blockers": len(blockers),
            "violations": [r.to_dict() for r in violations],
            "results": [r.to_dict() for r in results],
        }

    def check_data(self, context: dict = None) -> dict:
        """Check data dimension only."""
        return self.check_dimension(RuleCategory.DATA.value, context)

    def check_account(self, context: dict = None) -> dict:
        """Check account dimension only."""
        return self.check_dimension(RuleCategory.ACCOUNT.value, context)

    def check_execution(self, context: dict = None) -> dict:
        """Check execution dimension only."""
        return self.check_dimension(RuleCategory.EXECUTION.value, context)

    def check_loss(self, context: dict = None) -> dict:
        """Check loss dimension only."""
        return self.check_dimension(RuleCategory.LOSS.value, context)

    def check_system(self, context: dict = None) -> dict:
        """Check system dimension only."""
        return self.check_dimension(RuleCategory.SYSTEM.value, context)

    # -- Status & reporting ----------------------------------------------

    def get_status(self) -> SentinelStatus:
        """Get the latest sentinel status.

        Returns the last check result, or a default "unknown" status
        if no check has been run yet.
        """
        if self._last_status:
            return self._last_status

        return SentinelStatus(
            status="unknown",
            last_check_at="",
            n_rules_checked=0,
            kill_switch_state=self._kill_switch.state,
            incident_summary=self._incident_log.summary(),
        )

    def get_summary(self) -> dict:
        """Get a concise summary of sentinel state."""
        status = self.get_status()
        return {
            "sentinel": self.name,
            "status": status.status,
            "kill_switch": self._kill_switch.state,
            "last_check": status.last_check_at,
            "n_rules": len(self._rules),
            "n_violations": status.n_violations,
            "n_blockers": status.n_blockers,
            "dimensions": status.dimensions,
            "incidents": status.incident_summary,
        }

    def get_check_history(self, n: int = 20) -> list[dict]:
        """Get recent check cycle history."""
        return [c.to_dict() for c in self._checks[-n:]]

    def to_dict(self) -> dict:
        """Full serialization."""
        return {
            "name": self.name,
            "status": self.get_summary(),
            "n_rules": len(self._rules),
            "rules": {name: rule.to_dict()
                      for name, rule in self._rules.items()},
            "kill_switch": self._kill_switch.to_dict(),
            "incident_log": self._incident_log.summary(),
            "checks": self.get_check_history(5),
        }

    # ------------------------------------------------------------------ #
    #  Data freshness & connectivity checks
    # ------------------------------------------------------------------ #

    def check_data_freshness(self) -> dict:
        """Check data freshness by calling data_health.health_check().

        Returns a dict with:
          - checked_at: ISO timestamp
          - healthy: bool (all sources healthy)
          - total_sources: int
          - healthy_sources: int
          - unhealthy_sources: int
          - details: list of source health info
        """
        try:
            result = health_check()
            self._incident_log.record(
                rule_name="data_freshness",
                severity="info",
                message=f"Data freshness check: {result.get('healthy', 0)}/"
                        f"{result.get('total_sources', 0)} sources healthy",
                category="data",
                source="risk_sentinel",
                tags=["data_freshness", "check"],
            )
            # If unhealthy sources exist, trigger a warning-level incident
            unhealthy = result.get("unhealthy", 0)
            if unhealthy > 0:
                self._incident_log.record(
                    rule_name="data_freshness",
                    severity="warning",
                    message=f"{unhealthy} data source(s) unhealthy",
                    category="data",
                    source="risk_sentinel",
                    details={"unhealthy_sources": [
                        s for s in result.get("sources", [])
                        if not s.get("healthy", False)
                    ]},
                    tags=["data_freshness", "unhealthy"],
                )
            return result
        except Exception as exc:
            error_result = {
                "checked_at": datetime.now(CST).isoformat(),
                "healthy": False,
                "error": str(exc),
                "total_sources": 0,
                "healthy_sources": 0,
                "unhealthy_sources": 0,
                "sources": [],
            }
            self._incident_log.record(
                rule_name="data_freshness",
                severity="error",
                message=f"Data freshness check failed: {exc}",
                category="data",
                source="risk_sentinel",
                tags=["data_freshness", "error"],
            )
            return error_result

    def check_market_connectivity(self) -> dict:
        """Check market data connectivity.

        Performs a connectivity probe on registered data sources.
        Returns a dict with connectivity status per source.
        """
        try:
            result = health_check()
            # Derive connectivity from health status
            sources = result.get("sources", [])
            connected = sum(1 for s in sources if s.get("healthy", False))
            total = len(sources)

            connectivity_result = {
                "checked_at": datetime.now(CST).isoformat(),
                "connected": connected,
                "total": total,
                "all_connected": connected == total if total > 0 else False,
                "sources": [
                    {
                        "source_id": s.get("source_id", ""),
                        "name": s.get("name", ""),
                        "connected": s.get("healthy", False),
                    }
                    for s in sources
                ],
            }

            if not connectivity_result["all_connected"]:
                disconnected = [s for s in sources if not s.get("healthy", False)]
                self._incident_log.record(
                    rule_name="market_connectivity",
                    severity="critical" if total > 0 and connected == 0 else "warning",
                    message=f"Market connectivity: {connected}/{total} sources connected",
                    category="data",
                    source="risk_sentinel",
                    details={"disconnected_sources": [
                        {"id": s.get("source_id"), "name": s.get("name")}
                        for s in disconnected
                    ]},
                    tags=["market_connectivity", "check"],
                )

            return connectivity_result
        except Exception as exc:
            return {
                "checked_at": datetime.now(CST).isoformat(),
                "connected": 0,
                "total": 0,
                "all_connected": False,
                "error": str(exc),
                "sources": [],
            }

    # ------------------------------------------------------------------ #
    #  Run cycle — unified check + persistence
    # ------------------------------------------------------------------ #

    def run_cycle(self, contexts: dict[str, Any] = None) -> dict:
        """Execute one full check cycle.

        Combines:
          1. Rule evaluation via check_all()
          2. Data freshness check
          3. Market connectivity check
          4. State persistence to disk

        Args:
            contexts: Optional dict of dimension -> context for rule evaluation.

        Returns:
            dict with full cycle state including all checks.
        """
        contexts = contexts or {}
        started_at = datetime.now(CST).isoformat()

        # 1. Rule evaluation
        status = self.check_all(contexts)

        # 2. Data freshness
        freshness = self.check_data_freshness()

        # 3. Market connectivity
        connectivity = self.check_market_connectivity()

        # 4. 异常检测 (V3.5.4 新增)
        anomaly = {}
        if self.anomaly_detector:
            try:
                if self.last_market_ts:
                    lag = self.anomaly_detector.check_market_lag(self.last_market_ts)
                    anomaly["market_lag"] = lag
            except Exception as exc:
                anomaly["error"] = str(exc)

        # 5. Build state dict
        state = {
            "sentinel_name": self.name,
            "cycle_started_at": started_at,
            "completed_at": datetime.now(CST).isoformat(),
            "overall_status": status.status,
            "kill_switch_state": self._kill_switch.state,
            "kill_switch_triggered": self._kill_switch.is_triggered(),
            "n_rules_checked": status.n_rules_checked,
            "n_violations": status.n_violations,
            "n_blockers": status.n_blockers,
            "n_open_incidents": status.n_open_incidents,
            "dimensions": status.dimensions,
            "data_freshness": freshness,
            "market_connectivity": connectivity,
            "anomaly": anomaly,
            "last_check_at": status.last_check_at,
        }

        # Persist state
        self._save_state(state)

        # V3.5.5: 检测到 blocker 时发送风控摘要（每天最多1次）
        blockers = [
            r for r in (getattr(status, "checks", None) or [])
            if isinstance(r, dict) and r.get("severity") == "blocker"
        ]
        if blockers and self._should_send_daily_summary():
            try:
                from factor_lab.notify import notify_risk_summary
                summary = {
                    "date": datetime.now(CST).strftime("%Y-%m-%d"),
                    "total_checks": status.n_rules_checked,
                    "passed": status.n_rules_checked - status.n_violations,
                    "warnings": status.n_violations - status.n_blockers,
                    "blockers": status.n_blockers,
                    "kill_switch_state": self._kill_switch.state,
                    "top_events": [
                        str(r.get("message", ""))
                        for r in blockers[:5]
                    ],
                }
                notify_risk_summary(summary)
            except Exception:
                pass

        return state

    # ------------------------------------------------------------------ #
    #  Daemon mode (background thread)
    # ------------------------------------------------------------------ #

    def start(self, interval_seconds: int = 30):
        """Start the sentinel daemon in a background thread.

        Args:
            interval_seconds: Seconds between check cycles (default: 30).
        """
        with self._daemon_lock:
            if self._running:
                return  # Already running

            self._interval = interval_seconds
            self._running = True
            self._thread = threading.Thread(
                target=self._daemon_loop,
                name=f"RiskSentinel-{self.name}",
                daemon=True,
            )
            self._thread.start()

            self._incident_log.record(
                rule_name="risk_sentinel",
                severity="info",
                message=f"RiskSentinel daemon started (interval={interval_seconds}s)",
                category="system",
                source="risk_sentinel",
                tags=["risk_sentinel", "daemon", "start"],
            )

    def stop(self):
        """Stop the sentinel daemon gracefully."""
        with self._daemon_lock:
            if not self._running:
                return

            self._running = False

            self._incident_log.record(
                rule_name="risk_sentinel",
                severity="info",
                message="RiskSentinel daemon stopped",
                category="system",
                source="risk_sentinel",
                tags=["risk_sentinel", "daemon", "stop"],
            )

    def is_running(self) -> bool:
        """Check if the daemon is currently running."""
        return self._running

    def _daemon_loop(self):
        """Internal daemon loop — runs check cycles at fixed intervals."""
        while self._running:
            try:
                self.run_cycle()
            except Exception as exc:
                self._incident_log.record(
                    rule_name="risk_sentinel",
                    severity="error",
                    message=f"Daemon cycle error: {exc}",
                    category="system",
                    source="risk_sentinel",
                    details={"error": str(exc)},
                    tags=["risk_sentinel", "error"],
                )

            # Sleep in small increments so stop() is responsive
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    # V3.5.5: 每日风控摘要冷却
    def _should_send_daily_summary(self) -> bool:
        """检查是否可以发送每日风控摘要（每天最多 1 次）。"""
        today = datetime.now(CST).strftime("%Y-%m-%d")
        if getattr(self, '_last_summary_date', None) != today:
            self._last_summary_date = today
            return True
        return False

    # ------------------------------------------------------------------ #
    #  State persistence
    # ------------------------------------------------------------------ #

    def _save_state(self, state: dict):
        """Persist sentinel state to state.json on disk."""
        try:
            os.makedirs(str(STATE_DIR), exist_ok=True)
            path = STATE_DIR / "state.json"
            with open(str(path), "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Best-effort persistence; never crash on write failure

    def get_state(self) -> dict:
        """Return the current sentinel state snapshot.

        Reads from the persisted state.json if available, otherwise
        builds a live state from in-memory data.
        """
        # Try to read persisted state first
        try:
            path = STATE_DIR / "state.json"
            if path.exists():
                with open(str(path), "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

        # Fall back to live data
        status = self.get_status()
        return {
            "sentinel_name": self.name,
            "completed_at": datetime.now(CST).isoformat(),
            "overall_status": status.status,
            "kill_switch_state": self._kill_switch.state,
            "kill_switch_triggered": self._kill_switch.is_triggered(),
            "n_rules_checked": status.n_rules_checked,
            "n_violations": status.n_violations,
            "n_blockers": status.n_blockers,
            "n_open_incidents": status.n_open_incidents,
            "dimensions": status.dimensions,
            "last_check_at": status.last_check_at,
        }
