"""V4.8 Capital Safety Boundary — Comprehensive Tests

Tests cover:
  - CapitalAllocation: limit configuration, check_allocation, order checks,
    usage tracking, daily limits
  - CapitalAuthority: tier permissions, action checks, amount thresholds,
    audit logging
  - CapitalSafetyMonitor: exposure checks, free capital, daily turnover,
    snapshots
  - CapitalIncidentProtection: rapid position changes, unusual order sizes,
    concentration detection
  - CapitalBoundaryEnforcer: integrated enforcement, check_all,
    usage recording, enable/disable
  - Convenience: build_capital_safety_boundaries, build_capital_safety_policy
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta
from factor_lab.execution.capital_boundary import (
    # Enums
    AuthorityTier,
    CapitalActionType,
    IncidentSeverity,
    # Allocation
    CapitalAllocationConfig,
    AllocationLimit,
    AllocationCheckResult,
    CapitalAllocation,
    # Authority
    CapitalAuthority,
    AuthorityCheckResult,
    # Monitor
    CapitalSafetyMonitor,
    CapitalUsageSnapshot,
    CapitalAlert,
    # Incident Protection
    CapitalIncidentProtection,
    CapitalIncidentAlert,
    # Enforcer
    CapitalBoundaryEnforcer,
    # Convenience
    build_capital_safety_boundaries,
    build_capital_safety_policy,
)

CST = timezone(timedelta(hours=8))


# =========================================================================
# CapitalAllocation Tests
# =========================================================================

class TestCapitalAllocationConfig:
    """CapitalAllocationConfig — limit configuration"""

    def test_default_config_has_sensible_limits(self):
        """默认配置包含合理的限制值"""
        config = CapitalAllocationConfig()
        assert config.total_capital == 1_000_000.0
        assert config.max_total_exposure_pct == 0.95
        assert config.min_free_capital == 50_000.0
        assert config.max_per_strategy_pct == 0.40
        assert config.max_per_asset_pct == 0.15
        assert config.max_single_order_capital == 200_000.0
        assert config.max_daily_orders == 50

    def test_get_limit_for_global(self):
        """获取全局限额"""
        config = CapitalAllocationConfig(total_capital=500_000.0)
        limit = config.get_limit_for("global")
        assert limit.scope == "global"
        assert limit.max_capital == 500_000.0
        assert limit.max_pct == 1.0
        assert limit.min_capital == 50_000.0

    def test_get_limit_for_strategy(self):
        """获取策略限额"""
        config = CapitalAllocationConfig(max_per_strategy_pct=0.35)
        limit = config.get_limit_for("strategy:mean_reversion")
        assert limit.scope == "strategy:mean_reversion"
        assert limit.max_pct == 0.35
        assert limit.description == "Per-strategy limit for mean_reversion"

    def test_get_limit_for_asset(self):
        """获取资产限额"""
        config = CapitalAllocationConfig(max_per_asset_capital=100_000.0)
        limit = config.get_limit_for("asset:000001.SZ")
        assert limit.scope == "asset:000001.SZ"
        assert limit.max_capital == 100_000.0

    def test_scope_override(self):
        """自定义范围覆盖"""
        config = CapitalAllocationConfig()
        override = AllocationLimit(
            scope="strategy:high_freq",
            max_capital=200_000.0,
            max_pct=0.20,
            description="Custom limit for high_freq",
        )
        config.set_override("strategy:high_freq", override)

        limit = config.get_limit_for("strategy:high_freq")
        assert limit.max_capital == 200_000.0
        assert limit.max_pct == 0.20

    def test_unknown_scope_returns_disabled_limit(self):
        """未知范围返回禁用限额"""
        config = CapitalAllocationConfig()
        limit = config.get_limit_for("unknown:scope")
        assert limit.enabled is False

    def test_to_dict(self):
        """序列化"""
        config = CapitalAllocationConfig(total_capital=2_000_000.0)
        d = config.to_dict()
        assert d["total_capital"] == 2_000_000.0
        assert "scope_overrides" in d


class TestCapitalAllocation:
    """CapitalAllocation — allocation checks and usage tracking"""

    def test_initial_usage_is_zero(self):
        """初始使用量为零"""
        alloc = CapitalAllocation()
        assert alloc.get_total_usage() == 0.0
        assert alloc.get_usage("strategy:a") == 0.0

    def test_record_usage_tracks_amount(self):
        """记录使用量"""
        alloc = CapitalAllocation()
        alloc.record_usage("strategy:a", 100_000.0)
        assert alloc.get_usage("strategy:a") == 100_000.0
        assert alloc.get_total_usage() == 100_000.0

    def test_record_usage_accumulates(self):
        """多次记录累加"""
        alloc = CapitalAllocation()
        alloc.record_usage("strategy:a", 50_000.0)
        alloc.record_usage("strategy:a", 30_000.0)
        assert alloc.get_usage("strategy:a") == 80_000.0

    def test_multiple_scopes(self):
        """多个范围独立跟踪"""
        alloc = CapitalAllocation()
        alloc.record_usage("strategy:a", 100_000.0)
        alloc.record_usage("strategy:b", 200_000.0)
        assert alloc.get_total_usage() == 300_000.0

    def test_available_capital(self):
        """可用资金计算"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(total_capital=1_000_000.0))
        alloc.record_usage("strategy:a", 300_000.0)
        assert alloc.get_available_capital() == 700_000.0

    def test_available_capital_never_negative(self):
        """可用资金不会为负"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(total_capital=100_000.0))
        alloc.record_usage("strategy:a", 999_999.0)
        assert alloc.get_available_capital() >= 0.0

    def test_reset_usage_clears_all(self):
        """重置清除所有使用量"""
        alloc = CapitalAllocation()
        alloc.record_usage("strategy:a", 100_000.0)
        alloc.record_daily_trade(50_000.0)
        alloc.reset_usage()
        assert alloc.get_total_usage() == 0.0
        assert alloc._daily_trade_count == 0
        assert alloc._daily_trade_capital == 0.0

    def test_check_allocation_within_limit(self):
        """分配检查—在限额内"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            max_per_strategy_pct=0.40,
        ))
        result = alloc.check_allocation("strategy:mean_reversion", 300_000.0)
        assert result.allowed is True
        assert result.blocked is False

    def test_check_allocation_exceeds_pct_limit(self):
        """分配检查—超过百分比限额"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            max_per_strategy_pct=0.40,
        ))
        # 41% of 1M = 410,000
        alloc.record_usage("strategy:mean_reversion", 100_000.0)
        result = alloc.check_allocation("strategy:mean_reversion", 320_000.0)
        assert result.allowed is False
        assert result.blocked is True
        assert "Percentage limit" in result.reason
        assert result.severity == "blocker"

    def test_check_allocation_exceeds_capital_limit(self):
        """分配检查—超过绝对金额限额"""
        config = CapitalAllocationConfig(total_capital=1_000_000.0)
        config.set_override("strategy:small_strat", AllocationLimit(
            scope="strategy:small_strat",
            max_capital=200_000.0,
        ))
        alloc = CapitalAllocation(config=config)
        result = alloc.check_allocation("strategy:small_strat", 250_000.0)
        assert result.allowed is False
        assert result.blocked is True
        assert "Capital limit" in result.reason

    def test_check_allocation_free_capital_reserve(self):
        """分配检查—自由资金保留"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            min_free_capital=100_000.0,
        ))
        alloc.record_usage("strategy:a", 850_000.0)
        # 850k used + 200k new = 1.05M > 1M, free = -50k < 100k
        result = alloc.check_allocation("global", 200_000.0)
        assert result.allowed is False
        assert result.blocked is True
        assert "free capital" in result.reason.lower()

    def test_check_order_single_order_limit(self):
        """订单检查—单笔金额限制"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            max_single_order_capital=200_000.0,
        ))
        result = alloc.check_order(250_000.0)
        assert result.allowed is False
        assert result.blocked is True
        assert "max single order" in result.reason.lower()

    def test_check_order_daily_limit(self):
        """订单检查—日内总额限制"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            max_daily_trade_capital=500_000.0,
        ))
        alloc.record_daily_trade(400_000.0)
        result = alloc.check_order(150_000.0)
        assert result.allowed is False
        assert result.blocked is True
        assert "daily trade capital" in result.reason.lower()

    def test_check_order_within_limits(self):
        """订单检查—在限额内"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            max_single_order_capital=200_000.0,
            max_daily_trade_capital=500_000.0,
        ))
        result = alloc.check_order(50_000.0)
        assert result.allowed is True

    def test_daily_order_count_limit(self):
        """日内订单数量限制"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            max_daily_orders=3,
        ))
        alloc.record_daily_trade(10_000.0)
        alloc.record_daily_trade(10_000.0)
        alloc.record_daily_trade(10_000.0)
        result = alloc.check_allocation("global", 10_000.0)
        assert result.allowed is False
        assert "order limit" in result.reason.lower()

    def test_daily_count_resets_on_new_day(self):
        """日内计数在新的一天重置"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            max_daily_orders=2,
        ))
        alloc.record_daily_trade(10_000.0)
        alloc.record_daily_trade(10_000.0)

        # Simulate next day by manipulating reset timestamp
        yesterday = datetime.now(CST) - timedelta(days=1)
        alloc._daily_reset_at = yesterday.isoformat()

        # Next record should reset
        alloc.record_daily_trade(10_000.0)
        assert alloc._daily_trade_count == 1  # Reset to 0, then +1


# =========================================================================
# CapitalAuthority Tests
# =========================================================================

class TestCapitalAuthority:
    """CapitalAuthority — tier permissions and amount thresholds"""

    def test_observer_can_only_view(self):
        """观察者只能查看"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.OBSERVER, CapitalActionType.VIEW_CAPITAL)
        assert result.allowed is True
        assert result.blocked is False

    def test_observer_cannot_execute_trade(self):
        """观察者不能执行交易"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.OBSERVER, CapitalActionType.EXECUTE_TRADE)
        assert result.allowed is False
        assert result.blocked is True
        assert "Requires at least" in result.reason

    def test_trader_can_execute_trade(self):
        """交易者可以执行交易"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.TRADER, CapitalActionType.EXECUTE_TRADE)
        assert result.allowed is True

    def test_trader_cannot_modify_allocation(self):
        """交易者不能修改分配"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.TRADER, CapitalActionType.MODIFY_ALLOCATION)
        assert result.allowed is False

    def test_strategist_can_modify_allocation(self):
        """策略者可以修改分配"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.STRATEGIST, CapitalActionType.MODIFY_ALLOCATION)
        assert result.allowed is True

    def test_admin_can_change_limits(self):
        """管理员可以修改限额"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.ADMIN, CapitalActionType.CHANGE_LIMITS)
        assert result.allowed is True

    def test_super_admin_can_override(self):
        """超级管理员可以覆盖边界"""
        auth = CapitalAuthority()
        result = auth.check_permission(AuthorityTier.SUPER_ADMIN, CapitalActionType.OVERRIDE_BOUNDARY)
        assert result.allowed is True

    def test_trader_amount_threshold_within_limit(self):
        """交易者金额阈值—在限额内"""
        auth = CapitalAuthority()
        result = auth.check_permission(
            AuthorityTier.TRADER,
            CapitalActionType.EXECUTE_TRADE,
            amount=50_000.0,
        )
        assert result.allowed is True
        assert result.amount_allowed is True

    def test_trader_amount_threshold_exceeded(self):
        """交易者金额阈值—超限"""
        auth = CapitalAuthority()
        result = auth.check_permission(
            AuthorityTier.TRADER,
            CapitalActionType.EXECUTE_TRADE,
            amount=200_000.0,  # Trader max is 100_000
        )
        assert result.allowed is False
        assert result.amount_allowed is False
        assert "threshold" in result.reason.lower()

    def test_strategist_higher_amount_threshold(self):
        """策略者金额阈值更高"""
        auth = CapitalAuthority()
        result = auth.check_permission(
            AuthorityTier.STRATEGIST,
            CapitalActionType.EXECUTE_TRADE,
            amount=200_000.0,  # Within strategist's 500k
        )
        assert result.allowed is True

    def test_audit_log_records_checks(self):
        """审计日志记录检查"""
        auth = CapitalAuthority()
        auth.check_permission(AuthorityTier.OBSERVER, CapitalActionType.EXECUTE_TRADE)
        auth.check_permission(AuthorityTier.TRADER, CapitalActionType.VIEW_CAPITAL)
        log = auth.get_audit_log()
        assert len(log) == 2
        assert log[0]["allowed"] is False
        assert log[1]["allowed"] is True

    def test_clear_audit_log(self):
        """清除审计日志"""
        auth = CapitalAuthority()
        auth.check_permission(AuthorityTier.OBSERVER, CapitalActionType.VIEW_CAPITAL)
        assert len(auth.get_audit_log()) == 1
        auth.clear_audit_log()
        assert len(auth.get_audit_log()) == 0

    def test_tier_has_permission(self):
        """权限检查辅助方法"""
        assert CapitalAuthority.tier_has_permission(AuthorityTier.OBSERVER, CapitalActionType.VIEW_CAPITAL) is True
        assert CapitalAuthority.tier_has_permission(AuthorityTier.OBSERVER, CapitalActionType.EXECUTE_TRADE) is False
        assert CapitalAuthority.tier_has_permission(AuthorityTier.SUPER_ADMIN, CapitalActionType.DISABLE_SAFETY) is True

    def test_get_required_tier(self):
        """获取所需最低权限"""
        assert CapitalAuthority.get_required_tier(CapitalActionType.VIEW_CAPITAL) == AuthorityTier.OBSERVER
        assert CapitalAuthority.get_required_tier(CapitalActionType.DISABLE_SAFETY) == AuthorityTier.SUPER_ADMIN

    def test_amount_threshold_for_tier(self):
        """获取权限金额阈值"""
        assert CapitalAuthority.get_tier_threshold(AuthorityTier.TRADER) == 100_000.0
        assert CapitalAuthority.get_tier_threshold(AuthorityTier.SUPER_ADMIN) == float("inf")


# =========================================================================
# CapitalSafetyMonitor Tests
# =========================================================================

class TestCapitalSafetyMonitor:
    """CapitalSafetyMonitor — monitoring and alerts"""

    def test_initial_no_alerts(self):
        """初始无告警"""
        monitor = CapitalSafetyMonitor()
        alerts = monitor.check_all()
        assert len(alerts) == 0

    def test_exposure_alert_when_over_limit(self):
        """暴露超限时生成告警"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            max_total_exposure_pct=0.50,
        ))
        alloc.record_usage("strategy:a", 600_000.0)  # 60% > 50%
        monitor = CapitalSafetyMonitor(allocation=alloc)
        alerts = monitor.check_exposure()
        assert len(alerts) >= 1
        assert alerts[0].category == "exposure"

    def test_free_capital_alert_when_below_minimum(self):
        """自由资金低于最低时生成告警"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            min_free_capital=100_000.0,
        ))
        alloc.record_usage("strategy:a", 950_000.0)  # Free = 50k < 100k
        monitor = CapitalSafetyMonitor(allocation=alloc)
        alerts = monitor.check_exposure()
        free_alerts = [a for a in alerts if a.category == "exposure" and "free capital" in a.message.lower()]
        assert len(free_alerts) >= 1

    def test_daily_turnover_alert(self):
        """日内换手率超限时生成告警"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            max_daily_turnover_pct=0.30,
        ))
        alloc._daily_trade_capital = 400_000.0  # 40% > 30%
        monitor = CapitalSafetyMonitor(allocation=alloc)
        alerts = monitor.check_exposure()
        turnover_alerts = [a for a in alerts if a.category == "exposure" and "turnover" in a.message.lower()]
        assert len(turnover_alerts) >= 1

    def test_snapshot_contains_all_fields(self):
        """快照包含所有字段"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(total_capital=1_000_000.0))
        alloc.record_usage("strategy:a", 200_000.0)
        alloc.record_usage("asset:000001.SZ", 100_000.0)
        alloc.record_daily_trade(50_000.0)
        monitor = CapitalSafetyMonitor(allocation=alloc)
        snap = monitor.snapshot()
        assert snap.total_capital == 1_000_000.0
        assert snap.total_used == 300_000.0
        assert snap.total_free == 700_000.0
        assert snap.daily_trade_count == 1
        assert snap.daily_trade_capital == 50_000.0
        assert "strategy:a" in snap.per_strategy
        assert "asset:000001.SZ" in snap.per_asset

    def test_get_alerts_filtered(self):
        """按严重程度过滤告警"""
        alloc = CapitalAllocation(config=CapitalAllocationConfig(
            total_capital=1_000_000.0,
            max_total_exposure_pct=0.50,
            min_free_capital=100_000.0,
        ))
        alloc.record_usage("strategy:a", 960_000.0)  # Both exposure and free capital triggered
        monitor = CapitalSafetyMonitor(allocation=alloc)
        monitor.check_exposure()
        warnings = monitor.get_alerts(severity="warning")
        assert len(warnings) >= 1

    def test_clear_alerts(self):
        """清除告警"""
        monitor = CapitalSafetyMonitor()
        monitor._alerts.append(CapitalAlert(alert_id="test1", severity="warning", message="test"))
        assert len(monitor.get_alerts()) == 1
        monitor.clear_alerts()
        assert len(monitor.get_alerts()) == 0


# =========================================================================
# CapitalIncidentProtection Tests
# =========================================================================

class TestCapitalIncidentProtection:
    """CapitalIncidentProtection — abnormal pattern detection"""

    def test_no_alerts_with_no_trades(self):
        """无交易记录时无告警"""
        protector = CapitalIncidentProtection()
        alerts = protector.check_all()
        assert len(alerts) == 0

    def test_rapid_position_change_detected(self):
        """检测快速仓位变化"""
        protector = CapitalIncidentProtection()
        protector.max_position_change_pct = 0.30  # 30% per hour

        symbol = "000001.SZ"
        # Record initial position
        protector.record_trade(symbol, 100_000.0, "buy")
        protector.record_trade(symbol, 100_000.0, "buy")

        # Large additional position
        protector.record_trade(symbol, 100_000.0, "buy")  # 200k -> 300k = 50% change

        alerts = protector.check_rapid_position_change()
        rapid = [a for a in alerts if a.pattern == "rapid_position_change"]
        # The 3rd change of 100k when base is 200k = 100k/(200k+100k) = 33% > 30%
        # But our calculation: cumulative first two = 200k, total changes = 300k, recent = 300k (all in last hour)
        # total_delta = 300k, base = 0 (all changes are recent)
        # change_pct = 300/(0+300) = 100% > 30%
        # This triggers
        assert len(rapid) >= 1

    def test_unusual_order_size_detected(self):
        """检测异常订单大小"""
        protector = CapitalIncidentProtection()
        protector.unusual_size_multiplier = 2.0

        # Record some normal trades
        for _ in range(10):
            protector.record_trade("000001.SZ", 10_000.0, "buy")

        # An unusually large trade
        protector.record_trade("000001.SZ", 100_000.0, "buy")

        alerts = protector.check_unusual_order_size()
        unusual = [a for a in alerts if a.pattern == "unusual_size"]
        # With 10 samples of 10k each, mean=10k, std≈0
        # The 100k should be many stddevs above
        assert len(unusual) >= 1

    def test_concentration_detected(self):
        """检测过度集中"""
        protector = CapitalIncidentProtection()
        protector.max_concentration_pct = 0.70

        # Most activity in one symbol
        protector.record_trade("000001.SZ", 900_000.0, "buy")
        protector.record_trade("000002.SZ", 100_000.0, "buy")

        alerts = protector.check_concentration()
        conc = [a for a in alerts if a.pattern == "concentration"]
        assert len(conc) >= 1
        assert conc[0].scope == "000001.SZ"

    def test_no_concentration_alert_when_diversified(self):
        """分散投资不触发集中度告警"""
        protector = CapitalIncidentProtection()
        for i in range(10):
            protector.record_trade(f"{i:06d}.SZ", 100_000.0, "buy")

        alerts = protector.check_concentration()
        conc = [a for a in alerts if a.pattern == "concentration"]
        assert len(conc) == 0

    def test_not_enough_data_for_unusual_size(self):
        """数据不足时不检测异常大小"""
        protector = CapitalIncidentProtection()
        protector.record_trade("000001.SZ", 10_000.0, "buy")
        protector.record_trade("000001.SZ", 100_000.0, "buy")
        alerts = protector.check_unusual_order_size()
        unusual = [a for a in alerts if a.pattern == "unusual_size"]
        assert len(unusual) == 0  # Need >= 5 trades

    def test_get_alerts_filtered_by_severity_and_pattern(self):
        """按严重程度和模式过滤告警"""
        protector = CapitalIncidentProtection()
        protector._alerts.append(CapitalIncidentAlert(
            alert_id="t1", severity="warning", pattern="rapid_position_change",
        ))
        protector._alerts.append(CapitalIncidentAlert(
            alert_id="t2", severity="critical", pattern="concentration",
        ))

        assert len(protector.get_alerts(severity="warning")) == 1
        assert len(protector.get_alerts(pattern="concentration")) == 1
        assert len(protector.get_alerts(severity="critical", pattern="concentration")) == 1

    def test_clear_history(self):
        """清除历史"""
        protector = CapitalIncidentProtection()
        protector.record_trade("000001.SZ", 10_000.0, "buy")
        assert len(protector._trade_history) == 1
        protector.clear_history()
        assert len(protector._trade_history) == 0
        assert len(protector._alerts) == 0


# =========================================================================
# CapitalBoundaryEnforcer Tests
# =========================================================================

class TestCapitalBoundaryEnforcer:
    """CapitalBoundaryEnforcer — integrated enforcement"""

    def test_enforcer_is_enabled_by_default(self):
        """默认启用"""
        enforcer = CapitalBoundaryEnforcer()
        assert enforcer.is_enabled is True

    def test_enable_disable(self):
        """启用/禁用控制"""
        enforcer = CapitalBoundaryEnforcer()
        enforcer.disable("testing")
        assert enforcer.is_enabled is False
        enforcer.enable()
        assert enforcer.is_enabled is True

    def test_disabled_enforcer_blocks_all(self):
        """禁用后阻止所有操作"""
        enforcer = CapitalBoundaryEnforcer()
        enforcer.disable("maintenance")
        result = enforcer.check_all(
            tier=AuthorityTier.SUPER_ADMIN,
            action=CapitalActionType.VIEW_CAPITAL,
            scope="global",
        )
        assert result["allowed"] is False
        assert result["blocked_by"] == "enabled"

    def test_authority_block_propagates(self):
        """权限阻止传播到最终结果"""
        enforcer = CapitalBoundaryEnforcer()
        result = enforcer.check_all(
            tier=AuthorityTier.OBSERVER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="strategy:a",
            amount=50_000.0,
        )
        assert result["allowed"] is False
        assert result["blocked_by"] == "authority"

    def test_allocation_block_propagates(self):
        """分配阻止传播到最终结果"""
        enforcer = CapitalBoundaryEnforcer(allocation=CapitalAllocation(
            config=CapitalAllocationConfig(
                total_capital=1_000_000.0,
                max_per_strategy_pct=0.10,
            ),
        ))
        result = enforcer.check_all(
            tier=AuthorityTier.STRATEGIST,
            action=CapitalActionType.MODIFY_ALLOCATION,
            scope="strategy:big_strat",
            amount=200_000.0,  # 20% > 10%
        )
        assert result["allowed"] is False
        assert result["blocked_by"] == "allocation"

    def test_order_limit_block(self):
        """订单限额阻止"""
        enforcer = CapitalBoundaryEnforcer(allocation=CapitalAllocation(
            config=CapitalAllocationConfig(max_single_order_capital=50_000.0),
        ))
        result = enforcer.check_all(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=100_000.0,  # > 50k
        )
        assert result["allowed"] is False
        assert result["blocked_by"] == "order_limit"

    def test_all_checks_pass(self):
        """所有检查通过"""
        enforcer = CapitalBoundaryEnforcer()
        result = enforcer.check_all(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=50_000.0,
            symbol="000001.SZ",
        )
        assert result["allowed"] is True
        assert result["blocked"] is False
        # Should have checks for: enabled, authority, allocation, order_limit, incident_protection
        assert len(result["checks"]) >= 4

    def test_record_trade_updates_state(self):
        """记录交易更新状态"""
        enforcer = CapitalBoundaryEnforcer()
        enforcer.record_trade("000001.SZ", 50_000.0, "buy", "asset:000001.SZ")
        assert enforcer.allocation.get_usage("asset:000001.SZ") == 50_000.0
        assert enforcer.allocation._daily_trade_count == 1
        assert len(enforcer.incident_protection._trade_history) == 1

    def test_reset_clears_all_state(self):
        """重置清除所有状态"""
        enforcer = CapitalBoundaryEnforcer()
        enforcer.record_trade("000001.SZ", 50_000.0, "buy", "asset:000001.SZ")
        enforcer.check_all(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=10_000.0,
        )
        assert len(enforcer._check_history) > 0
        enforcer.reset()
        assert enforcer.allocation.get_total_usage() == 0.0
        assert len(enforcer._check_history) == 0
        assert len(enforcer._blocked_actions) == 0

    def test_report_contains_all_sections(self):
        """报告包含所有章节"""
        enforcer = CapitalBoundaryEnforcer()
        report = enforcer.get_report()
        assert report["version"] == "V4.8"
        assert "capital_usage" in report
        assert "alerts" in report
        assert "monitor_alerts" in report
        assert "authority_audit" in report
        assert "n_checks" in report
        assert "n_blocked" in report

    def test_convenience_boundaries_created(self):
        """便利函数创建边界"""
        boundaries = build_capital_safety_boundaries()
        assert len(boundaries) >= 5
        names = [b.name for b in boundaries]
        assert "capital_allocation_limit" in names
        assert "capital_authority_tier" in names
        assert "capital_exposure_limit" in names
        assert "capital_incident_protection" in names
        assert "daily_trade_limits" in names

    def test_convenience_policy_created(self):
        """便利函数创建策略"""
        policy = build_capital_safety_policy()
        assert policy.name == "V4.8 Capital Safety Policy"
        assert policy.version == "V4.8"
        assert len(policy.boundaries) >= 5


# =========================================================================
# Integration Tests
# =========================================================================

class TestCapitalSafetyIntegration:
    """Capital Safety Boundary — integration tests"""

    def test_full_enforcement_cycle(self):
        """完整执行周期"""
        enforcer = CapitalBoundaryEnforcer()

        # 1. Observer tries to execute trade → blocked by authority
        result = enforcer.check_all(
            tier=AuthorityTier.OBSERVER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=10_000.0,
        )
        assert result["allowed"] is False

        # 2. Trader executes small trade → allowed
        result = enforcer.check_all(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=10_000.0,
            symbol="000001.SZ",
        )
        assert result["allowed"] is True
        enforcer.record_trade("000001.SZ", 10_000.0, "buy", "asset:000001.SZ")

        # 3. Trader tries large trade → blocked by amount threshold
        result = enforcer.check_all(
            tier=AuthorityTier.TRADER,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=500_000.0,  # Exceeds trader's 100k limit
        )
        assert result["allowed"] is False
        assert result["blocked_by"] == "authority"

        # 4. Generate report
        report = enforcer.get_report()
        assert report["n_checks"] >= 3
        assert report["n_blocked"] >= 2
        assert report["capital_usage"]["total_used"] == 10_000.0

    def test_safety_never_blocks_super_admin_within_limits(self):
        """超级管理员在限额内不被阻止"""
        enforcer = CapitalBoundaryEnforcer()
        result = enforcer.check_all(
            tier=AuthorityTier.SUPER_ADMIN,
            action=CapitalActionType.EXECUTE_TRADE,
            scope="asset:000001.SZ",
            amount=100_000.0,
            symbol="000001.SZ",
        )
        assert result["allowed"] is True

    def test_permission_escalation(self):
        """权限升级流程"""
        auth = CapitalAuthority()

        # Observer cannot trade
        assert auth.check_permission(
            AuthorityTier.OBSERVER, CapitalActionType.EXECUTE_TRADE
        ).allowed is False

        # Trader can trade
        assert auth.check_permission(
            AuthorityTier.TRADER, CapitalActionType.EXECUTE_TRADE
        ).allowed is True

        # Trader cannot modify allocation
        assert auth.check_permission(
            AuthorityTier.TRADER, CapitalActionType.MODIFY_ALLOCATION
        ).allowed is False

        # Strategist can modify allocation
        assert auth.check_permission(
            AuthorityTier.STRATEGIST, CapitalActionType.MODIFY_ALLOCATION
        ).allowed is True

        # Strategist cannot change limits
        assert auth.check_permission(
            AuthorityTier.STRATEGIST, CapitalActionType.CHANGE_LIMITS
        ).allowed is False

        # Admin can change limits
        assert auth.check_permission(
            AuthorityTier.ADMIN, CapitalActionType.CHANGE_LIMITS
        ).allowed is True
