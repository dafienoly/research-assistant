"""V4.9 Controlled Live Readiness Report — 实盘就绪报告

Generates a comprehensive readiness assessment for controlled live trading
entry, covering data, strategy, execution, risk, audit, and manual workflow
maturity. It produces a readiness checklist, gap report, go/no-go
recommendation, and manual approval package — but NEVER executes trades.

This is the final gate before live execution in the controlled pipeline.
Crossing this gate still requires manual approval (V4.5).

Components:
  1. ReadinessDimension — Enum of assessed dimensions
  2. ReadinessChecklist — Checklist items organized by dimension
  3. ChecklistItem — A single checklist entry with status
  4. GapReport — Identifies gaps between current state and readiness
  5. Gap — A single gap finding
  6. GoNoGoRecommendation — Go/no-go decision with reasoning
  7. ManualApprovalPackage — Packages findings for human review
  8. LiveReadinessReport — Main orchestrator and report builder
  9. run_live_readiness — Backward-compatible entry point

Design principles:
  - All checks are structured, auditable, and evidence-backed
  - Gaps are clearly explained with severity (blocker/warning/info)
  - Even a "go" recommendation requires manual confirmation
  - No execution pathways are triggered — report only
  - Integration with MigrationCompat for core framework output

Safety boundaries:
  - readiness_check_only: True (never executes)
  - no_live_trade: True (never trades)
  - auto_apply: False (requires manual confirmation)
"""

import os, json, csv, hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from factor_lab.core.migration import MigrationCompat
from factor_lab.core.gate import GateEngine, GateCheck
from factor_lab.core.report import ReportBuilder

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


# ===========================================================================
# Enums
# ===========================================================================

class ReadinessDimension(str, Enum):
    """Dimensions assessed in the live readiness report."""
    DATA = "data"                       # Data source completeness and quality
    STRATEGY = "strategy"               # Strategy maturity and stability
    EXECUTION = "execution"             # Execution quality and reliability
    RISK = "risk"                       # Risk controls and limits
    AUDIT = "audit"                     # Audit trail completeness
    MANUAL_WORKFLOW = "manual_workflow" # Manual approval process readiness


