"""V4.4 Kill Switch / Risk Sentinel — risk package

The risk package provides unified risk monitoring, circuit breaking,
and incident logging for the Hermes controlled execution pipeline.

Core modules:
  - risk_rules:      Structured rule definitions and evaluation engine
  - kill_switch:     Global circuit breaker (Kill Switch)
  - risk_sentinel:   Unified risk monitoring sentinel
  - incident_log:    Structured incident event log

Legacy modules (pre-V4.4):
  - pretrade_risk_check: A-share pretrade risk checks
"""

from factor_lab.risk.risk_rules import (
    RiskRule,
    RuleCheckResult,
    RuleEvaluator,
    RuleCategory,
    RuleSeverity,
    RuleStatus,
    build_default_rules,
    build_default_rule_evaluator,
    rule_by_name,
)

from factor_lab.risk.kill_switch import (
    KillSwitch,
    KillSwitchState,
    KillSwitchStatus,
    BlockedActionRecord,
)

from factor_lab.risk.risk_sentinel import (
    RiskSentinel,
    SentinelStatus,
    SentinelCheck,
)

from factor_lab.risk.incident_log import (
    IncidentLog,
    IncidentRecord,
)

__all__ = [
    # Risk Rules
    "RiskRule", "RuleCheckResult", "RuleEvaluator",
    "RuleCategory", "RuleSeverity", "RuleStatus",
    "build_default_rules", "build_default_rule_evaluator", "rule_by_name",
    # Kill Switch
    "KillSwitch", "KillSwitchState", "KillSwitchStatus", "BlockedActionRecord",
    # Risk Sentinel
    "RiskSentinel", "SentinelStatus", "SentinelCheck",
    # Incident Log
    "IncidentLog", "IncidentRecord",
]
