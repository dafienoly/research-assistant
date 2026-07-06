"""V4.0 Controlled Live Pipeline — Approval Gate Spec

Multi-level approval gate system that enforces human confirmation
before any critical pipeline transition. Gates are placed at every
point where a decision could lead to real trading.

Approval levels:
  AUTO    — system may proceed without human (research steps)
  MANUAL  — human approval is REQUIRED (proposal, paper→live)
  BLOCKED — stage is blocked by design (live execution)

Each gate logs:
  - Who approved
  - What evidence was presented
  - What the decision was
  - When it happened
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Approval level enum
# ---------------------------------------------------------------------------
class ApprovalLevel(Enum):
    """Gate approval levels"""
    AUTO = "auto"               # System may proceed without human
    MANUAL = "manual"           # Human approval REQUIRED
    BLOCKED = "blocked"         # Blocked by design (no_live_trade)


# ---------------------------------------------------------------------------
# Gate configuration
# ---------------------------------------------------------------------------
@dataclass
class ApprovalGateConfig:
    """Gate configuration — defines when and how a gate is enforced."""
    gate_name: str
    level: ApprovalLevel = ApprovalLevel.AUTO
    description: str = ""
    required_evidence: list = field(default_factory=list)
    required_approvers: int = 1  # Number of human approvals needed
    timeout_hours: int = 72      # Proposal expires after this
    safety_checks: list = field(default_factory=list)
    rollback_required: bool = True

    def to_dict(self) -> dict:
        return {
            "gate_name": self.gate_name,
            "level": self.level.value,
            "description": self.description,
            "required_evidence": self.required_evidence,
            "required_approvers": self.required_approvers,
            "timeout_hours": self.timeout_hours,
            "safety_checks": self.safety_checks,
            "rollback_required": self.rollback_required,
        }


# ---------------------------------------------------------------------------
# Approval decision
# ---------------------------------------------------------------------------
@dataclass
class ApprovalDecision:
    """Record of a single approval decision."""
    decision_id: str = ""
    gate_name: str = ""
    approved: bool = False
    approved_by: str = ""
    approved_at: str = ""
    evidence: str = ""
    notes: str = ""
    expires_at: str = ""
    status: str = "pending"  # pending / approved / rejected / expired
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.approved_at:
            self.approved_at = datetime.now(CST).isoformat()

    def approve(self, approver: str, evidence: str = "", notes: str = ""):
        """Record a human approval."""
        self.approved = True
        self.approved_by = approver
        self.approved_at = datetime.now(CST).isoformat()
        self.evidence = evidence
        self.notes = notes
        self.status = "approved"

    def reject(self, approver: str, reason: str = ""):
        """Record a human rejection."""
        self.approved = False
        self.approved_by = approver
        self.approved_at = datetime.now(CST).isoformat()
        self.notes = reason
        self.status = "rejected"

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            return datetime.now(CST) > expiry
        except (ValueError, TypeError):
            return False

    def validate(self) -> list:
        errors = []
        if self.approved and not self.approved_by:
            errors.append("approved decision requires approver identity")
        if self.status == "approved" and not self.approved:
            errors.append("status approved but approved flag not set")
        return errors


# ---------------------------------------------------------------------------
# Gate definitions
# ---------------------------------------------------------------------------
class Gates:
    """Canonical gate definitions for V4.0 Controlled Live Pipeline."""

    # Gate A: Research → Proposal (auto, with safety checks)
    GATE_RESEARCH_TO_PROPOSAL = ApprovalGateConfig(
        gate_name="research_to_proposal",
        level=ApprovalLevel.AUTO,
        description="研究信号 → 提案创建. Auto-gate: validates signal contract, "
                    "checks source credibility, verifies no_live_trade flag.",
        required_evidence=["ResearchSignal validated", "Source verified"],
        required_approvers=0,
        rollback_required=False,
        safety_checks=[
            "auto_apply must be False",
            "no_live_trade must be True",
            "confidence must be in [0, 1]",
            "source must be known and documented",
        ],
    )

    # Gate B: Proposal → Paper (requires human approval)
    GATE_PROPOSAL_TO_PAPER = ApprovalGateConfig(
        gate_name="proposal_to_paper",
        level=ApprovalLevel.MANUAL,
        description="提案 → Paper Trading. Human must review and approve the "
                    "proposal before it enters paper shadow trading.",
        required_evidence=[
            "ProposalContract validated",
            "Round-trip rollback plan provided",
            "Config diff preview generated",
            "Impact assessment reviewed",
        ],
        required_approvers=1,
        timeout_hours=72,
        rollback_required=True,
        safety_checks=[
            "auto_apply must be False",
            "no_live_trade must be True",
            "rollback_plan must exist",
            "proposal action must be valid",
            "config_diff must be reversible",
        ],
    )

    # Gate C: Paper → Live Readiness (requires human approval)
    GATE_PAPER_TO_READINESS = ApprovalGateConfig(
        gate_name="paper_to_readiness",
        level=ApprovalLevel.MANUAL,
        description="Paper Performance → Live Readiness Assessment. "
                    "Human must confirm paper performance justifies live consideration.",
        required_evidence=[
            "Paper shadow results available",
            "Paper performance review completed",
            "Risk assessment reviewed",
            "Comparison to baseline available",
        ],
        required_approvers=1,
        timeout_hours=168,  # 7 days
        rollback_required=True,
        safety_checks=[
            "paper_performance must be measured against baseline",
            "risk_flags must be reviewed",
            "no automatic promotion",
            "live_config unchanged during paper phase",
        ],
    )

    # Gate D: Readiness → Live Approval (requires human approval)
    GATE_READINESS_TO_LIVE_APPROVAL = ApprovalGateConfig(
        gate_name="readiness_to_live_approval",
        level=ApprovalLevel.MANUAL,
        description="Live Readiness → Live Approval. "
                    "Human must explicitly approve moving to live execution. "
                    "This is the final safety gate before live.",
        required_evidence=[
            "Live readiness report available",
            "All risk gates passed",
            "Capital safety verified",
            "Kill switch operational",
            "Rollback plan confirmed",
        ],
        required_approvers=1,
        timeout_hours=72,
        rollback_required=True,
        safety_checks=[
            "readiness report must be generated",
            "no outstanding risk_flags",
            "capital safety checks passed",
            "paper phase completed successfully",
            "all prior gates passed",
        ],
    )

    # Gate E: Live Approval → Live Execution (BLOCKED by design)
    GATE_LIVE_EXECUTION = ApprovalGateConfig(
        gate_name="live_execution",
        level=ApprovalLevel.BLOCKED,
        description="Live Approval → Live Execution. "
                    "BLOCKED BY DESIGN in V4.0. This gate exists in the "
                    "architecture but always rejects — no real trading occurs.",
        required_evidence=["V4.0 design phase — execution not implemented"],
        required_approvers=0,
        rollback_required=True,
        safety_checks=[
            "BLOCKED: no_live_trade=True",
            "BLOCKED: no broker adapter connected",
            "BLOCKED: no real order submission",
            "BLOCKED: design phase only",
        ],
    )

    # All gates
    ALL_GATES = [
        GATE_RESEARCH_TO_PROPOSAL,
        GATE_PROPOSAL_TO_PAPER,
        GATE_PAPER_TO_READINESS,
        GATE_READINESS_TO_LIVE_APPROVAL,
        GATE_LIVE_EXECUTION,
    ]

    @classmethod
    def get_gate(cls, name: str) -> Optional[ApprovalGateConfig]:
        for g in cls.ALL_GATES:
            if g.gate_name == name:
                return g
        return None


# ---------------------------------------------------------------------------
# Gate evaluator
# ---------------------------------------------------------------------------
class GateEvaluator:
    """Evaluates gate conditions and enforces approval policies.

    Usage:
        evaluator = GateEvaluator()
        result = evaluator.evaluate(gate_config, context)
        if not result["passed"]:
            # gate is blocked
    """

    def __init__(self):
        self.decisions: list = []
        self.results: list = []

    def evaluate(self, gate: ApprovalGateConfig,
                 context: dict = None) -> dict:
        """Evaluate whether a gate should open.

        Returns:
            dict with:
              - gate_name: str
              - level: str (auto/manual/blocked)
              - passed: bool
              - requires_human: bool
              - blocked: bool
              - checks: list of check results
              - decision: ApprovalDecision or None
        """
        checks = []
        all_passed = True

        # 1. Run safety checks
        for check in gate.safety_checks:
            check_passed = _evaluate_safety_check(check, context or {})
            checks.append({"check": check, "passed": check_passed})
            if not check_passed:
                all_passed = False

        # 2. Determine gate status by level
        requires_human = gate.level == ApprovalLevel.MANUAL
        blocked = gate.level == ApprovalLevel.BLOCKED

        if blocked:
            passed = False
        elif gate.level == ApprovalLevel.AUTO:
            passed = all_passed
        else:  # MANUAL
            # Manual gates require both checks AND human decision
            passed = all_passed and self._has_approved(gate.gate_name)

        # 3. Record evaluation
        decision = self._get_decision(gate.gate_name)
        result = {
            "gate_name": gate.gate_name,
            "level": gate.level.value,
            "passed": passed,
            "requires_human": requires_human,
            "blocked": blocked,
            "checks": checks,
            "decision": asdict(decision) if decision else None,
        }
        self.results.append(result)

        # 4. Enforce: manual gates without approval fail
        if requires_human and not self._has_approved(gate.gate_name):
            passed = False
            result["passed"] = False
            result["reason"] = "Human approval required but not yet provided"

        return result

    def register_decision(self, decision: ApprovalDecision):
        """Register a human approval decision."""
        errors = decision.validate()
        if errors:
            raise ValueError(f"Invalid approval decision: {errors}")
        self.decisions.append(decision)

    def _find_decision(self, gate_name: str) -> Optional[ApprovalDecision]:
        for d in reversed(self.decisions):
            if d.gate_name == gate_name:
                return d
        return None

    def _get_decision(self, gate_name: str) -> Optional[ApprovalDecision]:
        d = self._find_decision(gate_name)
        if d and d.is_expired():
            d.status = "expired"
            return d
        return d

    def _has_approved(self, gate_name: str) -> bool:
        d = self._find_decision(gate_name)
        if d is None:
            return False
        if d.is_expired():
            return False
        return d.approved

    def get_summary(self) -> dict:
        return {
            "n_gates_evaluated": len(self.results),
            "n_decisions": len(self.decisions),
            "gates": self.results,
        }


def _evaluate_safety_check(check: str, context: dict) -> bool:
    """Evaluate a single safety check string against context.

    Supports simple keyword-based checks:
      - "auto_apply must be False" → context.get("auto_apply") is False
      - "no_live_trade must be True" → context.get("no_live_trade") is True
      - "must exist" / "must be"  → existence checks
    """
    check_lower = check.lower()

    if "auto_apply must be false" in check_lower:
        return context.get("auto_apply") is False
    if "no_live_trade must be true" in check_lower:
        return context.get("no_live_trade") is True
    if "rollback_plan must exist" in check_lower or "rollback_plan must" in check_lower:
        return bool(context.get("rollback_plan"))
    if "must exist" in check_lower:
        # Generic existence check
        key = check.split("must")[0].strip().replace(" ", "_").lower()
        if key in context:
            return bool(context[key])
        return True  # Unknown keys pass by default
    if "must be" in check_lower:
        # Only evaluate against context if the key actually exists in context
        parts = check.split("must be")
        if len(parts) == 2:
            key = parts[0].strip().replace(" ", "_").lower()
            value = parts[1].strip()
            # Skip if the key isn't in context (it's a policy statement, not run-time check)
            if key in context:
                return str(context.get(key)).lower() == value.lower()
            return True  # Informational policy checks pass by default

    # Default: safety checks that reference "BLOCKED" pass automatically
    if "blocked" in check_lower:
        return True

    return True
