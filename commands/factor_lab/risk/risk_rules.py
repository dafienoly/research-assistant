"""V4.4 Kill Switch / Risk Sentinel — Risk Rules

Structured risk rule definitions and evaluation engine.
Each rule has a name, severity, threshold, condition evaluator,
and optional auto-recovery policy.

Rule categories:
  - DATA:    Data freshness, missing data, price anomalies
  - ACCOUNT: Account connection, balance, position anomalies
  - EXECUTION: Consecutive failures, fill deviations, slippage
  - LOSS:    Daily loss, drawdown, concentration
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Optional

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class RuleCategory(Enum):
    """Rule category — which risk dimension a rule monitors."""
    DATA = "data"
    ACCOUNT = "account"
    EXECUTION = "execution"
    LOSS = "loss"
    SYSTEM = "system"


class RuleSeverity(Enum):
    """Severity of a rule violation."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKER = "blocker"


class RuleStatus(Enum):
    """Current status of a rule check."""
    PASSED = "passed"
    VIOLATED = "violated"
    ERROR = "error"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Rule Definition
# ---------------------------------------------------------------------------
@dataclass
class RiskRule:
    """A single risk rule definition.

    Each rule evaluates a condition and produces a check result.
    Multiple rules form the risk sentinel's monitoring policy.

    Threshold fields are interpreted by the rule's evaluate function.
    """

    name: str
    category: str  # RuleCategory value
    description: str = ""
    severity: str = "warning"  # RuleSeverity value
    enabled: bool = True
    threshold: float = 0.0
    max_consecutive_failures: int = 3
    cooldown_seconds: int = 300  # Min seconds between re-triggers
    auto_recoverable: bool = False
    tags: list = field(default_factory=list)

    # Last evaluation state (runtime, not serialized to config)
    _last_status: str = "passed"
    _last_checked_at: str = ""
    _consecutive_failures: int = 0
    _last_triggered_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Strip runtime fields
        d.pop("_last_status", None)
        d.pop("_last_checked_at", None)
        d.pop("_consecutive_failures", None)
        d.pop("_last_triggered_at", None)
        return d

    def clone(self) -> "RiskRule":
        """Create a mutable copy with fresh runtime state."""
        return RiskRule(
            name=self.name,
            category=self.category,
            description=self.description,
            severity=self.severity,
            enabled=self.enabled,
            threshold=self.threshold,
            max_consecutive_failures=self.max_consecutive_failures,
            cooldown_seconds=self.cooldown_seconds,
            auto_recoverable=self.auto_recoverable,
            tags=list(self.tags),
        )


# ---------------------------------------------------------------------------
# Check Result
# ---------------------------------------------------------------------------
@dataclass
class RuleCheckResult:
    """Result of evaluating a single risk rule."""
    rule_name: str
    status: str = "passed"  # RuleStatus value
    severity: str = "warning"
    message: str = ""
    checked_at: str = ""
    category: str = "data"
    triggered_by: str = ""  # What value triggered the violation
    threshold: float = 0.0
    actual_value: float = 0.0
    consecutive_failures: int = 0
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(CST).isoformat()

    def is_violation(self) -> bool:
        return self.status in (RuleStatus.VIOLATED.value, RuleStatus.ERROR.value)

    def is_blocker(self) -> bool:
        return self.severity == RuleSeverity.BLOCKER.value and self.is_violation()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rule Evaluator
