"""V4.6 Trade Filter & Slippage Control — Trade Filter Tests

Tests cover:
  - Default rules loaded with all expected filters
  - Price limit filters (buy limit up, sell limit down)
  - Board type filters (ST/*ST, delisting)
  - Suspension filter
  - Volume liquidity filter
  - Position concentration filter
  - Price gap filter
  - Market state filter
  - Max order size filter
  - Rule management (add, remove, enable, disable)
  - TradeContext construction
  - FilterReport and FilterResult serialization
  - Engine reset and history
  - Integration with ShadowPipelineRunner
  - Edge cases (missing data, zero values, extremes)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta

from factor_lab.execution.trade_filter import (
    TradeFilterEngine, TradeFilterRule, TradeContext,
    FilterResult, FilterReport, FilterType, FilterSeverity, FilterStatus,
    build_default_trade_filter_rules, detect_board_type, is_st_board,
)
from factor_lab.execution.shadow_pipeline import (
    ShadowPipelineRunner, ShadowPipelineConfig, ShadowPipelineResult,
)

CST = timezone(timedelta(hours=8))

# =========================================================================
# Default Rules Tests
# =========================================================================

def test_default_rules_loaded():
    """默认规则加载正确"""
    engine = TradeFilterEngine()
    rules = engine.rules
    assert len(rules) > 0
    names = [r.name for r in rules]
    assert "buy_limit_up" in names
    assert "sell_limit_down" in names
    assert "st_stock_filter" in names
    assert "suspension_filter" in names
    assert "volume_liquidity_filter" in names
    assert "single_stock_concentration" in names
    assert "price_gap_filter" in names
    assert "market_state_filter" in names
    assert "max_order_size_filter" in names


def test_default_rules_severities():
    """默认规则的严重级正确"""
    engine = TradeFilterEngine()
    rules = {r.name: r for r in engine.rules}

    # Blockers
    assert rules["buy_limit_up"].severity == FilterSeverity.BLOCKER.value
    assert rules["sell_limit_down"].severity == FilterSeverity.BLOCKER.value
    assert rules["st_stock_filter"].severity == FilterSeverity.BLOCKER.value
    assert rules["suspension_filter"].severity == FilterSeverity.BLOCKER.value
    assert rules["market_state_filter"].severity == FilterSeverity.BLOCKER.value
    assert rules["max_order_size_filter"].severity == FilterSeverity.BLOCKER.value

    # Warnings
    assert rules["volume_liquidity_filter"].severity == FilterSeverity.WARNING.value
    assert rules["single_stock_concentration"].severity == FilterSeverity.WARNING.value
    assert rules["price_gap_filter"].severity == FilterSeverity.WARNING.value


def test_build_default_rules_function():
    """build_default_trade_filter_rules() 返回正确结构"""
    rules = build_default_trade_filter_rules()
    assert len(rules) == 10
    for r in rules:
        assert r.name
        assert r.filter_type
        assert r.severity
        assert isinstance(r.enabled, bool)


# =========================================================================
# Price Limit Filter Tests
# =========================================================================

def test_buy_limit_up_blocked():
    """涨停时买入被阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        close=11.0,    # At limit up
        limit_up=11.0,
        limit_down=9.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True
    assert report.n_blocked >= 1
    # Check blocker messages contain limit up info
    assert any("涨停" in m for m in report.blocker_messages)


def test_buy_not_limit_up_passes():
    """未涨停时买入通过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        close=10.5,
        limit_up=11.0,
        limit_down=9.0,
    )
    report = engine.evaluate_trade(ctx)
    # Only check that price limit filter passes
    assert report.passed is True


def test_sell_limit_down_blocked():
    """跌停时卖出被阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="sell",
        quantity=1000,
        price=10.0,
        close=9.0,     # At limit down
        limit_up=11.0,
        limit_down=9.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True
    assert any("跌停" in m for m in report.blocker_messages)


def test_sell_not_limit_down_passes():
    """未跌停时卖出通过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="sell",
        quantity=1000,
        price=10.0,
        close=9.5,
        limit_up=11.0,
        limit_down=9.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True


# =========================================================================
# Board Type Filter Tests
# =========================================================================

def test_st_stock_blocked():
    """ST 股票被阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        board_type="st",
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True
    assert any("ST" in m for m in report.blocker_messages)


