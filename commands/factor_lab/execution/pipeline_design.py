"""V4.1 Shadow Live Pipeline — Pipeline Design & Contracts

Defines the layered contracts that govern the flow from research signal
to execution intent. Every real execution path REQUIRES human approval.
This module integrates V4.1 shadow pipeline for PAPER_SHADOW stage execution.

Pipeline stages (in order):

  0. RESEARCH_SIGNAL   — 研究信号生成 (auto)
  1. PROPOSAL_CREATION — 提案创建 (auto with gate checks)
  2. PROPOSAL_APPROVAL — 提案审批 (requires HUMAN approval)   ← manual gate
  3. PAPER_SHADOW      — Paper shadow forward (V4.1 auto shadow execution)
  4. PAPER_REVIEW      — Paper 表现审查 (auto with gate checks)
  5. LIVE_READINESS    — 实盘就绪评估 (requires HUMAN approval)  ← manual gate
  6. LIVE_APPROVAL     — 实盘审批确认 (requires HUMAN approval)  ← manual gate
  7. LIVE_EXECUTION    — 实盘执行 (BLOCKED — design only)
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Stage identifiers
# ---------------------------------------------------------------------------
STAGE_RESEARCH_SIGNAL = "research_signal"
STAGE_PROPOSAL_CREATION = "proposal_creation"
STAGE_PROPOSAL_APPROVAL = "proposal_approval"
STAGE_PAPER_SHADOW = "paper_shadow"
STAGE_PAPER_REVIEW = "paper_review"
STAGE_LIVE_READINESS = "live_readiness"
STAGE_LIVE_APPROVAL = "live_approval"
STAGE_LIVE_EXECUTION = "live_execution"

# Stages that require human approval (manual gate)
HUMAN_APPROVAL_STAGES = {
    STAGE_PROPOSAL_APPROVAL,
    STAGE_LIVE_READINESS,
    STAGE_LIVE_APPROVAL,
}

# Stages that are blocked by design (no_live_trade=True)
BLOCKED_STAGES = {
    STAGE_LIVE_EXECUTION,
}

ALL_STAGES = [
    STAGE_RESEARCH_SIGNAL,
    STAGE_PROPOSAL_CREATION,
    STAGE_PROPOSAL_APPROVAL,
    STAGE_PAPER_SHADOW,
    STAGE_PAPER_REVIEW,
    STAGE_LIVE_READINESS,
    STAGE_LIVE_APPROVAL,
    STAGE_LIVE_EXECUTION,
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SignalSource(Enum):
    RESEARCH_SKILL = "research_skill"
    ALPHA_DISCOVERY = "alpha_discovery"
    FACTOR_EVALUATION = "factor_evaluation"
    MANUAL_ANALYSIS = "manual_analysis"
    EXTERNAL_IMPORT = "external_import"


class ProposalAction(Enum):
    ADD_STRATEGY = "add_strategy"
    REMOVE_STRATEGY = "remove_strategy"
    MODIFY_WEIGHT = "modify_weight"
    MODIFY_CONFIG = "modify_config"
    REBALANCE_NOW = "rebalance_now"
    NO_ACTION = "no_action"


class IntentStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    EXECUTED = "executed"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@dataclass
class ResearchSignal:
    """研究信号 — 管道输入契约 (Stage 0 output)

    Represents a research finding that COULD lead to a trading action.
    It is NOT an instruction — it's evidence + recommendation.
    """
    signal_id: str = ""
    generated_at: str = ""
    source: str = SignalSource.RESEARCH_SKILL.value
    title: str = ""
    description: str = ""
    evidence_path: str = ""
    confidence: float = 0.0  # 0.0–1.0
    related_alpha_ids: list = field(default_factory=list)
    data_lineage: dict = field(default_factory=dict)
    risk_flags: list = field(default_factory=list)
    suggested_action: str = ProposalAction.NO_ACTION.value
    auto_apply: bool = False
    no_live_trade: bool = True
    dry_run: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(CST).isoformat()
        if not self.signal_id:
            self.signal_id = f"sig_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"

    def validate(self) -> list:
        """Validate signal contract. Returns list of validation errors."""
        errors = []
        if self.auto_apply:
            errors.append("auto_apply must be False for research signals")
        if not self.no_live_trade:
            errors.append("no_live_trade must be True for research signals")
        if self.confidence < 0 or self.confidence > 1:
            errors.append(f"confidence must be [0,1], got {self.confidence}")
        if not self.title:
            errors.append("title is required")
        return errors


@dataclass
class ProposalContract:
    """提案契约 — 从研究信号到配置建议 (Stage 1 output)

    A structured proposal that a human can review and approve/reject.
    Contains the delta from current state and expected impact.
    """
    proposal_id: str = ""
    signal_id: str = ""
    created_at: str = ""
    title: str = ""
    description: str = ""
    action: str = ProposalAction.NO_ACTION.value
    target: str = ""  # e.g., strategy name, config key
    config_diff: dict = field(default_factory=dict)
    expected_impact: str = ""
    risk_assessment: str = ""
    requires_human_approval: bool = True
    auto_apply: bool = False
    no_live_trade: bool = True
    rollback_plan: str = ""
    evidence_refs: list = field(default_factory=list)
    status: str = IntentStatus.DRAFT.value
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.proposal_id:
            self.proposal_id = f"prop_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"

    def validate(self) -> list:
        """Validate proposal contract. Returns list of validation errors."""
        errors = []
        if self.auto_apply:
            errors.append("auto_apply must be False for proposals")
        if not self.no_live_trade:
            errors.append("no_live_trade must be True for proposals")
        if not self.requires_human_approval:
            errors.append("requires_human_approval must be True for proposals")
        if not self.title:
            errors.append("title is required")
        if not self.rollback_plan:
            errors.append("rollback_plan is required for proposals")
        if self.action == ProposalAction.NO_ACTION.value and not self.config_diff:
            errors.append("proposal with no_action and no config_diff is meaningless")
        return errors


@dataclass
class ExecutionIntent:
    """执行意图契约 — 审批通过后的执行指令 (Gate output)

    Represents an approved action that is ready for execution.
    Execution is gated: paper execution runs automatically,
    live execution requires additional human confirmation.
    """
    intent_id: str = ""
    proposal_id: str = ""
    signal_id: str = ""
    created_at: str = ""
    action: str = ProposalAction.NO_ACTION.value
    target: str = ""
    config_diff: dict = field(default_factory=dict)
    environment: str = "paper"  # "paper" or "live"
    approved_by: str = ""
    approved_at: str = ""
    is_executed: bool = False
    executed_at: str = ""
    execution_result: dict = field(default_factory=dict)
    rollback_plan: str = ""
    auto_apply: bool = False
    no_live_trade: bool = True
    status: str = IntentStatus.DRAFT.value
    audit_trail: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.intent_id:
            self.intent_id = f"int_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"

    def validate(self) -> list:
        """Validate execution intent. Returns list of validation errors."""
        errors = []
        if self.auto_apply:
            errors.append("auto_apply must be False for execution intents")
        if self.environment == "live" and self.no_live_trade:
            errors.append("live execution requires no_live_trade=False, "
                          "which is blocked by design")
        if self.status == IntentStatus.EXECUTED.value and not self.executed_at:
            errors.append("executed intents must have executed_at timestamp")
        return errors


@dataclass
class AuditRecord:
    """审计记录 — 每个操作步骤的审计轨迹"""
    record_id: str = ""
    stage: str = ""
    action: str = ""
    actor: str = ""  # "system" | "human:<name>"
    timestamp: str = ""
    detail: str = ""
    before_state: dict = field(default_factory=dict)
    after_state: dict = field(default_factory=dict)
    safety_flags: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(CST).isoformat()
        if not self.record_id:
            self.record_id = f"aud_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"


# ---------------------------------------------------------------------------
# Pipeline context & stages
# ---------------------------------------------------------------------------
@dataclass
class PipelineContext:
    """Pipeline 上下文 — 贯穿整个管线的共享状态"""
    pipeline_id: str = ""
    version: str = "V4.1"
    created_at: str = ""
    signal: Optional[ResearchSignal] = None
    proposal: Optional[ProposalContract] = None
    intent: Optional[ExecutionIntent] = None
    audit_log: list = field(default_factory=list)
    current_stage: str = STAGE_RESEARCH_SIGNAL
    status: str = "running"
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.pipeline_id:
            self.pipeline_id = f"pipe_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"

    def add_audit(self, stage: str, action: str, actor: str,
                  detail: str = "", before: dict = None, after: dict = None):
        record = AuditRecord(
            record_id=f"aud_{len(self.audit_log)+1:04d}",
            stage=stage, action=action, actor=actor,
            detail=detail, before_state=before or {},
            after_state=after or {},
            safety_flags={"auto_apply": False, "no_live_trade": True},
        )
        self.audit_log.append(asdict(record))


@dataclass
class PipelineStage:
    """Pipeline 阶段定义"""
    name: str
    index: int
    requires_human_approval: bool = False
    is_blocked: bool = False
    is_auto: bool = True
    entry_criteria: list = field(default_factory=list)
    exit_criteria: list = field(default_factory=list)
    status: str = "pending"


@dataclass
class PipelineResult:
    """Pipeline 运行结果"""
    pipeline_id: str = ""
    version: str = "V4.1"
    status: str = "completed"
    stages: list = field(default_factory=list)
    output_dir: str = ""
    summary: dict = field(default_factory=dict)
    safety_flags: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "version": self.version,
            "status": self.status,
            "stages": [s if isinstance(s, dict) else s for s in self.stages],
            "output_dir": self.output_dir,
            "summary": self.summary,
            "safety_flags": self.safety_flags,
        }


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------
def _build_stage_definitions() -> list:
    """Build the canonical list of pipeline stages."""
    return [
        PipelineStage(
            name=STAGE_RESEARCH_SIGNAL, index=0,
            is_auto=True, requires_human_approval=False,
            entry_criteria=["ResearchSignal received"],
            exit_criteria=["ResearchSignal validated", "source verified"],
        ),
        PipelineStage(
            name=STAGE_PROPOSAL_CREATION, index=1,
            is_auto=True, requires_human_approval=False,
            entry_criteria=["ResearchSignal validated"],
            exit_criteria=["ProposalContract created", "rollback_plan included"],
        ),
        PipelineStage(
            name=STAGE_PROPOSAL_APPROVAL, index=2,
            is_auto=False, requires_human_approval=True,
            entry_criteria=["ProposalContract drafted"],
            exit_criteria=["Human approved", "Proposal signed"],
        ),
        PipelineStage(
            name=STAGE_PAPER_SHADOW, index=3,
            is_auto=True, requires_human_approval=False,
            entry_criteria=["Proposal approved"],
            exit_criteria=["Shadow forward completed", "Audit logged"],
        ),
        PipelineStage(
            name=STAGE_PAPER_REVIEW, index=4,
            is_auto=True, requires_human_approval=False,
            entry_criteria=["Shadow results available"],
            exit_criteria=["Paper performance reviewed"],
        ),
        PipelineStage(
            name=STAGE_LIVE_READINESS, index=5,
            is_auto=False, requires_human_approval=True,
            entry_criteria=["Paper reviewed", "Risk assessment done"],
            exit_criteria=["Readiness approved by human"],
        ),
        PipelineStage(
            name=STAGE_LIVE_APPROVAL, index=6,
            is_auto=False, requires_human_approval=True,
            entry_criteria=["Readiness approved"],
            exit_criteria=["Final human confirmation"],
        ),
        PipelineStage(
            name=STAGE_LIVE_EXECUTION, index=7,
            is_auto=False, requires_human_approval=True,
            is_blocked=True,
            entry_criteria=["Live approved"],
            exit_criteria=["BLOCKED — design only"],
        ),
    ]


def _build_stage_map(stages: list) -> dict:
    return {s.name: s for s in stages}


class LivePipelineRunner:
    """V4.0 受控实盘管线运行器

    Orchestrates the pipeline stages. Enforces safety boundaries:
      - No auto-apply for proposals or intents
      - No live trade execution
      - Human approval required at critical gates
      - Every step is audited
    """

    def __init__(self, output_dir: str = ""):
        self.stages = _build_stage_definitions()
        self.stage_map = _build_stage_map(self.stages)
        self.output_dir = output_dir
        self.context: Optional[PipelineContext] = None
        self.result: Optional[PipelineResult] = None

    def start(self, signal: ResearchSignal) -> PipelineContext:
        """Start a new pipeline run with a research signal."""
        ctx = PipelineContext(
            pipeline_id=f"pipe_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}",
            signal=signal,
            current_stage=STAGE_RESEARCH_SIGNAL,
        )
        # Initial audit: signal received
        errors = signal.validate()
        if errors:
            ctx.errors.extend(errors)
            ctx.status = "failed"
        ctx.add_audit(
            stage=STAGE_RESEARCH_SIGNAL,
            action="signal_received",
            actor="system",
            detail=f"Signal '{signal.title}' received. Source: {signal.source}. "
                   f"Errors: {len(errors)}",
        )
        self.context = ctx
        return ctx

    def advance(self, target_stage: str, actor: str = "system",
                human_approval: bool = False, approval_evidence: str = "") -> dict:
        """Advance the pipeline to the next stage.

        Returns a status dict with:
          - success: bool
          - blocked: bool  (stage is blocked by design)
          - needs_human: bool  (stage requires human approval)
          - message: str
          - errors: list
        """
        if not self.context:
            return {"success": False, "blocked": False, "needs_human": False,
                    "message": "No active pipeline context", "errors": ["No context"]}

        current = self.stage_map.get(self.context.current_stage)
        target = self.stage_map.get(target_stage)

        if not current or not target:
            return {"success": False, "blocked": False, "needs_human": False,
                    "message": f"Unknown stage: current={self.context.current_stage}, target={target_stage}",
                    "errors": ["Unknown stage"]}

        if target.index <= current.index:
            return {"success": False, "blocked": False, "needs_human": False,
                    "message": f"Cannot go backward: {current.name} → {target.name}",
                    "errors": ["Backward transition"]}

        # ENFORCE sequential advancement — one stage at a time
        # This prevents skipping intermediate human-approval gates
        if target.index != current.index + 1:
            return {"success": False, "blocked": False, "needs_human": False,
                    "message": f"Must advance sequentially: {current.name} → "
                               f"(next) → {target.name} (gap of {target.index - current.index})",
                    "errors": ["Non-sequential advancement"]}

        # Check if current stage needs human approval to proceed
        if current.requires_human_approval and not human_approval:
            return {"success": False, "blocked": False, "needs_human": True,
                    "message": f"Stage '{current.name}' requires human approval to advance",
                    "errors": ["Human approval required"]}

        # If target requires human approval, verify approval evidence
        if target.requires_human_approval and not human_approval:
            return {"success": False, "blocked": False, "needs_human": True,
                    "message": f"Stage '{target.name}' requires human approval before entry",
                    "errors": ["Human approval required for entry"]}

        # Advance — even blocked stages are entered (so pipeline state reflects it)
        current.status = "completed"
        target.status = "running" if not target.is_blocked else "blocked"
        self.context.current_stage = target_stage

        self.context.add_audit(
            stage=target_stage,
            action="stage_entered",
            actor=actor,
            detail=f"Entered stage '{target.name}'. "
                   f"Requires human: {target.requires_human_approval}. "
                   f"Blocked: {target.is_blocked}. "
                   + (f"Approval evidence: {approval_evidence}" if approval_evidence else ""),
        )

        if target.is_blocked:
            self.context.status = "blocked"
        elif target_stage == STAGE_LIVE_APPROVAL:
            self.context.status = "awaiting_human"
        else:
            self.context.status = "running"

        return {
            "success": True,
            "blocked": target.is_blocked,
            "needs_human": target.requires_human_approval,
            "message": f"Advanced to stage '{target.name}'",
            "errors": [],
        }

    def shadow_forward(self, trades: list, output_dir: str = "") -> dict:
        """Execute V4.1 shadow forward for the PAPER_SHADOW stage.

        Runs the proposal through the shadow pipeline: creates shadow orders,
        simulates fills with slippage, tracks positions/PnL, and generates
        deviation reports.

        Args:
            trades: list of trade dicts [{symbol, side, quantity, price, ...}]
            output_dir: override output directory

        Returns:
            dict with shadow execution results
        """
        from factor_lab.execution.shadow_pipeline import (
            ShadowPipelineRunner, ShadowPipelineConfig,
        )

        if not self.context:
            return {"success": False, "error": "No active pipeline context"}

        cfg = ShadowPipelineConfig(
            output_dir=output_dir or self.output_dir or "",
            auto_generate_reports=True,
        )
        shadow_runner = ShadowPipelineRunner(config=cfg)

        signal_id = self.context.signal.signal_id if self.context.signal else ""
        proposal_id = self.context.proposal.proposal_id if self.context.proposal else ""

        result = shadow_runner.process_signal(signal_id, proposal_id, trades)

        # Link result back to pipeline context
        self.context.metadata["shadow_result"] = result.to_dict()

        # Audit
        n_entries = result.n_entries if result else 0
        n_errors = len(result.errors) if result else 0
        self.context.add_audit(
            stage=STAGE_PAPER_SHADOW,
            action="shadow_forward_executed",
            actor="system",
            detail=f"Shadow forward: {len(trades)} trades, "
                   f"{n_entries} ledger entries, {n_errors} errors",
        )

        return {
            "success": True,
            "result": result.to_dict() if result else {},
            "n_trades": len(trades),
        }

    def finalize(self) -> PipelineResult:
        """Complete the pipeline run and produce a result."""
        if not self.context:
            raise ValueError("No pipeline context to finalize")

        stage_summaries = []
        for s in self.stages:
            stage_summaries.append({
                "name": s.name,
                "status": s.status,
                "requires_human_approval": s.requires_human_approval,
                "is_blocked": s.is_blocked,
            })

        self.result = PipelineResult(
            pipeline_id=self.context.pipeline_id,
            status=self.context.status,
            stages=stage_summaries,
            summary={
                "signal_id": self.context.signal.signal_id if self.context.signal else "",
                "proposal_id": self.context.proposal.proposal_id if self.context.proposal else "",
                "intent_id": self.context.intent.intent_id if self.context.intent else "",
                "final_stage": self.context.current_stage,
                "n_audit_records": len(self.context.audit_log),
                "n_errors": len(self.context.errors),
                "n_warnings": len(self.context.warnings),
            },
            safety_flags={
                "auto_apply": False,
                "no_live_trade": True,
                "human_approval_stages": list(HUMAN_APPROVAL_STAGES),
                "blocked_stages": list(BLOCKED_STAGES),
                "live_execution_reached": self.context.current_stage == STAGE_LIVE_EXECUTION,
            },
        )
        return self.result

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        return self.stage_map.get(name)

    @property
    def all_stages_passed(self) -> bool:
        return all(s.status == "completed" for s in self.stages
                   if not s.is_blocked)

    def to_dict(self) -> dict:
        """Serialize the pipeline configuration as a design document."""
        return {
            "version": "V4.1",
            "pipeline": {
                "name": "Controlled Live Pipeline",
                "description": "受控实盘管线 — V4.1 影子实盘集成",
                "auto_apply": False,
                "no_live_trade": True,
                "stages": [
                    {
                        "name": s.name,
                        "index": s.index,
                        "requires_human_approval": s.requires_human_approval,
                        "is_blocked": s.is_blocked,
                        "is_auto": s.is_auto,
                        "entry_criteria": s.entry_criteria,
                        "exit_criteria": s.exit_criteria,
                    }
                    for s in self.stages
                ],
                "human_approval_required_stages": sorted(HUMAN_APPROVAL_STAGES),
                "blocked_stages": sorted(BLOCKED_STAGES),
                "safety_boundaries": {
                    "auto_apply": False,
                    "no_live_trade": True,
                    "requires_human_approval": True,
                    "no_broker_adapter": True,
                    "no_miniqmt": True,
                    "no_real_order_submission": True,
                    "rollback_mandatory": True,
                },
            },
            "contracts": {
                "research_signal": {
                    "required_fields": ["signal_id", "title", "source", "confidence"],
                    "auto_apply": "must be False",
                    "no_live_trade": "must be True",
                },
                "proposal": {
                    "required_fields": ["proposal_id", "title", "action", "rollback_plan"],
                    "auto_apply": "must be False",
                    "no_live_trade": "must be True",
                    "requires_human_approval": "must be True",
                },
                "execution_intent": {
                    "required_fields": ["intent_id", "proposal_id", "environment", "approved_by"],
                    "auto_apply": "must be False",
                    "live_environment_guard": "requires additional human approval",
                },
            },
        }