# ---------------------------------------------------------------------------
class RuleEvaluator:
    """Evaluates risk rules against provided context values.

    Supports both built-in threshold comparisons and custom evaluator
    functions for complex conditions.
    """

    def __init__(self):
        self.custom_evaluators: dict[str, Callable] = {}

    def register_evaluator(self, rule_name: str,
                           fn: Callable[[RiskRule, Any], RuleCheckResult]):
        """Register a custom evaluator for a specific rule."""
        self.custom_evaluators[rule_name] = fn

    def evaluate(self, rule: RiskRule, context: Any = None) -> RuleCheckResult:
        """Evaluate a single rule against context.

        Args:
            rule: The risk rule to evaluate
            context: Data context — can be a dict of values, a numeric
                     value, or any structured data the evaluator needs

        Returns:
            RuleCheckResult
        """
        if not rule.enabled:
            return RuleCheckResult(
                rule_name=rule.name,
                status=RuleStatus.SKIPPED.value,
                severity=rule.severity,
                message="Rule is disabled",
                category=rule.category,
            )

        # Custom evaluator takes priority
        if rule.name in self.custom_evaluators:
            result = self.custom_evaluators[rule.name](rule, context)
            rule._last_status = result.status
            rule._last_checked_at = result.checked_at
            if result.is_violation():
                rule._consecutive_failures += 1
                rule._last_triggered_at = result.checked_at
            else:
                rule._consecutive_failures = 0
            return result

        # Default: threshold-based evaluation
        return self._evaluate_threshold(rule, context)

    def _evaluate_threshold(self, rule: RiskRule,
                            context: Any = None) -> RuleCheckResult:
        """Default threshold-based evaluation.

        Context can be:
          - A dict with key "value" or the rule's name
          - A numeric value (int or float)
          - None (skips check)
        """
        actual = 0.0
        if isinstance(context, dict):
            actual = float(context.get("value", context.get(rule.name, 0)))
        elif isinstance(context, (int, float)):
            actual = float(context)
        else:
            return RuleCheckResult(
                rule_name=rule.name,
                status=RuleStatus.SKIPPED.value,
                severity=rule.severity,
                message="No context provided for threshold evaluation",
                category=rule.category,
                threshold=rule.threshold,
                actual_value=0.0,
            )

        is_violation = actual > rule.threshold
        status = RuleStatus.VIOLATED.value if is_violation else RuleStatus.PASSED.value
        message = (
            f"Value {actual} exceeds threshold {rule.threshold}"
            if is_violation
            else f"Value {actual} within threshold {rule.threshold}"
        )

        rule._last_status = status
        rule._last_checked_at = datetime.now(CST).isoformat()

        if is_violation:
            rule._consecutive_failures += 1
            rule._last_triggered_at = datetime.now(CST).isoformat()
        else:
            rule._consecutive_failures = 0

        return RuleCheckResult(
            rule_name=rule.name,
            status=status,
            severity=rule.severity,
            message=message,
            checked_at=datetime.now(CST).isoformat(),
            category=rule.category,
            triggered_by=f"value={actual} > threshold={rule.threshold}" if is_violation else "",
            threshold=rule.threshold,
            actual_value=actual,
            consecutive_failures=rule._consecutive_failures,
        )

    def evaluate_rules(self, rules: list[RiskRule],
                       context: Any = None) -> list[RuleCheckResult]:
        """Evaluate a list of rules against the same context."""
        return [self.evaluate(r, context) for r in rules]

    def summary(self, results: list[RuleCheckResult]) -> dict:
        """Generate a summary of rule check results."""
        n_total = len(results)
        n_violated = sum(1 for r in results if r.is_violation())
        n_blockers = sum(1 for r in results if r.is_blocker())
        n_passed = sum(1 for r in results if r.status == RuleStatus.PASSED.value)
        n_skipped = sum(1 for r in results if r.status == RuleStatus.SKIPPED.value)
        n_errors = sum(1 for r in results if r.status == RuleStatus.ERROR.value)

        violations = [r.to_dict() for r in results if r.is_violation()]
        return {
            "n_total": n_total,
            "n_violated": n_violated,
            "n_blockers": n_blockers,
            "n_passed": n_passed,
            "n_skipped": n_skipped,
            "n_errors": n_errors,
            "violations": violations,
            "status": (
                "blocked" if n_blockers > 0
                else "violated" if n_violated > 0
                else "passed"
            ),
        }