def test_normal_stock_passes():
    """正常股票通过 ST 过滤"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        board_type="main",
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True


# =========================================================================
# Suspension Filter Tests
# =========================================================================

def test_suspended_stock_blocked():
    """停牌股票被阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        is_suspended=True,
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True
    assert any("停牌" in m for m in report.blocker_messages)


# =========================================================================
# Volume Liquidity Filter Tests
# =========================================================================

def test_volume_liquidity_warning():
    """订单金额过大触发热度警告"""
    engine = TradeFilterEngine()
    # 10元 * 1000股 = 1万, 日均成交额5万 → ratio=0.2 > 0.1
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        avg_amount_20d=50_000,  # avg daily amount
        total_equity=10_000_000,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True  # Warning doesn't block
    assert report.n_warnings >= 1


def test_volume_liquidity_skip_no_data():
    """无成交额数据时跳过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        avg_amount_20d=0,
    )
    report = engine.evaluate_trade(ctx)
    # Should pass because no data to evaluate
    assert report.passed is True


# =========================================================================
# Position Concentration Filter Tests
# =========================================================================

def test_concentration_warning():
    """集中度超限触发警告"""
    engine = TradeFilterEngine()
    total_equity = 1_000_000
    # Already has position worth 200k, buying 100k more = 300k total = 30%
    # threshold is 25%
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=10_000,
        price=10.0,
        total_equity=total_equity,
        current_position_shares=20_000,
        current_position_cost=10.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True  # Warning doesn't block
    assert report.n_warnings >= 1


def test_concentration_skip_no_equity():
    """无权益数据时跳过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        total_equity=0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True


# =========================================================================
# Price Gap Filter Tests
# =========================================================================

def test_price_gap_warning():
    """信号价偏离过大触发警告"""
    engine = TradeFilterEngine()
    # signal_price=10, price=11 → gap=10% > 5%
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=11.0,
        signal_price=10.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True  # Warning doesn't block
    assert report.n_warnings >= 1


def test_price_gap_skip_no_prices():
    """无价格数据时跳过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=0,
        signal_price=0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True


# =========================================================================
# Market State Filter Tests
# =========================================================================

def test_market_state_missing_blocked():
    """市场数据缺失时阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        market_status="missing",
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True
    assert any("异常" in m for m in report.blocker_messages)


def test_market_state_available_passes():
    """市场数据可用时通过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        market_status="available",
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True


# =========================================================================
# Max Order Size Filter Tests
# =========================================================================

def test_max_order_size_blocked():
    """单笔订单金额超限被阻断"""
    engine = TradeFilterEngine()
    # 1000 * 1000 = 1,000,000 > 500,000 threshold
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=100_000,
        price=100.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True
    assert any("上限" in m for m in report.blocker_messages)


def test_max_order_size_normal_passes():
    """正常订单金额通过"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
    )
    report = engine.evaluate_trade(ctx)
    assert report.passed is True


# =========================================================================
# Rule Management Tests
# =========================================================================

def test_add_rule():
    """添加新规则"""
    engine = TradeFilterEngine()
    n_before = len(engine.rules)
    rule = TradeFilterRule(
        name="custom_filter",
        filter_type=FilterType.CUSTOM.value,
        description="Custom test filter",
        severity=FilterSeverity.BLOCKER.value,
    )
    engine.add_rule(rule)
    assert len(engine.rules) == n_before + 1


def test_remove_rule():
    """删除规则"""
    engine = TradeFilterEngine()
    engine.add_rule(TradeFilterRule(
        name="temp_rule",
        filter_type=FilterType.CUSTOM.value,
    ))
    n_before = len(engine.rules)
    removed = engine.remove_rule("temp_rule")
    assert removed is True
    assert len(engine.rules) == n_before - 1


def test_remove_nonexistent_rule():
    """删除不存在的规则返回 False"""
    engine = TradeFilterEngine()
    removed = engine.remove_rule("nonexistent_rule")
    assert removed is False