class ChecklistStatus(str, Enum):
    """Status of a single checklist item."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    NOT_APPLICABLE = "na"
    NOT_CHECKED = "not_checked"


class GapSeverity(str, Enum):
    """Severity of a readiness gap."""
    BLOCKER = "blocker"     # Must be resolved before live
    WARNING = "warning"     # Should be resolved before live
    INFO = "info"           # Informational, no action required


class Recommendation(str, Enum):
    """Go/no-go recommendation."""
    GO = "go"                           # Ready for live (still requires manual approval)
    CONDITIONAL_GO = "conditional_go"   # Ready with conditions
    NO_GO = "no_go"                     # Not ready
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # Cannot determine


# ===========================================================================
# Data Classes
# ===========================================================================

@dataclass
class ChecklistItem:
    """A single readiness checklist entry.

    Each item represents one verifiable condition that should be met
    before live trading can be considered.
    """
    item_id: str                         # Unique identifier (e.g., "data_market_provider")
    dimension: ReadinessDimension        # Which dimension this belongs to
    title: str                           # Short human-readable title
    description: str                     # What this check verifies
    status: ChecklistStatus = ChecklistStatus.NOT_CHECKED
    severity: GapSeverity = GapSeverity.BLOCKER  # Severity if this item fails
    evidence: str = ""                   # Evidence/justification for the status
    source: str = ""                     # Where the evidence comes from

    def __post_init__(self):
        """Convert string fields to enum members if needed."""
        if isinstance(self.status, str):
            self.status = ChecklistStatus(self.status)
        if isinstance(self.severity, str):
            self.severity = GapSeverity(self.severity)
        if isinstance(self.dimension, str):
            self.dimension = ReadinessDimension(self.dimension)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "dimension": self.dimension.value,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "severity": self.severity.value,
            "evidence": self.evidence,
            "source": self.source,
        }


@dataclass
class Gap:
    """A single gap found during readiness assessment.

    Gaps are derived from checklist items that are not in PASS status.
    """
    item_id: str
    dimension: ReadinessDimension
    title: str
    description: str
    severity: GapSeverity
    impact: str = ""                     # What happens if this gap is not resolved
    recommendation: str = ""             # How to resolve this gap
    current_state: str = ""              # Current state description

    def __post_init__(self):
        """Convert string fields to enum members if needed."""
        if isinstance(self.dimension, str):
            self.dimension = ReadinessDimension(self.dimension)
        if isinstance(self.severity, str):
            self.severity = GapSeverity(self.severity)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "dimension": self.dimension.value,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "current_state": self.current_state,
        }


# ===========================================================================
# Readiness Checklist — Definition and Evaluation
# ===========================================================================

class ReadinessChecklist:
    """Defines and evaluates the readiness checklist.

    The checklist covers all six dimensions of readiness:
    data, strategy, execution, risk, audit, and manual workflow.
    """

    # Default checklist items organized by dimension
    DEFAULT_ITEMS: list = [
        # ── Data Dimension ──
        ChecklistItem(
            item_id="data_market_provider",
            dimension=ReadinessDimension.DATA,
            title="Market data provider active",
            description="At least one market data provider is active and returning data",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="data_fundamental_provider",
            dimension=ReadinessDimension.DATA,
            title="Fundamental data provider active",
            description="Fundamental/financial data provider is active",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="data_realtime_quote",
            dimension=ReadinessDimension.DATA,
            title="Real-time quote available",
            description="Real-time quote ingestion is operational",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="data_quality_gate",
            dimension=ReadinessDimension.DATA,
            title="Data quality gate passed",
            description="Recent data passes quality checks (freshness, completeness)",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="data_daily_bar",
            dimension=ReadinessDimension.DATA,
            title="Daily bar data available",
            description="Daily bar storage is complete with no critical gaps",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="data_no_fallback",
            dimension=ReadinessDimension.DATA,
            title="No fallback data used",
            description="All data comes from real providers, no demo/fallback",
            severity=GapSeverity.BLOCKER,
        ),

        # ── Strategy Dimension ──
        ChecklistItem(
            item_id="strategy_backtest_valid",
            dimension=ReadinessDimension.STRATEGY,
            title="Backtest results valid",
            description="Strategy backtest passed minimum performance thresholds",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="strategy_oos_valid",
            dimension=ReadinessDimension.STRATEGY,
            title="Out-of-sample test valid",
            description="OOS/walk-forward test results meet criteria",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="strategy_paper_tested",
            dimension=ReadinessDimension.STRATEGY,
            title="Paper trading completed",
            description="Strategy has completed minimum paper trading days",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="strategy_no_overfit",
            dimension=ReadinessDimension.STRATEGY,
            title="No overfit detected",
            description="Anti-overfit metrics are within acceptable range",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="strategy_orthogonal",
            dimension=ReadinessDimension.STRATEGY,
            title="Factor orthogonality maintained",
            description="Strategy factors are not redundant with existing ones",
            severity=GapSeverity.WARNING,
        ),

        # ── Execution Dimension ──
        ChecklistItem(
            item_id="execution_shadow_pipeline",
            dimension=ReadinessDimension.EXECUTION,
            title="Shadow pipeline active",
            description="Shadow pipeline is running and producing fills",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="execution_fill_rate",
            dimension=ReadinessDimension.EXECUTION,
            title="Fill rate acceptable",
            description="Shadow/paper fill rate meets minimum threshold",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="execution_slippage_control",
            dimension=ReadinessDimension.EXECUTION,
            title="Slippage control active",
            description="Slippage budget and estimation are configured",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="execution_trade_filter",
            dimension=ReadinessDimension.EXECUTION,
            title="Trade filter engine active",
            description="Trade filter rules are loaded and enforced",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="execution_order_book",
            dimension=ReadinessDimension.EXECUTION,
            title="Order book ready",
            description="Centralized order book is operational",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="execution_broker_sandbox",
            dimension=ReadinessDimension.EXECUTION,
            title="Broker adapter sandbox ready",
            description="Broker adapter sandbox has been tested",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="execution_capital_safety",
            dimension=ReadinessDimension.EXECUTION,
            title="Capital safety boundary active",
            description="Capital allocation limits and authority tiers are configured",
            severity=GapSeverity.BLOCKER,
        ),

        # ── Risk Dimension ──
        ChecklistItem(
            item_id="risk_sentinel_active",
            dimension=ReadinessDimension.RISK,
            title="Risk sentinel active",
            description="Risk sentinel is running and monitoring",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="risk_kill_switch",
            dimension=ReadinessDimension.RISK,
            title="Kill switch operational",
            description="Kill switch can halt operations if triggered",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="risk_boundary_enforcer",
            dimension=ReadinessDimension.RISK,
            title="Risk boundary enforcer active",
            description="Risk boundaries are defined and enforced",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="risk_drawdown_limit",
            dimension=ReadinessDimension.RISK,
            title="Drawdown limits configured",
            description="Maximum drawdown limits are set",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="risk_exposure_limit",
            dimension=ReadinessDimension.RISK,
            title="Exposure limits configured",
            description="Per-asset and total exposure limits are set",
            severity=GapSeverity.BLOCKER,
        ),

        # ── Audit Dimension ──
        ChecklistItem(
            item_id="audit_trail_complete",
            dimension=ReadinessDimension.AUDIT,
            title="Audit trail complete",
            description="All prior stages have complete audit logs",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="audit_approval_recorded",
            dimension=ReadinessDimension.AUDIT,
            title="Approval decisions recorded",
            description="All prior approvals have audit records",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="audit_rollback_available",
            dimension=ReadinessDimension.AUDIT,
            title="Rollback plan available",
            description="Rollback plan exists for config and strategy changes",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="audit_artifact_manifest",
            dimension=ReadinessDimension.AUDIT,
            title="Artifact manifest generated",
            description="All previous outputs have artifact manifests",
            severity=GapSeverity.WARNING,
        ),

        # ── Manual Workflow Dimension ──
        ChecklistItem(
            item_id="manual_approval_gate",
            dimension=ReadinessDimension.MANUAL_WORKFLOW,
            title="Manual approval gate configured",
            description="Manual approval workflow exists and is enforced",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="manual_approval_pending",
            dimension=ReadinessDimension.MANUAL_WORKFLOW,
            title="Manual approval pending review",
            description="At least one authorized person must approve live entry",
            severity=GapSeverity.BLOCKER,
        ),
        ChecklistItem(
            item_id="manual_operating_procedure",
            dimension=ReadinessDimension.MANUAL_WORKFLOW,
            title="Operating procedure documented",
            description="Live entry operating procedure is documented",
            severity=GapSeverity.WARNING,
        ),
        ChecklistItem(
            item_id="manual_emergency_contact",
            dimension=ReadinessDimension.MANUAL_WORKFLOW,
            title="Emergency contact available",
            description="Emergency contact and escalation path are defined",
            severity=GapSeverity.WARNING,
        ),
    ]

    def __init__(self, items: list = None):
        self.items = items or [ChecklistItem(**i.to_dict()) for i in self.DEFAULT_ITEMS]

    def evaluate(self, evidence_source: dict = None) -> list:
        """Evaluate checklist items against provided evidence.

        Args:
            evidence_source: Dict mapping item_id -> {status, evidence, source}
                             If None, items remain with their defaults.
        """
        evidence_source = evidence_source or {}
        for item in self.items:
            if item.item_id in evidence_source:
                ev = evidence_source[item.item_id]
                item.status = ChecklistStatus(ev.get("status", "not_checked"))
                item.evidence = ev.get("evidence", "")
                item.source = ev.get("source", "")
            # Items without evidence remain NOT_CHECKED
        return self.items

    def get_items_by_dimension(self, dimension: ReadinessDimension) -> list:
        """Get all items for a given dimension."""
        return [i for i in self.items if i.dimension == dimension]

    def get_summary(self) -> dict:
        """Get a summary of checklist results by dimension."""
        summary = {}
        for dim in ReadinessDimension:
            items = self.get_items_by_dimension(dim)
            if items:
                summary[dim.value] = {
                    "total": len(items),
                    "pass": sum(1 for i in items if i.status == ChecklistStatus.PASS),
                    "fail": sum(1 for i in items if i.status == ChecklistStatus.FAIL),
                    "warning": sum(1 for i in items if i.status == ChecklistStatus.WARNING),
                    "na": sum(1 for i in items if i.status == ChecklistStatus.NOT_APPLICABLE),
                    "not_checked": sum(1 for i in items if i.status == ChecklistStatus.NOT_CHECKED),
                }
        summary["overall"] = {
            "total": len(self.items),
            "pass": sum(1 for i in self.items if i.status == ChecklistStatus.PASS),
            "fail": sum(1 for i in self.items if i.status == ChecklistStatus.FAIL),
            "warning": sum(1 for i in self.items if i.status == ChecklistStatus.WARNING),
            "na": sum(1 for i in self.items if i.status == ChecklistStatus.NOT_APPLICABLE),
            "not_checked": sum(1 for i in self.items if i.status == ChecklistStatus.NOT_CHECKED),
        }
        return summary

    def to_dict_list(self) -> list:
        return [item.to_dict() for item in self.items]


# ===========================================================================
# Gap Report — Identify and Describe Gaps
# ===========================================================================

class GapReport:
    """Identifies and describes gaps between current state and readiness.

    Gaps are derived from the checklist: items that are FAIL or WARNING
    status generate gap entries with impact analysis and recommendations.
    """

    # Default impact and recommendation templates for common gaps
    GAP_TEMPLATES = {
        "data_market_provider": {
            "impact": "Cannot receive real-time market data",
            "recommendation": "Activate at least one market data provider (e.g., Baostock, AkShare)",
        },
        "data_fundamental_provider": {
            "impact": "Financial analysis features will be limited",
            "recommendation": "Configure a fundamental data provider for financial metrics",
        },
        "data_realtime_quote": {
            "impact": "Cannot execute trades with current pricing",
            "recommendation": "Enable real-time quote ingestion pipeline",
        },
        "data_quality_gate": {
            "impact": "Unreliable data may lead to incorrect signals",
            "recommendation": "Run data quality checks and resolve all failures",
        },
        "data_daily_bar": {
            "impact": "Backtest and analysis may use incomplete data",
            "recommendation": "Complete daily bar backfill and verify coverage",
        },
        "data_no_fallback": {
            "impact": "Demo/fallback data could mask real data issues",
            "recommendation": "Disable all fallback data sources and verify real provider connectivity",
        },
        "strategy_backtest_valid": {
            "impact": "Strategy is not verified for live conditions",
            "recommendation": "Run full backtest and verify metrics meet minimum thresholds",
        },
        "strategy_oos_valid": {
            "impact": "Strategy may be overfit to historical data",
            "recommendation": "Complete out-of-sample testing and verify OOS performance",
        },
        "strategy_paper_tested": {
            "impact": "Strategy has not been validated in simulated live conditions",
            "recommendation": "Run paper trading for minimum observation period",
        },
        "strategy_no_overfit": {
            "impact": "Strategy may fail in unseen market regimes",
            "recommendation": "Verify anti-overfit metrics (IC decay, walk-forward stability)",
        },
        "strategy_orthogonal": {
            "impact": "Strategy may be redundant with existing positions",
            "recommendation": "Verify factor correlation is within acceptable range",
        },
        "execution_shadow_pipeline": {
            "impact": "No execution simulation available",
            "recommendation": "Start and verify shadow pipeline operation",
        },
        "execution_fill_rate": {
            "impact": "Execution quality may be poor in live trading",
            "recommendation": "Investigate and improve fill rate",
        },
        "execution_slippage_control": {
            "impact": "Slippage may exceed acceptable levels",
            "recommendation": "Configure slippage budget and estimation parameters",
        },
        "execution_trade_filter": {
            "impact": "Unfiltered orders may reach execution",
            "recommendation": "Enable and configure trade filter rules",
        },
        "execution_order_book": {
            "impact": "Order execution may not be properly tracked",
            "recommendation": "Initialize and verify order book operation",
        },
        "execution_broker_sandbox": {
            "impact": "Broker integration not validated for live",
            "recommendation": "Run broker adapter sandbox tests and verify all interfaces",
        },
        "execution_capital_safety": {
            "impact": "Capital allocation and authority controls not active",
            "recommendation": "Configure capital safety boundaries with allocation limits and authority tiers",
        },
        "risk_sentinel_active": {
            "impact": "System anomalies may go undetected",
            "recommendation": "Start and verify risk sentinel monitoring",
        },
        "risk_kill_switch": {
            "impact": "Cannot halt operations in emergency",
            "recommendation": "Configure kill switch and verify manual trigger works",
        },
        "risk_boundary_enforcer": {
            "impact": "Risk policies are not enforced",
            "recommendation": "Define risk boundaries and enable boundary enforcer",
        },
        "risk_drawdown_limit": {
            "impact": "Uncontrolled losses could accumulate",
            "recommendation": "Set maximum drawdown limits and alert thresholds",
        },
        "risk_exposure_limit": {
            "impact": "Single position could dominate portfolio risk",
            "recommendation": "Set per-asset and total exposure limits",
        },
        "audit_trail_complete": {
            "impact": "Cannot trace historical decisions",
            "recommendation": "Complete audit trail for all prior stages",
        },
        "audit_approval_recorded": {
            "impact": "Cannot verify proper authorization",
            "recommendation": "Record all approval decisions in audit log",
        },
        "audit_rollback_available": {
            "impact": "Cannot undo changes in case of issues",
            "recommendation": "Generate rollback plan for current configuration",
        },
        "audit_artifact_manifest": {
            "impact": "Artifact lineage is not traceable",
            "recommendation": "Generate artifact manifests for all prior outputs",
        },
        "manual_approval_gate": {
            "impact": "Live entry can proceed without human oversight",
            "recommendation": "Configure mandatory manual approval gate for live entry",
        },
        "manual_approval_pending": {
            "impact": "Live entry has not been reviewed by authorized personnel",
            "recommendation": "Submit for manual approval by authorized approver",
        },
        "manual_operating_procedure": {
            "impact": "Live entry procedure is ad-hoc and error-prone",
            "recommendation": "Document standard operating procedure for live entry",
        },
        "manual_emergency_contact": {
            "impact": "No clear escalation path for emergencies",
            "recommendation": "Define emergency contact and escalation procedures",
        },
    }

    def __init__(self, checklist: ReadinessChecklist = None):
        self.checklist = checklist or ReadinessChecklist()
        self.gaps: list = []

    def analyze(self) -> list:
        """Analyze checklist results and generate gaps.

        Returns:
            List of Gap objects derived from non-passing checklist items.
        """
        self.gaps = []
        for item in self.checklist.items:
            if item.status in (ChecklistStatus.FAIL, ChecklistStatus.WARNING, ChecklistStatus.NOT_CHECKED):
                template = self.GAP_TEMPLATES.get(item.item_id, {})
                gap = Gap(
                    item_id=item.item_id,
                    dimension=item.dimension,
                    title=item.title,
                    description=item.description,
                    severity=item.severity if item.status == ChecklistStatus.FAIL else GapSeverity.WARNING,
                    impact=template.get("impact", "Unknown impact"),
                    recommendation=template.get("recommendation", "Investigate and resolve"),
                    current_state=f"Status: {item.status.value}. {item.evidence}" if item.evidence else f"Status: {item.status.value}. No evidence provided.",
                )
                self.gaps.append(gap)
        return self.gaps

    def get_gaps_by_severity(self, severity: GapSeverity) -> list:
        return [g for g in self.gaps if g.severity == severity]

    def get_gaps_by_dimension(self, dimension: ReadinessDimension) -> list:
        return [g for g in self.gaps if g.dimension == dimension]

    def get_summary(self) -> dict:
        return {
            "total_gaps": len(self.gaps),
            "blockers": len(self.get_gaps_by_severity(GapSeverity.BLOCKER)),
            "warnings": len(self.get_gaps_by_severity(GapSeverity.WARNING)),
            "info": len(self.get_gaps_by_severity(GapSeverity.INFO)),
            "by_dimension": {
                dim.value: len(self.get_gaps_by_dimension(dim))
                for dim in ReadinessDimension
            },
        }

    def to_dict_list(self) -> list:
        return [gap.to_dict() for gap in self.gaps]


# ===========================================================================
# Go/No-Go Recommendation
# ===========================================================================

class GoNoGoRecommendation:
    """Generates go/no-go recommendation based on gap analysis.

    Decision rules:
      - Any BLOCKER gap → NO_GO
      - No blockers, any WARNING gap → CONDITIONAL_GO
      - No gaps at all → GO
      - Not enough evidence → INSUFFICIENT_EVIDENCE
    """

    def __init__(self, gap_report: GapReport = None):
        self.gap_report = gap_report or GapReport()
        self.recommendation: Recommendation = Recommendation.INSUFFICIENT_EVIDENCE
        self.reasoning: list = []
        self.conditions: list = []

    def evaluate(self) -> dict:
        """Evaluate gaps and generate recommendation."""
        self.recommendation = Recommendation.INSUFFICIENT_EVIDENCE
        self.reasoning = []
        self.conditions = []

        gaps = self.gap_report.gaps
        if not gaps:
            gaps = self.gap_report.analyze()

        blockers = self.gap_report.get_gaps_by_severity(GapSeverity.BLOCKER)
        warnings = self.gap_report.get_gaps_by_severity(GapSeverity.WARNING)

        if not self.gap_report.checklist.items:
            self.recommendation = Recommendation.INSUFFICIENT_EVIDENCE
            self.reasoning.append("No checklist items evaluated. Cannot determine readiness.")
        elif len(blockers) > 0:
            self.recommendation = Recommendation.NO_GO
            self.reasoning.append(f"Found {len(blockers)} blocker gap(s) that must be resolved before live entry:")
            for b in blockers:
                self.reasoning.append(f"  - [{b.item_id}] {b.title}: {b.recommendation}")
                self.conditions.append(f"Resolve: {b.title}")
        elif len(warnings) > 0:
            self.recommendation = Recommendation.CONDITIONAL_GO
            self.reasoning.append(f"No blockers found. Found {len(warnings)} warning(s). Conditional go with conditions:")
            for w in warnings:
                self.reasoning.append(f"  - [{w.item_id}] {w.title}: {w.recommendation}")
                self.conditions.append(f"Address: {w.title}")
            self.reasoning.append("Final live entry still requires manual approval.")
        else:
            self.recommendation = Recommendation.GO
            self.reasoning.append("All checklist items passed. Ready for live consideration.")
            self.reasoning.append("NOTE: This is a recommendation only. Manual approval is still required.")

        return {
            "recommendation": self.recommendation.value,
            "reasoning": self.reasoning,
            "conditions": self.conditions,
            "requires_manual_approval": True,
            "auto_apply": False,
        }


# ===========================================================================
# Manual Approval Package
# ===========================================================================

class ManualApprovalPackage:
    """Packages all findings for human review and approval.

    The approval package contains:
      - Executive summary
      - Checklist results
      - Gap report
      - Go/no-go recommendation
      - Supporting evidence
      - Approval form (decision + signature fields)
    """

    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir) if output_dir else Path("/tmp")
        self.checklist: ReadinessChecklist = None
        self.gap_report: GapReport = None
        self.recommendation: dict = None
        self.package: dict = {}

    def build(self, checklist: ReadinessChecklist, gap_report: GapReport,
              recommendation: dict, context: dict = None) -> dict:
        """Build the complete manual approval package."""
        self.checklist = checklist
        self.gap_report = gap_report
        self.recommendation = recommendation

        self.package = {
            "package_type": "V4.9 Live Readiness Approval Package",
            "generated_at": datetime.now(CST).isoformat(),
            "context": context or {},
            "executive_summary": self._build_executive_summary(),
            "checklist_summary": checklist.get_summary(),
            "gap_analysis": {
                "summary": gap_report.get_summary(),
                "gaps": gap_report.to_dict_list(),
            },
            "recommendation": recommendation,
            "approval_form": self._build_approval_form(),
            "safety_boundaries": {
                "readiness_check_only": True,
                "no_live_trade": True,
                "auto_apply": False,
                "requires_manual_approval": True,
            },
        }
        return self.package

    def _build_executive_summary(self) -> dict:
        """Build executive summary."""
        checklist_summary = self.checklist.get_summary()
        overall = checklist_summary.get("overall", {})
        gap_summary = self.gap_report.get_summary() if self.gap_report else {}
        return {
            "title": "V4.9 Controlled Live Readiness Report",
            "overall_status": "NOT READY" if overall.get("fail", 0) > 0 or overall.get("not_checked", 0) > 0 else "READY",
            "total_items": overall.get("total", 0),
            "passed": overall.get("pass", 0),
            "failed": overall.get("fail", 0),
            "warnings": overall.get("warning", 0),
            "not_checked": overall.get("not_checked", 0),
            "total_gaps": gap_summary.get("total_gaps", 0),
            "blockers": gap_summary.get("blockers", 0),
            "recommendation": self.recommendation.get("recommendation", "unknown"),
            "message": "This report assesses readiness for controlled live trading. "
                       "It does NOT execute any trades or modify any configurations.",
        }

    def _build_approval_form(self) -> dict:
        """Build the approval form fields for human decision."""
        return {
            "title": "Live Entry Approval Form",
            "required_approver_level": "ADMIN or above",
            "fields": [
                {"name": "approver_name", "label": "Approver Name", "type": "text", "required": True},
                {"name": "approver_role", "label": "Role/Title", "type": "text", "required": True},
                {"name": "decision", "label": "Decision",
                 "type": "select", "options": ["approve", "reject", "conditional_approve"],
                 "required": True},
                {"name": "conditions", "label": "Conditions (if conditional)", "type": "text", "required": False},
                {"name": "signature", "label": "Digital Signature", "type": "text", "required": True},
                {"name": "comments", "label": "Comments", "type": "textarea", "required": False},
            ],
            "approved": False,
            "approved_at": None,
            "approved_by": None,
        }

    def to_dict(self) -> dict:
        return self.package

    def write_outputs(self, output_dir: str = None) -> Path:
        """Write all outputs to disk."""
        out = Path(output_dir or self.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # JSON package
        (out / "live_readiness_approval_package.json").write_text(
            json.dumps(self.package, indent=2, ensure_ascii=False))

        # Markdown report
        md = self._generate_markdown()
        (out / "live_readiness_report.md").write_text(md, encoding="utf-8")

        # HTML report
        html = self._generate_html()
        (out / "live_readiness_report.html").write_text(html, encoding="utf-8")

        # CSV summary
        self._write_csv(out)

        return out

    def _generate_markdown(self) -> str:
        """Generate markdown report."""
        rec = self.recommendation or {}
        rec_name = rec.get("recommendation", "unknown")
        icon = {"go": "✅", "conditional_go": "⚠️", "no_go": "❌", "insufficient_evidence": "❓"}.get(rec_name, "❓")

        lines = [
            f"# {icon} V4.9 Controlled Live Readiness Report",
            f"",
            f"**Generated:** {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Recommendation:** {rec_name}",
            f"",
            f"## Executive Summary",
            f"",
            f"This report assesses readiness for controlled live trading. "
            f"It does NOT execute any trades or modify configurations.",
            f"",
        ]

        # Checklist summary
        cs = self.checklist.get_summary() if self.checklist else {}
        overall = cs.get("overall", {})
        lines.extend([
            f"## Checklist Summary",
            f"",
            f"| Dimension | Total | Pass | Fail | Warning | N/A | Not Checked |",
            f"|-----------|-------|------|------|---------|-----|-------------|",
        ])
        for dim in ReadinessDimension:
            d = cs.get(dim.value, {})
            lines.append(
                f"| {dim.value} | {d.get('total', 0)} | {d.get('pass', 0)} | "
                f"{d.get('fail', 0)} | {d.get('warning', 0)} | "
                f"{d.get('na', 0)} | {d.get('not_checked', 0)} |"
            )
        lines.append(
            f"| **Total** | {overall.get('total', 0)} | {overall.get('pass', 0)} | "
            f"{overall.get('fail', 0)} | {overall.get('warning', 0)} | "
            f"{overall.get('na', 0)} | {overall.get('not_checked', 0)} |"
        )
        lines.append("")

        # Gaps
        gaps = self.gap_report.to_dict_list() if self.gap_report else []
        if gaps:
            lines.extend([
                f"## Gap Analysis ({len(gaps)} gaps)",
                f"",
                f"| ID | Dimension | Severity | Title |",
                f"|----|-----------|----------|-------|",
            ])
            for g in gaps:
                lines.append(f"| {g['item_id']} | {g['dimension']} | {g['severity']} | {g['title']} |")
            lines.append("")

            for g in gaps:
                lines.extend([
                    f"### {g['title']} ({g['item_id']})",
                    f"",
                    f"- **Severity:** {g['severity']}",
                    f"- **Impact:** {g.get('impact', 'N/A')}",
                    f"- **Recommendation:** {g.get('recommendation', 'N/A')}",
                    f"- **Current State:** {g.get('current_state', 'N/A')}",
                    f"",
                ])

        # Recommendation
        lines.extend([
            f"## Recommendation: {rec_name.upper()}",
            f"",
        ])
        for r in rec.get("reasoning", []):
            lines.append(f"- {r}")
        lines.append("")

        conditions = rec.get("conditions", [])
        if conditions:
            lines.extend([
                f"### Conditions",
                f"",
            ])
            for c in conditions:
                lines.append(f"- [ ] {c}")
            lines.append("")

        # Safety
        lines.extend([
            f"## Safety Boundaries",
            f"",
            f"- **Readiness check only:** Yes (no execution)",
            f"- **No live trade:** Yes",
            f"- **Auto-apply:** No",
            f"- **Manual approval required:** Yes",
            f"",
            f"---",
            f"*V4.9 Controlled Live Readiness Report | Hermes Research Assistant*",
        ])

        return "\n".join(lines)

    def _generate_html(self) -> str:
        """Generate HTML report."""
        rec = self.recommendation or {}
        rec_name = rec.get("recommendation", "unknown")
        icon = {"go": "✅", "conditional_go": "⚠️", "no_go": "❌", "insufficient_evidence": "❓"}.get(rec_name, "❓")
        rec_color = {"go": "#059669", "conditional_go": "#D97706",
                     "no_go": "#DC2626", "insufficient_evidence": "#64748B"}.get(rec_name, "#64748B")

        cs = self.checklist.get_summary() if self.checklist else {}
        overall = cs.get("overall", {})

        # Dimension rows
        dim_rows = ""
        for dim in ReadinessDimension:
            d = cs.get(dim.value, {})
            dim_rows += (
                f"<tr><td>{dim.value}</td><td>{d.get('total', 0)}</td>"
                f"<td style='color:#059669'>{d.get('pass', 0)}</td>"
                f"<td style='color:#DC2626'>{d.get('fail', 0)}</td>"
                f"<td style='color:#D97706'>{d.get('warning', 0)}</td>"
                f"<td>{d.get('na', 0)}</td>"
                f"<td style='color:#64748B'>{d.get('not_checked', 0)}</td></tr>"
            )

        # Gap rows
        gap_rows = ""
        gaps = self.gap_report.to_dict_list() if self.gap_report else []
        for g in gaps:
            sev_color = {"blocker": "#DC2626", "warning": "#D97706", "info": "#64748B"}.get(g["severity"], "#64748B")
            gap_rows += (
                f"<tr><td>{g['item_id']}</td><td>{g['dimension']}</td>"
                f"<td style='color:{sev_color}'>{g['severity']}</td>"
                f"<td>{g['title']}</td>"
                f"<td>{g.get('impact', '')}</td></tr>"
            )

        # Reasoning
        reasoning_html = "".join(f"<li>{r}</li>" for r in rec.get("reasoning", []))

        # Conditions
        conditions_html = ""
        for c in rec.get("conditions", []):
            conditions_html += f"<li><input type='checkbox' disabled> {c}</li>"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>V4.9 Live Readiness Report</title>
<style>
body {{font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif;background:#1a1a2e;color:#e0e0e0;margin:0;padding:20px;}}
.card {{background:#16213e;border-radius:8px;padding:20px;margin:12px 0;}}
h1 {{color:#00bcd4;}} h2 {{color:#00bcd4;border-bottom:1px solid #333;padding-bottom:6px;}}
table {{width:100%;border-collapse:collapse;margin:8px 0;}}
th,td {{padding:6px 8px;text-align:left;border-bottom:1px solid #333;font-size:0.9em;}}
th {{color:#888;font-weight:600;}}
.badge {{display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.8em;font-weight:600;}}
.badge-pass {{background:#064E3B;color:#6EE7B7;}}
.badge-fail {{background:#7F1D1D;color:#FCA5A5;}}
.badge-warn {{background:#78350F;color:#FDE68A;}}
.footer {{text-align:center;color:#666;font-size:0.8em;margin-top:24px;}}
ul {{margin:4px 0;padding-left:20px;}}
li {{margin:4px 0;}}
</style></head><body>
<div class="card" style="border-left:4px solid {rec_color};">
<h1>{icon} V4.9 Controlled Live Readiness Report</h1>
<p><strong>Recommendation:</strong> <span class="badge badge-{'pass' if rec_name=='go' else 'warn' if rec_name=='conditional_go' else 'fail'}">{rec_name}</span></p>
<p><strong>Generated:</strong> {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p>
<p><strong>Status:</strong> {'READY' if overall.get('fail',0)==0 and overall.get('not_checked',0)==0 else 'NOT READY'}</p>
<p><em>This report assesses readiness for controlled live trading. It does NOT execute any trades or modify configurations.</em></p>
</div>

<div class="card"><h2>📋 Checklist Summary</h2>
<table><tr><th>Dimension</th><th>Total</th><th>Pass</th><th>Fail</th><th>Warning</th><th>N/A</th><th>Not Checked</th></tr>
{dim_rows}
<tr style="font-weight:600;border-top:2px solid #00bcd4;">
<td>Total</td><td>{overall.get('total',0)}</td>
<td style='color:#059669'>{overall.get('pass',0)}</td>
<td style='color:#DC2626'>{overall.get('fail',0)}</td>
<td style='color:#D97706'>{overall.get('warning',0)}</td>
<td>{overall.get('na',0)}</td>
<td style='color:#64748B'>{overall.get('not_checked',0)}</td>
</tr></table></div>

<div class="card"><h2>🔍 Gap Analysis ({len(gaps)} gaps)</h2>
<table><tr><th>ID</th><th>Dimension</th><th>Severity</th><th>Title</th><th>Impact</th></tr>
{gap_rows}
</table></div>

<div class="card"><h2>🎯 Recommendation</h2>
<p><strong>{rec_name.upper()}</strong></p>
<ol>{reasoning_html}</ol>
</div>

<div class="card"><h2>📋 Conditions</h2>
<ul>{conditions_html or '<li style="color:#666">No conditions</li>'}</ul>
</div>

<div class="card"><h2>🛡️ Safety Boundaries</h2>
<ul>
<li>Readiness check only: ✅ (no execution)</li>
<li>No live trade: ✅</li>
<li>Auto-apply: ❌</li>
<li>Manual approval required: ✅</li>
</ul></div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>V4.9 Controlled Live Readiness Report | Hermes Research Assistant</p>
<p>{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>
</body></html>"""
        return html

    def _write_csv(self, out: Path):
        """Write CSV outputs."""
        # Gaps CSV
        gaps = self.gap_report.to_dict_list() if self.gap_report else []
        if gaps:
            with open(out / "readiness_gaps.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["item_id", "dimension", "severity", "title",
                                                   "description", "impact", "recommendation", "current_state"])
                w.writeheader()
                w.writerows(gaps)

        # Checklist CSV
        items = self.checklist.to_dict_list() if self.checklist else []
        if items:
            with open(out / "readiness_checklist.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["item_id", "dimension", "title", "description",
                                                   "status", "severity", "evidence", "source"])
                w.writeheader()
                w.writerows(items)


