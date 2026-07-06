"""V4.0 Controlled Live Pipeline — Risk Boundary Doc

Defines hard safety boundaries that MUST NOT be crossed.
These are the "auto_apply=False, no_live_trade=True" enforcement rules.

Key boundaries:
  1. No automatic modification of live config
  2. No broker adapter calls from automated pipelines
  3. No real order submission
  4. All proposal changes require human approval
  5. Rollback plan required for all config changes
  6. Kill switch must be operational before live consideration
  7. Paper environment is the highest auto-execution level
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Risk boundary data class
# ---------------------------------------------------------------------------
@dataclass
class RiskBoundary:
    """A single risk boundary definition."""
    name: str
    severity: str = "blocker"   # "blocker" | "warning" | "info"
    description: str = ""
    policy: str = ""
    enforced: bool = True
    auto_blocked_methods: list = field(default_factory=list)
    requires_human: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "description": self.description,
            "policy": self.policy,
            "enforced": self.enforced,
            "auto_blocked_methods": self.auto_blocked_methods,
            "requires_human": self.requires_human,
        }


# ---------------------------------------------------------------------------
# Risk policies
# ---------------------------------------------------------------------------
@dataclass
class RiskPolicy:
    """Risk policy — a named set of risk boundaries."""
    name: str
    version: str = "V4.0"
    boundaries: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def add_boundary(self, boundary: RiskBoundary):
        self.boundaries.append(boundary)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "boundaries": [b.to_dict() for b in self.boundaries],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Forbidden action registry
# ---------------------------------------------------------------------------
class ForbiddenActionRegistry:
    """Registry of actions that are forbidden in the automated pipeline.

    These actions must NEVER be called from auto-execution paths.
    They are only allowed with explicit human confirmation (and even then,
    V4.0 design blocks live execution).
    """

    FORBIDDEN_METHODS = [
        # Broker / exchange interaction
        "send_order",
        "place_order",
        "cancel_order",
        "execute_trade",
        "auto_trade",
        "broker_trade",
        # MiniQMT interaction
        "miniqmt_buy",
        "miniqmt_sell",
        "miniqmt_cancel",
        "miniqmt_position",
        # Config modification (auto)
        "auto_apply_config",
        "auto_modify_live_config",
        "auto_switch_strategy",
        # Order submission (live)
        "submit_live_order",
        "batch_submit_live_orders",
        # Account operations
        "transfer_in",
        "transfer_out",
        "withdraw",
    ]

    @classmethod
    def is_forbidden(cls, method_name: str) -> bool:
        return method_name in cls.FORBIDDEN_METHODS

    @classmethod
    def get_forbidden_list(cls) -> list:
        return list(cls.FORBIDDEN_METHODS)


# ---------------------------------------------------------------------------
# Default risk policy
# ---------------------------------------------------------------------------
def build_default_risk_policy() -> RiskPolicy:
    """Build the default V4.0 risk policy with all standard boundaries."""
    policy = RiskPolicy(
        name="V4.0 Default Risk Policy",
        version="V4.0",
    )

    # Boundary 1: No live trading
    policy.add_boundary(RiskBoundary(
        name="no_live_trade",
        severity="blocker",
        description="自动流程不得执行真实交易",
        policy="All automated pipelines must set no_live_trade=True. "
               "Any action that would result in a real trade is blocked.",
        enforced=True,
        auto_blocked_methods=["send_order", "place_order", "broker_trade",
                              "miniqmt_buy", "miniqmt_sell"],
        requires_human=True,
    ))

    # Boundary 2: No auto-apply
    policy.add_boundary(RiskBoundary(
        name="no_auto_apply",
        severity="blocker",
        description="自动流程不得修改配置",
        policy="All pipeline actions must have auto_apply=False. "
               "Config changes require human review and approval.",
        enforced=True,
        auto_blocked_methods=["auto_apply_config", "auto_modify_live_config"],
        requires_human=True,
    ))

    # Boundary 3: Human approval gate
    policy.add_boundary(RiskBoundary(
        name="human_approval_required",
        severity="blocker",
        description="关键路径必须人工审批",
        policy="Proposal-to-paper, paper-to-readiness, and readiness-to-live "
               "transitions all require recorded human approval.",
        enforced=True,
        auto_blocked_methods=[],
        requires_human=True,
    ))

    # Boundary 4: Rollback plan mandatory
    policy.add_boundary(RiskBoundary(
        name="rollback_required",
        severity="blocker",
        description="所有配置变更必须有回滚计划",
        policy="Every ProposalContract must include a rollback_plan. "
               "Proposals without rollback plans are rejected.",
        enforced=True,
        auto_blocked_methods=[],
        requires_human=False,
    ))

    # Boundary 5: No broker adapter
    policy.add_boundary(RiskBoundary(
        name="no_broker_adapter",
        severity="blocker",
        description="自动流程不得调用 broker 适配器",
        policy="Broker adapters (including MiniQMT) must not be called "
               "from any automated pipeline stage. V4.0 is design only.",
        enforced=True,
        auto_blocked_methods=["broker_trade", "miniqmt_buy", "miniqmt_sell",
                              "miniqmt_cancel", "miniqmt_position"],
        requires_human=True,
    ))

    # Boundary 6: Evidence traceability
    policy.add_boundary(RiskBoundary(
        name="evidence_traceability",
        severity="warning",
        description="所有决策必须有可追溯证据",
        policy="Every approval decision must reference supporting evidence. "
               "Decisions without evidence trace are flagged.",
        enforced=True,
        auto_blocked_methods=[],
        requires_human=False,
    ))

    # Boundary 7: Max daily loss
    policy.add_boundary(RiskBoundary(
        name="max_daily_loss",
        severity="warning",
        description="最大日亏损限制",
        policy="Paper trading should respect max_daily_loss_pct config. "
               "If exceeded, subsequent actions are blocked.",
        enforced=True,
        auto_blocked_methods=[],
        requires_human=True,
    ))

    # Boundary 8: Live config immutable
    policy.add_boundary(RiskBoundary(
        name="live_config_immutable",
        severity="blocker",
        description="实盘配置不可变 (V4.0 设计阶段)",
        policy="Live configuration must not be modified during design phase. "
               "All config changes target paper environment only.",
        enforced=True,
        auto_blocked_methods=["auto_modify_live_config"],
        requires_human=True,
    ))

    # Boundary 9: No fallback to demo data
    policy.add_boundary(RiskBoundary(
        name="no_demo_fallback",
        severity="warning",
        description="正式输出必须有真实数据源",
        policy="Pipeline outputs must contain data lineage. "
               "Demo/fallback data must be explicitly marked as test_only.",
        enforced=True,
        auto_blocked_methods=[],
        requires_human=False,
    ))

    return policy


# ---------------------------------------------------------------------------
# Boundary enforcer
# ---------------------------------------------------------------------------
class BoundaryEnforcer:
    """Enforces risk boundaries on pipeline actions.

    Usage:
        enforcer = BoundaryEnforcer()
        enforcer.load_policy(policy)
        result = enforcer.check_action("send_order", context)
        if not result["allowed"]:
            print(f"Blocked: {result['reason']}")
    """

    def __init__(self):
        self.policy: Optional[RiskPolicy] = None
        self.check_history: list = []
        self.blocked_actions: list = []
        self.warnings: list = []

    def load_policy(self, policy: RiskPolicy):
        """Load a risk policy for enforcement."""
        self.policy = policy

    def check_action(self, method_name: str, context: dict = None) -> dict:
        """Check whether an action is allowed under current policy.

        Returns:
            dict with:
              - allowed: bool
              - blocked: bool
              - reason: str
              - boundary: str (name of triggering boundary)
              - severity: str
        """
        context = context or {}

        # 1. Check forbidden actions registry
        if ForbiddenActionRegistry.is_forbidden(method_name):
            record = {
                "allowed": False,
                "blocked": True,
                "reason": f"Action '{method_name}' is in the forbidden actions list",
                "boundary": "forbidden_action_registry",
                "severity": "blocker",
            }
            self.blocked_actions.append(record)
            self.check_history.append(record)
            return record

        # 2. Check against policy boundaries
        if self.policy:
            for boundary in self.policy.boundaries:
                if not boundary.enforced:
                    continue

                # Check if the action is in the boundary's blocked methods
                if method_name in boundary.auto_blocked_methods:
                    record = {
                        "allowed": False,
                        "blocked": True,
                        "reason": f"Boundary '{boundary.name}' blocks '{method_name}': "
                                  f"{boundary.description}",
                        "boundary": boundary.name,
                        "severity": boundary.severity,
                    }
                    self.blocked_actions.append(record)
                    self.check_history.append(record)
                    return record

                # Check context-based policies
                if boundary.name == "no_live_trade":
                    if context.get("environment") == "live":
                        record = {
                            "allowed": False,
                            "blocked": True,
                            "reason": f"Boundary '{boundary.name}': live trading "
                                      f"not allowed in design phase",
                            "boundary": boundary.name,
                            "severity": "blocker",
                        }
                        self.blocked_actions.append(record)
                        self.check_history.append(record)
                        return record

                if boundary.name == "no_auto_apply":
                    if context.get("auto_apply") is True:
                        record = {
                            "allowed": False,
                            "blocked": True,
                            "reason": f"Boundary '{boundary.name}': auto_apply "
                                      f"is not permitted",
                            "boundary": boundary.name,
                            "severity": "blocker",
                        }
                        self.blocked_actions.append(record)
                        self.check_history.append(record)
                        return record

                if boundary.name == "rollback_required":
                    if context.get("action") in ("apply_config", "switch_strategy",
                                                 "modify_config"):
                        if not context.get("rollback_plan"):
                            record = {
                                "allowed": False,
                                "blocked": True,
                                "reason": f"Boundary '{boundary.name}': rollback "
                                          f"plan is required for config changes",
                                "boundary": boundary.name,
                                "severity": "blocker",
                            }
                            self.blocked_actions.append(record)
                            self.check_history.append(record)
                            return record

                if boundary.name == "live_config_immutable":
                    if context.get("config_type") == "live":
                        record = {
                            "allowed": False,
                            "blocked": True,
                            "reason": f"Boundary '{boundary.name}': live config "
                                      f"cannot be modified in design phase V4.0",
                            "boundary": boundary.name,
                            "severity": "blocker",
                        }
                        self.blocked_actions.append(record)
                        self.check_history.append(record)
                        return record

        # 3. Allow if no boundary triggered
        record = {
            "allowed": True,
            "blocked": False,
            "reason": "No boundary triggered",
            "boundary": "",
            "severity": "info",
        }
        self.check_history.append(record)
        return record

    def check_signal(self, signal: dict) -> list:
        """Check a research signal against all applicable boundaries.

        Returns list of violations (empty = clean).
        """
        violations = []
        if not self.policy:
            return violations

        for boundary in self.policy.boundaries:
            if not boundary.enforced:
                continue

            if boundary.name == "no_auto_apply":
                if signal.get("auto_apply") is True:
                    violations.append({
                        "boundary": boundary.name,
                        "message": "Signal must have auto_apply=False",
                        "severity": boundary.severity,
                    })

            if boundary.name == "no_live_trade":
                if signal.get("no_live_trade") is not True:
                    violations.append({
                        "boundary": boundary.name,
                        "message": "Signal must have no_live_trade=True",
                        "severity": boundary.severity,
                    })

            if boundary.name == "evidence_traceability":
                if not signal.get("evidence_path"):
                    violations.append({
                        "boundary": boundary.name,
                        "message": "Signal must include evidence_path",
                        "severity": boundary.severity,
                    })

                if not signal.get("data_lineage"):
                    violations.append({
                        "boundary": boundary.name,
                        "message": "Signal must include data_lineage",
                        "severity": boundary.severity,
                    })

        return violations

    def get_report(self) -> dict:
        """Generate a boundary enforcement report."""
        return {
            "policy": self.policy.to_dict() if self.policy else None,
            "n_checks": len(self.check_history),
            "n_blocked": len(self.blocked_actions),
            "n_warnings": len(self.warnings),
            "blocked_actions": self.blocked_actions,
            "check_history": self.check_history[-20:],  # Last 20 checks
            "status": "active" if not any(
                b.get("severity") == "blocker" for b in self.blocked_actions
            ) else "enforcing",
        }