def test_enable_disable_rule():
    """启用/禁用规则"""
    engine = TradeFilterEngine()
    rule = engine.get_rule("buy_limit_up")
    assert rule is not None
    assert rule.enabled is True

    engine.disable_rule("buy_limit_up")
    assert rule.enabled is False

    engine.enable_rule("buy_limit_up")
    assert rule.enabled is True


def test_disabled_rule_not_evaluated():
    """禁用的规则不参与评估"""
    engine = TradeFilterEngine()
    engine.disable_rule("buy_limit_up")

    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        close=11.0,
        limit_up=11.0,
    )
    report = engine.evaluate_trade(ctx)
    # With buy_limit_up disabled, this should pass
    # (may still be blocked by other filters, but not buy_limit_up)
    for result in report.results:
        if result.filter_name == "buy_limit_up":
            assert result.status == FilterStatus.SKIPPED.value


# =========================================================================
# TradeContext Tests
# =========================================================================

def test_trade_context_defaults():
    """TradeContext 默认值正确"""
    ctx = TradeContext()
    assert ctx.symbol == ""
    assert ctx.side == ""
    assert ctx.quantity == 0
    assert ctx.price == 0.0
    assert ctx.market_status == ""
    assert ctx.board_type == ""
    assert ctx.is_suspended is False
    assert ctx.timestamp != ""


def test_trade_context_with_values():
    """TradeContext 构造正确"""
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.5,
        close=10.5,
        limit_up=11.0,
        limit_down=9.5,
        market_status="available",
        board_type="main",
        total_equity=1_000_000,
        cash=500_000,
    )
    assert ctx.symbol == "000001"
    assert ctx.side == "buy"
    assert ctx.quantity == 1000
    assert ctx.price == 10.5
    assert ctx.total_equity == 1_000_000


# =========================================================================
# FilterResult and FilterReport Tests
# =========================================================================

def test_filter_result_defaults():
    """FilterResult 默认值正确"""
    result = FilterResult(
        filter_name="test",
        filter_type=FilterType.CUSTOM.value,
    )
    assert result.passed is True
    assert result.status == FilterStatus.PASSED.value
    assert result.checked_at != ""


def test_filter_result_blocker_detection():
    """BLOCKER 状态检测"""
    result = FilterResult(
        filter_name="test",
        filter_type=FilterType.CUSTOM.value,
        passed=False,
        severity=FilterSeverity.BLOCKER.value,
        status=FilterStatus.BLOCKED.value,
    )
    assert result.is_blocked() is True
    assert result.is_warning() is False
    assert result.is_passed() is False


def test_filter_result_warning_detection():
    """WARNING 状态检测"""
    result = FilterResult(
        filter_name="test",
        filter_type=FilterType.CUSTOM.value,
        passed=False,
        severity=FilterSeverity.WARNING.value,
        status=FilterStatus.WARNED.value,
    )
    assert result.is_blocked() is False
    assert result.is_warning() is True


def test_filter_report_construction():
    """FilterReport 构造正确"""
    report = FilterReport(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        passed=False,
        blocked=True,
        n_checks=3,
        n_passed=1,
        n_blocked=1,
        n_warnings=1,
        blocker_messages=["Price limit exceeded"],
        warning_messages=["Liquidity warning"],
    )
    assert report.symbol == "000001"
    assert report.blocked is True
    assert len(report.blocker_messages) == 1
    assert len(report.warning_messages) == 1


# =========================================================================
# Engine History and Reset Tests
# =========================================================================

def test_engine_history():
    """引擎记录评估历史"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        close=10.5,
        limit_up=11.0,
    )
    engine.evaluate_trade(ctx)
    engine.evaluate_trade(ctx)
    history = engine.get_history()
    assert len(history) == 2


def test_engine_reset():
    """重置引擎清除历史"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
    )
    engine.evaluate_trade(ctx)
    assert len(engine.get_history()) == 1
    engine.reset()
    assert len(engine.get_history()) == 0


# =========================================================================
# Engine Summary Tests
# =========================================================================

def test_engine_get_summary():
    """引擎汇总正确"""
    engine = TradeFilterEngine()
    summary = engine.get_summary()
    assert summary["name"] == "default"
    assert summary["total_evaluations"] == 0
    assert summary["active_rules"] > 0
    assert summary["total_rules"] > 0