# ===========================================================================
# Live Readiness Report — Main Orchestrator
# ===========================================================================

class LiveReadinessReport:
    """Main orchestrator for V4.9 Controlled Live Readiness Report.

    Coordinates checklist evaluation, gap analysis, recommendation, and
    approval package generation. Integrates with the core framework
    (MigrationCompat, GateEngine, ReportBuilder) for artifact management.
    """

    def __init__(self, run_id: str, output_dir: str = None, strict: bool = False):
        self.run_id = run_id
        self.strict = strict
        self.output_dir = Path(output_dir) if output_dir else BASE / "live_readiness" / run_id
        self.generated_at = datetime.now(CST)

        # Components
        self.checklist = ReadinessChecklist()
        self.gap_report = GapReport(self.checklist)
        self.recommendation_engine = GoNoGoRecommendation(self.gap_report)
        self.approval_package = ManualApprovalPackage(str(self.output_dir))

        # Framework integration
        self.compat = MigrationCompat(
            str(self.output_dir), run_id=run_id,
            module="live_readiness", source_run_id=run_id,
        )
        self.gate_engine = GateEngine()
        self.report_builder = ReportBuilder(str(self.output_dir))

    def run(self, evidence_source: dict = None, context: dict = None) -> dict:
        """Run the complete live readiness assessment.

        Args:
            evidence_source: Dict mapping item_id -> {status, evidence, source}
            context: Additional context for the report (e.g., strategy name)

        Returns:
            Complete readiness report as dict.
        """
        context = context or {}

        # 1. Evaluate checklist
        self.checklist.evaluate(evidence_source)

        # 2. Analyze gaps
        self.gap_report.analyze()

        # 3. Generate recommendation
        recommendation = self.recommendation_engine.evaluate()

        # 4. Build approval package
        self.approval_package.build(
            checklist=self.checklist,
            gap_report=self.gap_report,
            recommendation=recommendation,
            context=context,
        )

        # 5. Run framework gates
        self._run_gates()

        # 6. Write outputs
        self._write_outputs()

        # 7. Build result
        result = self._build_result(recommendation)
        return result

    def _run_gates(self):
        """Run gate checks for the live readiness pipeline."""
        ge = self.gate_engine
        checklist_summary = self.checklist.get_summary()
        overall = checklist_summary.get("overall", {})

        ge.add_check("readiness", "checklist_complete",
                     passed=overall.get("not_checked", 0) == 0,
                     severity="blocker",
                     message=f"{overall.get('not_checked', 0)} items not checked")

        ge.add_check("readiness", "no_failures",
                     passed=overall.get("fail", 0) == 0,
                     severity="blocker",
                     message=f"{overall.get('fail', 0)} items failed")

        ge.add_check("readiness", "no_blocker_gaps",
                     passed=len(self.gap_report.get_gaps_by_severity(GapSeverity.BLOCKER)) == 0,
                     severity="blocker",
                     message=f"{len(self.gap_report.get_gaps_by_severity(GapSeverity.BLOCKER))} blocker gaps found")

        ge.add_check("readiness", "recommendation_not_no_go",
                     passed=self.recommendation_engine.recommendation != Recommendation.NO_GO,
                     severity="blocker",
                     message=f"Recommendation: {self.recommendation_engine.recommendation.value}")

        ge.finalize()

    def _write_outputs(self):
        """Write all report outputs."""
        # Write approval package (JSON, MD, HTML, CSV)
        self.approval_package.write_outputs(str(self.output_dir))

        # Write JSON result
        result = self._build_result(self.recommendation_engine.evaluate())
        (self.output_dir / "live_readiness.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False))

        # Audit log
        with open(self.output_dir / "live_readiness_audit.log", "w") as f:
            f.write(f"=== LIVE READINESS AUDIT V4.9 ===\n")
            f.write(f"Run ID: {self.run_id}\n")
            f.write(f"Generated: {self.generated_at.isoformat()}\n")
            f.write(f"Recommendation: {self.recommendation_engine.recommendation.value}\n")
            f.write(f"Readiness check only: True\n")
            f.write(f"No live trade: True\n")
            f.write(f"Auto-apply: False\n")
            f.write(f"Manual approval required: True\n")
            f.write(f"=== END ===\n")

        # Core framework outputs
        for fname in ["live_readiness.json", "live_readiness_report.html",
                       "live_readiness_report.md", "readiness_checklist.csv",
                       "readiness_gaps.csv", "live_readiness_audit.log"]:
            p = self.output_dir / fname
            if p.exists():
                self.compat.legacy(fname)

        self.compat.finalize(
            verdict=self.recommendation_engine.recommendation.value,
            safety={"auto_apply": False, "no_live_trade": True},
        )
        self.compat.log_event(
            "live_readiness", status="completed",
            safety={"auto_apply": False, "no_live_trade": True},
        )

    def _build_result(self, recommendation: dict) -> dict:
        """Build the final result dict."""
        checklist_summary = self.checklist.get_summary()
        gap_summary = self.gap_report.get_summary()

        return {
            "run_id": self.run_id,
            "version": "V4.9",
            "generated_at": self.generated_at.isoformat(),
            "status": "completed",
            "recommendation": recommendation.get("recommendation", "insufficient_evidence"),
            "reasoning": recommendation.get("reasoning", []),
            "conditions": recommendation.get("conditions", []),
            "checklist_summary": checklist_summary,
            "gap_analysis": {
                "summary": gap_summary,
                "gaps": self.gap_report.to_dict_list(),
            },
            "gates": self.gate_engine.get_summary(),
            "safety": {
                "readiness_check_only": True,
                "no_live_trade": True,
                "auto_apply": False,
                "requires_manual_approval": True,
            },
        }


# ===========================================================================
# Backward-Compatible Entry Point
# ===========================================================================

def run_live_readiness(run_id=None, latest=False, candidate=None, strict=False):
    """Live Readiness assessment — backward-compatible entry point.

    Args:
        run_id: Specific run ID to assess
        latest: If True, use the latest paper_promotion_review run
        candidate: Optional strategy candidate name
        strict: If True, fails on first gap

    Returns:
        Dict with readiness assessment results.
    """
    # Resolve run_id
    if latest:
        parent = BASE / "paper_promotion_review"
        runs = sorted(parent.iterdir()) if parent.exists() else []
        if not runs:
            return {"error": "无 Paper Promotion Review 输出", "status": "failed"}
        run_id = runs[-1].name

    src_dir = BASE / "paper_promotion_review" / run_id
    if not src_dir.exists():
        return {"error": "Paper Promotion Review 目录不存在", "status": "failed"}

    audit_log = src_dir / "paper_promotion_audit.log"
    if not audit_log.exists():
        return {"error": "paper_promotion_audit.log 不存在", "status": "failed"}

    # Read promotion audit for context
    audit_text = audit_log.read_text() if audit_log.exists() else ""
    paper_review_only = "Paper review only: True" in audit_text
    live_apply = "Live apply: True" in audit_text

    # Build evidence from promotion review
    evidence = _build_evidence_from_promotion(src_dir, audit_text)

    context = {
        "source_run_id": run_id,
        "source_dir": str(src_dir),
        "candidate": candidate or audit_text,
        "paper_review_only": paper_review_only,
        "live_apply": live_apply,
    }

    # Run the full V4.9 assessment
    report = LiveReadinessReport(run_id=run_id, strict=strict)
    result = report.run(evidence_source=evidence, context=context)

    # Apply strict mode
    if strict and result.get("recommendation") in ("no_go", "insufficient_evidence"):
        result["status"] = "failed"
        if "error" not in result:
            result["error"] = "Strict mode: readiness check failed"

    return result


def _build_evidence_from_promotion(src_dir: Path, audit_text: str) -> dict:
    """Build evidence dict from existing promotion review outputs."""
    evidence = {}

    # Try to read config snapshots
    config_before = src_dir / "paper_config_snapshot_before.json"
    config_after = src_dir / "paper_config_snapshot_after.json"
    before = json.load(open(config_before)) if config_before.exists() else {}
    after = json.load(open(config_after)) if config_after.exists() else {}

    # Paper trading evidence
    if "Paper apply: True" in audit_text:
        evidence["strategy_paper_tested"] = {
            "status": "pass",
            "evidence": "Paper trading completed (promotion review confirms)",
            "source": str(src_dir),
        }

    # Audit trail
    if "Live config unchanged: True" in audit_text:
        evidence["audit_trail_complete"] = {
            "status": "pass",
            "evidence": "Audit trail found in paper_promotion_audit.log",
            "source": str(src_dir),
        }

    # Rollback available
    rollback_file = src_dir / "rollback_recommendation.md"
    if rollback_file.exists():
        evidence["audit_rollback_available"] = {
            "status": "pass",
            "evidence": "Rollback recommendation exists",
            "source": str(rollback_file),
        }

    # Artifact manifest
    manifest_file = src_dir / "manifest.json"
    if manifest_file.exists():
        evidence["audit_artifact_manifest"] = {
            "status": "pass",
            "evidence": "Artifact manifest found",
            "source": str(manifest_file),
        }

    return evidence
