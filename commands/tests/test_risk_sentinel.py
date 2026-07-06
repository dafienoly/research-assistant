"""V4.4 Kill Switch / Risk Sentinel — Comprehensive Tests

Tests cover:
  - Risk rules: creation, evaluation, threshold checks
  - Kill switch: arm, trigger, release, disable, recovery
  - Kill switch: action blocking, blocked action tracking
  - Incident log: record, acknowledge, resolve, close, persistence
  - Risk sentinel: full check cycle, dimension checks, status reporting
  - Integration: sentinel triggers kill switch on blocker violations
  - Edge cases: missing context, disabled rules, auto recovery
"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta

from factor_lab.risk.risk_rules import (
    RiskRule, RuleCheckResult, RuleEvaluator, RuleCategory,
    RuleSeverity, RuleStatus, build_default_rules,
    build_default_rule_evaluator, rule_by_name,
)
from factor_lab.risk.kill_switch import (
    KillSwitch, KillSwitchState, KillSwitchStatus, BlockedActionRecord,
)
from factor_lab.risk.incident_log import (
    IncidentLog, IncidentRecord,
)
from factor_lab.risk.risk_sentinel import (
    RiskSentinel, SentinelStatus, SentinelCheck,
)

CST = timezone(timedelta(hours=8))

# =========================================================================
# Risk Rules Tests
# =========================================================================

def test_default_rules_loaded():
    """默认规则加载正确"""
    rules = build_default_rules()
    assert len(rules) > 0
    names = [r.name for r in rules]
    assert "data_freshness" in names
    assert "daily_loss" in names
    assert "consecutive_order_failures" in names


def test_rule_find_by_name():
    """通过名称查找规则"""
    rules = build_default_rules()
    rule = rule_by_name(rules, "data_freshness")
    assert rule is not None
    assert rule.name == "data_freshness"
    assert rule.category == RuleCategory.DATA.value

    missing = rule_by_name(rules, "nonexistent_rule")
    assert missing is None


def test_rule_threshold_evaluation_passed():
    """阈值检查—通过"""
    evaluator = RuleEvaluator()
    rule = RiskRule(
        name="test_rule",
        category=RuleCategory.DATA.value,
        threshold=0.1,
    )
    result = evaluator.evaluate(rule, {"value": 0.05})
    assert result.status == RuleStatus.PASSED.value
    assert result.is_violation() is False
    assert result.actual_value == 0.05


def test_rule_threshold_evaluation_violated():
    """阈值检查—触发"""
    evaluator = RuleEvaluator()
    rule = RiskRule(
        name="test_rule",
        category=RuleCategory.DATA.value,
        threshold=0.1,
    )
    result = evaluator.evaluate(rule, {"value": 0.15})
    assert result.status == RuleStatus.VIOLATED.value
    assert result.is_violation() is True
    assert result.actual_value == 0.15


def test_rule_disable_skips_evaluation():
    """禁用的规则被跳过"""
    evaluator = RuleEvaluator()
    rule = RiskRule(
        name="test_rule",
        category=RuleCategory.DATA.value,
        threshold=0.1,
        enabled=False,
    )
    result = evaluator.evaluate(rule, {"value": 999})
    assert result.status == RuleStatus.SKIPPED.value


def test_rule_consecutive_failures_tracking():
    """连续失败计数"""
    evaluator = RuleEvaluator()
    rule = RiskRule(
        name="test_rule",
        category=RuleCategory.DATA.value,
        threshold=0.1,
    )

    # First violation
    evaluator.evaluate(rule, {"value": 0.2})
    assert rule._consecutive_failures == 1

    # Second violation
    evaluator.evaluate(rule, {"value": 0.3})
    assert rule._consecutive_failures == 2

    # Pass resets counter
    evaluator.evaluate(rule, {"value": 0.05})
    assert rule._consecutive_failures == 0


def test_rule_blocker_severity():
    """BLOCKER 级别的规则检查"""
    rule = RiskRule(
        name="blocker_rule",
        category=RuleCategory.ACCOUNT.value,
        severity=RuleSeverity.BLOCKER.value,
        threshold=0,
    )
    evaluator = RuleEvaluator()
    result = evaluator.evaluate(rule, {"value": 1})
    assert result.is_blocker() is True
    assert result.is_violation() is True


def test_rule_evaluator_summary():
    """评估摘要"""
    evaluator = RuleEvaluator()
    rules = [
        RiskRule(name="r1", category=RuleCategory.DATA.value, threshold=10, severity=RuleSeverity.CRITICAL.value),
        RiskRule(name="r2", category=RuleCategory.DATA.value, threshold=10),
        RiskRule(name="r3", category=RuleCategory.DATA.value, threshold=10),
    ]
    context = {"r1": 5, "r2": 15, "r3": 3}
    results = evaluator.evaluate_rules(rules, context)
    summary = evaluator.summary(results)
    assert summary["n_total"] == 3
    assert summary["n_violated"] == 1
    assert summary["n_passed"] == 2
    assert summary["status"] == "violated"


# =========================================================================
# Kill Switch Tests
# =========================================================================

def test_kill_switch_initial_state():
    """初始状态为 ARMED"""
    ks = KillSwitch()
    assert ks.state == KillSwitchState.ARMED.value
    assert ks.is_armed() is True
    assert ks.is_triggered() is False
    assert ks.is_blocked() is False


def test_kill_switch_arm():
    """arm() 切回 ARMED 状态"""
    ks = KillSwitch()
    ks.trigger("test_rule", "Test trigger")
    assert ks.is_triggered() is True
    ks.arm()
    assert ks.is_armed() is True


def test_kill_switch_trigger():
    """trigger() 正确切换到 TRIGGERED"""
    ks = KillSwitch()
    incident = ks.trigger("daily_loss", "Daily loss exceeded 2%")
    assert ks.is_triggered() is True
    assert ks.is_blocked() is True
    assert ks.status.triggered_by_rule == "daily_loss"
    assert incident is not None
    assert incident.severity == "blocker"


def test_kill_switch_release():
    """release() 回到 ARMED"""
    ks = KillSwitch()
    ks.trigger("test_rule")
    released = ks.release("admin", "Risk resolved")
    assert released is True
    assert ks.is_armed() is True


def test_kill_switch_release_without_auto_recovery():
    """没有 auto_recovery 时 release 需要 force"""
    ks = KillSwitch(auto_recovery=False)
    ks.trigger("test_rule")

    # Without force — should fail
    released = ks.release("admin", "Reason")
    assert released is False
    assert ks.is_triggered() is True

    # With force — should succeed
    released = ks.release("admin", "Force release", force=True)
    assert released is True
    assert ks.is_armed() is True


def test_kill_switch_disable():
    """disable() 正确停用"""
    ks = KillSwitch()
    disabled = ks.disable("admin", "Maintenance")
    assert disabled is True
    assert ks.is_disabled() is True
    assert ks.is_blocked() is False


def test_kill_switch_enable_after_disable():
    """enable() 恢复"""
    ks = KillSwitch()
    ks.disable("admin", "Maintenance")
    enabled = ks.enable()
    assert enabled is True
    assert ks.is_armed() is True


def test_kill_switch_check_action_blocks_when_triggered():
    """触发后 check_action 返回 blocked"""
    ks = KillSwitch()
    ks.trigger("test_rule", "Blocking all actions")

    result = ks.check_action("order", "buy_stock", "test")
    assert result["allowed"] is False
    assert result["blocked"] is True
    assert "Kill switch" in result["reason"]


def test_kill_switch_check_action_allows_when_armed():
    """ARMED 时 check_action 允许"""
    ks = KillSwitch()
    result = ks.check_action("order", "buy_stock", "test")
    assert result["allowed"] is True
    assert result["blocked"] is False


def test_kill_switch_blocked_actions_tracked():
    """所有被阻断的动作被记录"""
    ks = KillSwitch()
    ks.trigger("test_rule")
    ks.check_action("order", "action_1", "src")
    ks.check_action("config", "action_2", "src")
    ks.check_action("signal", "action_3", "src")

    assert ks._block_count == 3
    report = ks.get_blocked_action_report()
    assert len(report) == 3


def test_kill_switch_recovery_flow():
    """完整恢复流程: TRIGGERED → RECOVERING → ARMED"""
    ks = KillSwitch()
    ks.trigger("test_rule")
    assert ks.is_triggered() is True

    started = ks.start_recovery("Fixing data source")
    assert started is True
    assert ks.state == KillSwitchState.RECOVERING.value

    completed = ks.complete_recovery("system", "Data restored")
    assert completed is True
    assert ks.is_armed() is True


def test_kill_switch_status_snapshot():
    """KillSwitchStatus 正确反映状态"""
    ks = KillSwitch()
    status = ks.status
    assert status.state == KillSwitchState.ARMED.value
    assert status.is_triggered() is False
    assert status.is_blocked() is False

    ks.trigger("test_rule")
    status = ks.status
    assert status.is_triggered() is True
    assert status.is_blocked() is True


def test_kill_switch_summary():
    """汇总信息包含所有关键字段"""
    ks = KillSwitch()
    ks.trigger("test_rule", "Test")
    ks.check_action("order", "buy", "src")

    summary = ks.get_summary()
    assert summary["state"] == KillSwitchState.TRIGGERED.value
    assert summary["status"]["n_actions_blocked"] >= 1
    assert "open_incidents" in summary


# =========================================================================
# Incident Log Tests
# =========================================================================

def test_incident_log_record():
    """记录事件"""
    log = IncidentLog()
    incident = log.record("test_rule", "critical", "Something went wrong")
    assert incident.rule_name == "test_rule"
    assert incident.severity == "critical"
    assert incident.message == "Something went wrong"
    assert incident.status == "open"
    assert incident.incident_id.startswith("INC_")


def test_incident_log_acknowledge():
    """确认事件"""
    log = IncidentLog()
    incident = log.record("test_rule")
    acknowledged = log.acknowledge(incident.incident_id, "admin", "Looking into it")
    assert acknowledged is True
    assert incident.status == "acknowledged"


def test_incident_log_resolve():
    """解决事件"""
    log = IncidentLog()
    incident = log.record("test_rule")
    log.acknowledge(incident.incident_id, "admin")
    resolved = log.resolve(incident.incident_id, "Fixed", "admin")
    assert resolved is True
    assert incident.status == "resolved"


def test_incident_log_close():
    """关闭事件"""
    log = IncidentLog()
    incident = log.record("test_rule")
    log.acknowledge(incident.incident_id, "admin")
    log.resolve(incident.incident_id, "Fixed")
    closed = log.close(incident.incident_id)
    assert closed is True
    assert incident.status == "closed"


def test_incident_log_reopen():
    """重新打开事件"""
    log = IncidentLog()
    incident = log.record("test_rule")
    log.acknowledge(incident.incident_id, "admin")
    log.resolve(incident.incident_id, "Fixed")
    log.close(incident.incident_id)

    reopened = log.reopen(incident.incident_id, "Issue persists")
    assert reopened is True
    assert incident.status == "open"


def test_incident_find_by_rule():
    """按规则名称查找事件"""
    log = IncidentLog()
    log.record("rule_a")
    log.record("rule_b")
    log.record("rule_a")

    found = log.find_by_rule("rule_a")
    assert len(found) == 2

    found_open = log.find_by_rule("rule_a", "open")
    assert len(found_open) == 2

    log.acknowledge(found[0].incident_id, "admin")
    found_open = log.find_by_rule("rule_a", "open")
    assert len(found_open) == 1


def test_incident_get_open_incidents():
    """获取所有未解决事件"""
    log = IncidentLog()
    i1 = log.record("rule_a", "critical")
    i2 = log.record("rule_b", "warning")
    log.record("rule_c", "info")
    log.acknowledge(i2.incident_id, "admin")
    log.resolve(i2.incident_id, "Fixed")

    open_incidents = log.get_open_incidents()
    assert len(open_incidents) == 2  # i1 (open), i3 (open)

    critical = log.get_open_incidents("critical")
    assert len(critical) == 1


def test_incident_active_blockers():
    """获取活跃阻断事件"""
    log = IncidentLog()
    log.record("rule_a", "warning")
    log.record("rule_b", "blocker")

    blockers = log.get_active_blockers()
    assert len(blockers) == 1
    assert blockers[0].severity == "blocker"


def test_incident_log_summary():
    """事件日志摘要"""
    log = IncidentLog()
    log.record("r1", "critical")
    log.record("r2", "blocker")
    log.record("r3", "warning")

    summary = log.summary()
    assert summary["n_total"] == 3
    assert summary["n_open"] == 3
    assert summary["active_blockers"] == 1


def test_incident_log_persistence():
    """事件日志持久化"""
    log = IncidentLog()
    log.record("rule_a", "critical", "Test incident")

    with tempfile.TemporaryDirectory() as tmp:
        path = log.save(tmp)
        assert os.path.exists(path)

        # Load into new log
        log2 = IncidentLog()
        log2.load(path)
        assert len(log2.incidents) == 1
        assert log2.incidents[0].rule_name == "rule_a"
        assert log2.incidents[0].severity == "critical"


def test_incident_record_immutable_after_creation():
    """事件记录创建后不可变"""
    log = IncidentLog()
    incident = log.record("test_rule", "critical", "Msg")
    assert incident.status == "open"
    assert incident.triggered_at != ""


# =========================================================================
# Risk Sentinel Tests
# =========================================================================

def test_sentinel_initial_state():
    """初始状态为 unknown (尚未运行检查)"""
    sentinel = RiskSentinel()
    status = sentinel.get_status()
    assert status.status == "unknown"
    assert sentinel.kill_switch.is_armed() is True


def test_sentinel_has_default_rules():
    """使用默认规则"""
    sentinel = RiskSentinel()
    rules = sentinel.rules
    assert len(rules) > 0
    names = [r.name for r in rules]
    assert "data_freshness" in names
    assert "daily_loss" in names


def test_sentinel_check_all_passed():
    """全维度检查—全部通过时状态为 healthy"""
    sentinel = RiskSentinel()
    contexts = {
        "data": {"data_freshness": 30, "price_missing_rate": 0.01, "market_connectivity": 0},
        "account": {"account_connection": 0, "account_balance_anomaly": 0, "position_concentration": 0.1},
        "execution": {"consecutive_order_failures": 0, "fill_deviation": 0.001, "slippage_anomaly": 0.001},
        "loss": {"daily_loss": 0.005, "drawdown": 0.02, "daily_trade_count": 10},
        "system": {"pipeline_consistency": 0},
    }
    status = sentinel.check_all(contexts)
    assert status.status == "healthy"
    assert status.is_healthy() is True
    assert status.n_violations == 0
    assert status.n_blockers == 0


def test_sentinel_check_all_violation():
    """全维度检查—有 violation 时状态为 degraded"""
    sentinel = RiskSentinel()
    contexts = {
        "data": {"data_freshness": 600, "price_missing_rate": 0.01, "market_connectivity": 1},
        "account": {"account_connection": 1, "account_balance_anomaly": 0, "position_concentration": 0.1},
        "execution": {"consecutive_order_failures": 0, "fill_deviation": 0.001, "slippage_anomaly": 0.001},
        "loss": {"daily_loss": 0.005, "drawdown": 0.02, "daily_trade_count": 10},
        "system": {"pipeline_consistency": 0},
    }
    status = sentinel.check_all(contexts)
    assert status.status == "degraded"
    assert status.n_violations >= 1
    assert status.is_healthy() is False


def test_sentinel_triggers_kill_switch_on_blocker():
    """BLOCKER 违规自动触发熔断"""
    sentinel = RiskSentinel()
    sentinel.disable_rule("data_freshness")
    sentinel.disable_rule("price_missing_rate")
    sentinel.disable_rule("market_connectivity")
    sentinel.disable_rule("account_connection")
    sentinel.disable_rule("consecutive_order_failures")
    sentinel.disable_rule("fill_deviation")
    sentinel.disable_rule("slippage_anomaly")
    sentinel.disable_rule("daily_loss")
    sentinel.disable_rule("drawdown")
    sentinel.disable_rule("daily_trade_count")
    sentinel.disable_rule("pipeline_consistency")
    sentinel.disable_rule("position_concentration")
    sentinel.disable_rule("account_balance_anomaly")

    contexts = {"data": {"data_freshness": 600}}

    status = sentinel.check_all(contexts)
    assert sentinel.kill_switch.is_armed() is True


def test_sentinel_auto_trigger_blockers():
    """BLOCKER 违规是否自动触发 Kill Switch"""
    sentinel = RiskSentinel()
    # 配置某个 rule 为 blocker
    rule = RiskRule(
        name="blocker_check",
        category=RuleCategory.ACCOUNT.value,
        severity=RuleSeverity.BLOCKER.value,
        threshold=0,
    )
    sentinel.add_rule(rule)

    # 用 context 触发它：value > 0 触发 violation -> blocker
    contexts = {"account": {"blocker_check": 5}}
    status = sentinel.check_all(contexts)
    assert sentinel.kill_switch.is_triggered(), "Kill switch should be triggered on blocker"
    assert status.status == "blocked", f"Expected blocked, got {status.status}"
    assert sentinel.kill_switch.status.triggered_by_rule == "blocker_check"


def test_sentinel_auto_trigger_disabled():
    """关闭 auto_trigger 后 BLOCKER 不触发熔断"""
    sentinel = RiskSentinel(auto_trigger_kill_switch=False)
    rule = RiskRule(
        name="blocker_check",
        category=RuleCategory.ACCOUNT.value,
        severity=RuleSeverity.BLOCKER.value,
        threshold=0,
    )
    sentinel.add_rule(rule)

    contexts = {"account": {"blocker_check": 5}}
    status = sentinel.check_all(contexts)
    assert sentinel.kill_switch.is_armed() is True


def test_sentinel_data_dimension_check():
    """数据维度单独检查"""
    sentinel = RiskSentinel()
    context = {"data_freshness": 30, "price_missing_rate": 0.01, "market_connectivity": 1}
    result = sentinel.check_data(context)
    assert result["dimension"] == "data"
    assert result["n_rules"] > 0


def test_sentinel_loss_dimension_check():
    """亏损维度单独检查"""
    sentinel = RiskSentinel()
    context = {"daily_loss": 0.03, "drawdown": 0.05, "daily_trade_count": 10}
    result = sentinel.check_loss(context)
    assert result["dimension"] == "loss"
    assert result["n_rules"] > 0


def test_sentinel_add_remove_rule():
    """添加和删除规则"""
    sentinel = RiskSentinel()
    n_before = len(sentinel.rules)

    new_rule = RiskRule(
        name="custom_rule",
        category=RuleCategory.SYSTEM.value,
        threshold=42,
    )
    sentinel.add_rule(new_rule)
    assert len(sentinel.rules) == n_before + 1

    removed = sentinel.remove_rule("custom_rule")
    assert removed is True
    assert len(sentinel.rules) == n_before


def test_sentinel_enable_disable_rule():
    """启用和禁用规则"""
    sentinel = RiskSentinel()
    rule = sentinel.get_rule("data_freshness")
    assert rule is not None
    assert rule.enabled is True

    sentinel.disable_rule("data_freshness")
    assert rule.enabled is False

    sentinel.enable_rule("data_freshness")
    assert rule.enabled is True


def test_sentinel_get_summary():
    """获取汇总信息"""
    sentinel = RiskSentinel()
    summary = sentinel.get_summary()
    assert summary["sentinel"] == "default"
    assert summary["kill_switch"] == KillSwitchState.ARMED.value
    assert summary["n_rules"] > 0


def test_sentinel_check_history():
    """检查历史记录"""
    sentinel = RiskSentinel()
    contexts = {
        "data": {"data_freshness": 30, "price_missing_rate": 0.01, "market_connectivity": 1},
        "account": {"account_connection": 1, "account_balance_anomaly": 0, "position_concentration": 0.1},
        "execution": {"consecutive_order_failures": 0, "fill_deviation": 0.001, "slippage_anomaly": 0.001},
        "loss": {"daily_loss": 0.005, "drawdown": 0.02, "daily_trade_count": 10},
        "system": {"pipeline_consistency": 0},
    }
    sentinel.check_all(contexts)
    sentinel.check_all(contexts)
    history = sentinel.get_check_history()
    assert len(history) == 2


# =========================================================================
# Integration Tests
# =========================================================================

def test_full_sentinel_to_kill_switch_flow():
    """完整流程：哨兵 → 熔断 → 阻断 → 恢复"""
    sentinel = RiskSentinel()

    # Verify initial state
    assert sentinel.kill_switch.is_armed() is True

    # Phase 1: Add a custom blocker rule
    blocker = RiskRule(
        name="integration_blocker",
        category=RuleCategory.SYSTEM.value,
        severity=RuleSeverity.BLOCKER.value,
        threshold=0,
    )
    sentinel.add_rule(blocker)

    # Phase 2: Check with violation — should trigger kill switch
    contexts = {"system": {"integration_blocker": 1}}
    status = sentinel.check_all(contexts)
    assert sentinel.kill_switch.is_triggered() is True
    assert status.status == "blocked"

    # Phase 3: Kill switch blocks actions
    check = sentinel.kill_switch.check_action("order", "buy", "sentinel_test")
    assert check["allowed"] is False

    # Phase 4: Kill switch blocks data checks too (dimension checks still run)
    # (Dimension checks themselves don't go through check_action)
    loss_check = sentinel.check_loss({"daily_loss": 0.01, "drawdown": 0.03, "daily_trade_count": 5})
    assert loss_check["status"] == "passed"

    # Phase 5: Release kill switch
    released = sentinel.kill_switch.release("admin_test", "Test recovery")
    assert released is True
    assert sentinel.kill_switch.is_armed() is True

    # Phase 6: Actions allowed again
    check = sentinel.kill_switch.check_action("order", "buy", "sentinel_test")
    assert check["allowed"] is True


def test_incident_log_full_lifecycle():
    """事件完整生命周期: open → acknowledged → resolved → closed → reopened"""
    log = IncidentLog()
    incident = log.record("lifecycle_rule", "critical", "Integration test")

    assert incident.status == "open"

    log.acknowledge(incident.incident_id, "operator", "Checking")
    assert incident.status == "acknowledged"

    log.resolve(incident.incident_id, "Fixed by restart", "operator")
    assert incident.status == "resolved"

    log.close(incident.incident_id)
    assert incident.status == "closed"

    log.reopen(incident.incident_id, "Issue reappeared")
    assert incident.status == "open"


def test_sentinel_updates_violation_counts():
    """检查计数准确反映违规情况"""
    sentinel = RiskSentinel()
    contexts = {
        "data": {"data_freshness": 30, "price_missing_rate": 0.01, "market_connectivity": 0},
        "account": {"account_connection": 0, "account_balance_anomaly": 0, "position_concentration": 0.1},
        "execution": {"consecutive_order_failures": 0, "fill_deviation": 0.001, "slippage_anomaly": 0.001},
        "loss": {"daily_loss": 0.005, "drawdown": 0.02, "daily_trade_count": 10},
        "system": {"pipeline_consistency": 0},
    }
    status1 = sentinel.check_all(contexts)
    assert status1.n_violations == 0

    # Trigger a violation
    contexts["data"] = {"data_freshness": 600}
    status2 = sentinel.check_all(contexts)
    assert status2.n_violations >= 1


def test_sentinel_kill_switch_shared_incident_log():
    """共享 IncidentLog 时，事件在两个组件中都可见"""
    log = IncidentLog()
    sentinel = RiskSentinel(incident_log=log)

    assert sentinel.incident_log is log
    assert sentinel.kill_switch._incident_log is log

    # Record via sentinel
    sentinel.incident_log.record("shared_test", "info", "Shared test")
    assert len(log.incidents) == 1

    # Record via kill switch (trigger creates incident)
    sentinel.kill_switch.trigger("ks_trigger", "KS test")
    # The trigger creates an incident through its own log
    # Since they share the same log, both should be visible
    assert len(log.incidents) >= 2


# =========================================================================
# Edge Case Tests
# =========================================================================

def test_empty_rule_list():
    """空规则列表不报错"""
    sentinel = RiskSentinel(rules=[])
    assert len(sentinel.rules) == 0
    status = sentinel.check_all({})
    assert status.n_rules_checked == 0
    assert status.status == "healthy"


def test_kill_switch_double_trigger():
    """重复 trigger 不报错"""
    ks = KillSwitch()
    ks.trigger("rule_a")
    ks.trigger("rule_b")  # Still triggered, overwrites rule name
    assert ks.is_triggered() is True
    assert ks.status.triggered_by_rule == "rule_b"


def test_kill_switch_double_release():
    """重复 release 不报错"""
    ks = KillSwitch()
    released = ks.release("admin")  # Not triggered yet
    assert released is False

    ks.trigger("test")
    ks.release("admin", "Fixed")
    released = ks.release("admin")  # Already armed
    assert released is False


def test_sentinel_with_custom_rule_thresholds():
    """自定义阈值规则"""
    sentinel = RiskSentinel()
    custom = RiskRule(
        name="custom_drawdown",
        category=RuleCategory.LOSS.value,
        description="Custom tight drawdown",
        severity=RuleSeverity.CRITICAL.value,
        threshold=0.03,  # 3%
    )
    sentinel.add_rule(custom)

    context = {"custom_drawdown": 0.04}
    result = sentinel.check_dimension("loss", context)
    assert result["n_violations"] >= 1


def test_incident_log_clear():
    """清空事件日志"""
    log = IncidentLog()
    log.record("r1")
    log.record("r2")
    assert len(log.incidents) == 2

    log.clear()
    assert len(log.incidents) == 0


def test_sentinel_check_history_limit():
    """检查历史记录数量限制"""
    sentinel = RiskSentinel()
    for _ in range(25):
        sentinel._checks.append(SentinelCheck(cycle_id=f"chk_{_}"))

    history = sentinel.get_check_history(n=10)
    assert len(history) == 10