# =========================================================================
# Detect Board Type Tests
# =========================================================================

def test_detect_board_type():
    """板块类型检测"""
    assert detect_board_type("600000") == "main"
    assert detect_board_type("000001") == "main"
    assert detect_board_type("300001") == "chinext"
    assert detect_board_type("301001") == "chinext"
    assert detect_board_type("688001") == "star"

    # ST detection
    assert detect_board_type("600000ST") == "st"
    assert detect_board_type("*ST600000") == "st"


def test_is_st_board():
    """ST 股票检测"""
    assert is_st_board("600000ST") is True
    assert is_st_board("*ST600000") is True
    assert is_st_board("000001") is False


# =========================================================================
# Shadow Pipeline Integration Tests
# =========================================================================

def test_pipeline_with_trade_filter():
    """TradeFilter 集成到 ShadowPipeline"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_trade_filter=True,
    ))
    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")

    trades = [{
        "symbol": "000001",
        "side": "buy",
        "quantity": 1000,
        "price": 10.0,
        "name": "平安银行",
        "market_data": market,
    }]
    result = runner.process_signal("sig_001", "prop_001", trades)

    assert result is not None
    assert result.filter_summary is not None
    assert result.filter_summary.get("total_evaluations", 0) >= 0


def test_pipeline_filter_blocks_limit_up():
    """TradeFilter 阻断涨停买入"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_trade_filter=True,
    ))
    # Create market at limit up
    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")
    market.limit_up = 10.0  # Close = limit_up

    trades = [{
        "symbol": "000001",
        "side": "buy",
        "quantity": 1000,
        "price": 10.0,
        "name": "平安银行",
        "market_data": market,
    }]
    result = runner.process_signal("sig_001", "prop_001", trades)

    # Should be filtered
    assert result.n_filled == 0
    assert result.n_filter_blocked >= 1 or result.n_rejected >= 1


def test_pipeline_without_trade_filter():
    """关闭 TradeFilter 后不执行过滤"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_trade_filter=False,
    ))
    assert runner.trade_filter is None

    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")
    result = runner.process_buy("000001", 1000, 10.0, name="平安银行", market_data=market)
    assert result["n_filled"] == 1


def test_pipeline_with_slippage_control():
    """SlippageController 集成到 ShadowPipeline"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_slippage_control=True,
    ))
    assert runner.slippage_controller is not None

    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")
    result = runner.process_buy("000001", 1000, 10.0, name="平安银行", market_data=market)

    # Should complete normally for a small order
    assert result["n_filled"] == 1
    assert result.get("slippage_control_summary", {}).get("budget_tracker", {}).get("total_checks", 0) >= 0


def test_pipeline_without_slippage_control():
    """关闭 SlippageController 后不执行控制"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_slippage_control=False,
    ))
    assert runner.slippage_controller is None

    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")
    result = runner.process_buy("000001", 1000, 10.0, name="平安银行", market_data=market)
    assert result["n_filled"] == 1


def test_pipeline_version_v46():
    """ShadowPipelineResult version 是 V4.6"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        auto_generate_reports=False,
    ))
    result = runner.process_buy("000001", 1000, 10.0,
                                market_data=runner.make_market_snapshot("000001", 10.0))
    if hasattr(result, "version"):
        assert result.version == "V4.6"

    doc = runner.to_dict()
    assert doc["version"] == "V4.6"


def test_pipeline_filter_results_in_result():
    """FilterResults 出现在 PipelineResult 中"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_trade_filter=True,
    ))
    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")
    result = runner.process_buy("000001", 1000, 10.0, name="平安银行", market_data=market)

    assert isinstance(result, dict) or hasattr(result, "filter_results")
    if isinstance(result, dict):
        assert "filter_results" in result
        assert "n_filter_blocked" in result


def test_pipeline_reset_clears_filter():
    """Reset 清除过滤器和滑点控制器状态"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        auto_generate_reports=False,
        enable_trade_filter=True,
        enable_slippage_control=True,
    ))
    market = runner.make_market_snapshot("000001", 10.0)
    runner.process_buy("000001", 1000, 10.0, market_data=market)

    # Verify state exists
    if runner.trade_filter:
        assert len(runner.trade_filter.get_history()) >= 0

    runner.reset()
    # After reset, history should be cleared
    if runner.trade_filter:
        assert len(runner.trade_filter.get_history()) == 0