# ---------------------------------------------------------------------------
# Built-in Risk Rules
# ---------------------------------------------------------------------------
def build_default_rules() -> list[RiskRule]:
    """Build the default set of V4.4 risk rules."""
    rules = []

    # ── DATA rules ─────────────────────────────────────────────────
    rules.append(RiskRule(
        name="data_freshness",
        category=RuleCategory.DATA.value,
        description="数据新鲜度 — 行情/因子数据必须在阈值内更新",
        severity=RuleSeverity.CRITICAL.value,
        threshold=300,  # 5 minutes max staleness in seconds
        max_consecutive_failures=2,
        cooldown_seconds=60,
        auto_recoverable=True,
        tags=["data", "freshness", "stale"],
    ))

    rules.append(RiskRule(
        name="price_missing_rate",
        category=RuleCategory.DATA.value,
        description="价格缺失率 — 报价缺失比例不得超过阈值",
        severity=RuleSeverity.WARNING.value,
        threshold=0.05,  # 5% missing
        max_consecutive_failures=3,
        cooldown_seconds=120,
        auto_recoverable=True,
        tags=["data", "price", "missing"],
    ))

    rules.append(RiskRule(
        name="market_connectivity",
        category=RuleCategory.DATA.value,
        description="行情连接状态 — 数据源必须可用",
        severity=RuleSeverity.CRITICAL.value,
        threshold=0,
        max_consecutive_failures=1,
        cooldown_seconds=30,
        auto_recoverable=True,
        tags=["data", "connectivity", "source"],
    ))

    # ── ACCOUNT rules ──────────────────────────────────────────────
    rules.append(RiskRule(
        name="account_connection",
        category=RuleCategory.ACCOUNT.value,
        description="账户连接状态 — 交易账户必须在线",
        severity=RuleSeverity.CRITICAL.value,
        threshold=0,
        max_consecutive_failures=2,
        cooldown_seconds=60,
        auto_recoverable=True,
        tags=["account", "connection"],
    ))

    rules.append(RiskRule(
        name="account_balance_anomaly",
        category=RuleCategory.ACCOUNT.value,
        description="账户余额异常 — 余额低于最低留存",
        severity=RuleSeverity.CRITICAL.value,
        threshold=0,
        max_consecutive_failures=1,
        cooldown_seconds=300,
        auto_recoverable=False,
        tags=["account", "balance"],
    ))

    rules.append(RiskRule(
        name="position_concentration",
        category=RuleCategory.ACCOUNT.value,
        description="单票集中度 — 单只股票占总资产比例",
        severity=RuleSeverity.WARNING.value,
        threshold=0.25,  # 25% max
        max_consecutive_failures=3,
        cooldown_seconds=600,
        auto_recoverable=False,
        tags=["account", "position", "concentration"],
    ))

    # ── EXECUTION rules ────────────────────────────────────────────
    rules.append(RiskRule(
        name="consecutive_order_failures",
        category=RuleCategory.EXECUTION.value,
        description="连续订单失败 — 订单连续失败次数",
        severity=RuleSeverity.CRITICAL.value,
        threshold=3,
        max_consecutive_failures=1,  # Single evaluation triggers
        cooldown_seconds=120,
        auto_recoverable=True,
        tags=["execution", "order", "failure"],
    ))

    rules.append(RiskRule(
        name="fill_deviation",
        category=RuleCategory.EXECUTION.value,
        description="成交偏差 — 实际成交价偏离信号价比例",
        severity=RuleSeverity.WARNING.value,
        threshold=0.005,  # 0.5%
        max_consecutive_failures=3,
        cooldown_seconds=300,
        auto_recoverable=True,
        tags=["execution", "fill", "slippage"],
    ))

    rules.append(RiskRule(
        name="slippage_anomaly",
        category=RuleCategory.EXECUTION.value,
        description="滑点异常 — 平均滑点超过阈值",
        severity=RuleSeverity.WARNING.value,
        threshold=0.002,  # 0.2%
        max_consecutive_failures=3,
        cooldown_seconds=300,
        auto_recoverable=True,
        tags=["execution", "slippage"],
    ))

    # ── LOSS rules ─────────────────────────────────────────────────
    rules.append(RiskRule(
        name="daily_loss",
        category=RuleCategory.LOSS.value,
        description="日亏损 — 当日亏损超过阈值",
        severity=RuleSeverity.CRITICAL.value,
        threshold=0.02,  # 2% daily loss
        max_consecutive_failures=1,
        cooldown_seconds=3600,  # 1 hour cooldown
        auto_recoverable=False,
        tags=["loss", "daily", "pnl"],
    ))

    rules.append(RiskRule(
        name="drawdown",
        category=RuleCategory.LOSS.value,
        description="回撤 — 累计回撤超过阈值",
        severity=RuleSeverity.CRITICAL.value,
        threshold=0.08,  # 8% drawdown
        max_consecutive_failures=1,
        cooldown_seconds=3600,
        auto_recoverable=False,
        tags=["loss", "drawdown"],
    ))

    rules.append(RiskRule(
        name="daily_trade_count",
        category=RuleCategory.LOSS.value,
        description="日内交易次数 — 交易频率超过阈值",
        severity=RuleSeverity.WARNING.value,
        threshold=50,
        max_consecutive_failures=2,
        cooldown_seconds=600,
        auto_recoverable=True,
        tags=["loss", "frequency", "overtrade"],
    ))

    # ── SYSTEM rules ───────────────────────────────────────────────
    rules.append(RiskRule(
        name="pipeline_consistency",
        category=RuleCategory.SYSTEM.value,
        description="管线一致性 — 管线状态检查",
        severity=RuleSeverity.INFO.value,
        threshold=0,
        max_consecutive_failures=10,
        cooldown_seconds=300,
        auto_recoverable=True,
        tags=["system", "pipeline"],
    ))

    return rules


def build_default_rule_evaluator() -> RuleEvaluator:
    """Build a rule evaluator pre-loaded with default rules."""
    evaluator = RuleEvaluator()
    return evaluator


# ── Convenience ────────────────────────────────────────────────────
def rule_by_name(rules: list[RiskRule], name: str) -> Optional[RiskRule]:
    """Find a rule by name in a rule list."""
    for r in rules:
        if r.name == name:
            return r
    return None