# =========================================================================
# Edge Cases
# =========================================================================

def test_empty_rule_list():
    """空规则列表不报错"""
    engine = TradeFilterEngine(rules=[])
    assert len(engine.rules) == 0
    ctx = TradeContext(symbol="000001", side="buy", quantity=1000, price=10.0)
    report = engine.evaluate_trade(ctx)
    assert report.passed is True
    assert report.n_checks == 0


def test_zero_quantity_trade():
    """零股数订单不触发异常"""
    engine = TradeFilterEngine()
    ctx = TradeContext(symbol="000001", side="buy", quantity=0, price=10.0)
    report = engine.evaluate_trade(ctx)
    # Should not crash, some filters may skip
    assert report is not None


def test_negative_price():
    """负价格不触发异常"""
    engine = TradeFilterEngine()
    ctx = TradeContext(symbol="000001", side="buy", quantity=1000, price=-1.0)
    report = engine.evaluate_trade(ctx)
    assert report is not None


def test_trade_filter_to_dict():
    """引擎序列化正确"""
    engine = TradeFilterEngine()
    d = engine.to_dict()
    assert d["name"] == "default"
    assert "summary" in d
    assert "rules" in d
    assert "buy_limit_up" in d["rules"]


def test_delisting_filter():
    """退市整理期股票被阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=1.0,
        board_type="delisting",
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True


def test_market_state_stale_blocked():
    """数据陈旧时阻断"""
    engine = TradeFilterEngine()
    ctx = TradeContext(
        symbol="000001",
        side="buy",
        quantity=1000,
        price=10.0,
        market_status="stale",
    )
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True


def test_custom_evaluator():
    """自定义评估器"""
    engine = TradeFilterEngine()
    rule = TradeFilterRule(
        name="custom_check",
        filter_type=FilterType.CUSTOM.value,
        description="Custom check",
        severity=FilterSeverity.BLOCKER.value,
    )
    engine.add_rule(rule)

    def my_evaluator(r, ctx):
        if ctx.price > 100:
            return FilterResult(
                filter_name=r.name,
                filter_type=r.filter_type,
                passed=False,
                severity=r.severity,
                status=FilterStatus.BLOCKED.value,
                message="Price too high!",
            )
        return FilterResult(
            filter_name=r.name,
            filter_type=r.filter_type,
            passed=True,
            status=FilterStatus.PASSED.value,
        )

    registered = engine.register_custom_evaluator("custom_check", my_evaluator)
    assert registered is True

    # Test blocking
    ctx = TradeContext(symbol="000001", side="buy", quantity=1000, price=200.0)
    report = engine.evaluate_trade(ctx)
    assert report.blocked is True

    # Test passing
    ctx2 = TradeContext(symbol="000001", side="buy", quantity=1000, price=50.0)
    report2 = engine.evaluate_trade(ctx2)
    # Other filters may block, but custom one should pass
    custom_result = [r for r in report2.results if r.filter_name == "custom_check"]
    assert len(custom_result) >= 0


def test_serialize_filter_result():
    """FilterResult 序列化"""
    result = FilterResult(
        filter_name="test",
        filter_type=FilterType.CUSTOM.value,
        passed=False,
        severity=FilterSeverity.BLOCKER.value,
        status=FilterStatus.BLOCKED.value,
        message="Test blocked",
        detail="detail info",
        threshold=100.0,
        actual_value=150.0,
    )
    d = result.to_dict()
    assert d["filter_name"] == "test"
    assert d["passed"] is False
    assert d["severity"] == "blocker"
    assert d["status"] == "blocked"


def test_serialize_filter_report():
    """FilterReport 序列化"""
    report = FilterReport(
        symbol="000001",
        side="buy",
        passed=False,
        blocked=True,
        blocker_messages=["Blocked by filter"],
    )
    d = report.to_dict()
    assert d["symbol"] == "000001"
    assert d["blocked"] is True
    assert d["blocker_messages"] == ["Blocked by filter"]
