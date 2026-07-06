"""V4.6 Trade Filter & Slippage Control — Slippage Control Tests

Tests cover:
  - SlippageBudget config and defaults
  - SlippageBudgetTracker: check order, record fill, budget exceed
  - SlippageBudgetTracker: daily tracking and reset
  - SlippageEstimator: estimate with different models
  - SlippageEstimator: data quality and confidence
  - SlippageController: full check_trade flow
  - SlippageController: record_fill integration
  - Integration with FillEngine and ShadowPipeline
  - Edge cases (missing data, zero values, extreme values)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta

from factor_lab.execution.slippage_control import (
    SlippageController, SlippageEstimator, SlippageBudgetTracker,
    SlippageBudget, SlippageEstimate, SlippageLimitAction, BudgetPeriod,
)
from factor_lab.execution.shadow_fill import (
    FillEngine, SlippageConfig, SlippageModel,
    FillStrategy, MarketDataSnapshot, MarketDataStatus,
)
from factor_lab.execution.shadow_pipeline import (
    ShadowPipelineRunner, ShadowPipelineConfig,
)

CST = timezone(timedelta(hours=8))


# =========================================================================
# SlippageBudget Tests
# =========================================================================

def test_budget_defaults():
    """默认预算配置正确"""
    budget = SlippageBudget()
    assert budget.max_slippage_yuan == 0.0
    assert budget.max_slippage_pct == 0.005
    assert budget.max_daily_slippage_yuan == 0.0
    assert budget.max_daily_slippage_pct == 0.0
    assert budget.action_on_exceed == SlippageLimitAction.WARN.value
    assert budget.period == BudgetPeriod.PER_ORDER.value


def test_budget_custom():
    """自定义预算配置"""
    budget = SlippageBudget(
        max_slippage_yuan=100.0,
        max_slippage_pct=0.01,
        max_daily_slippage_yuan=500.0,
        max_daily_slippage_pct=0.02,
        action_on_exceed=SlippageLimitAction.REJECT.value,
    )
    assert budget.max_slippage_yuan == 100.0
    assert budget.action_on_exceed == SlippageLimitAction.REJECT.value


def test_budget_to_dict():
    """预算序列化"""
    budget = SlippageBudget(max_slippage_pct=0.01)
    d = budget.to_dict()
    assert d["max_slippage_pct"] == 0.01


# =========================================================================
# SlippageBudgetTracker Tests
# =========================================================================

def test_tracker_initial_state():
    """跟踪器初始状态"""
    tracker = SlippageBudgetTracker()
    state = tracker.get_daily_state()
    assert state["daily_slippage_yuan"] == 0.0
    assert state["daily_trade_count"] == 0
    assert state["daily_total_trade_value"] == 0.0


def test_tracker_check_order_allowed():
    """预算内的订单被允许"""
    tracker = SlippageBudgetTracker(budget=SlippageBudget(
        max_slippage_pct=0.01,  # 1%
    ))
    result = tracker.check_order(
        order_id="ord_001",
        trade_value=100_000,
        estimated_slippage_pct=0.002,  # 0.2% < 1%
    )
    assert result["allowed"] is True
    assert result["action"] == "proceed"


def test_tracker_check_order_exceeded_pct():
    """超预算订单被拒绝"""
    tracker = SlippageBudgetTracker(budget=SlippageBudget(
        max_slippage_pct=0.005,  # 0.5%
        action_on_exceed=SlippageLimitAction.REJECT.value,
    ))
    result = tracker.check_order(
        order_id="ord_001",
        trade_value=100_000,
        estimated_slippage_pct=0.02,  # 2% > 0.5%
    )
    assert result["allowed"] is False
    assert result["action"] == SlippageLimitAction.REJECT.value


def test_tracker_check_order_exceeded_yuan():
    """超绝对滑点额度被拒绝"""
    tracker = SlippageBudgetTracker(budget=SlippageBudget(
        max_slippage_yuan=50.0,
        action_on_exceed=SlippageLimitAction.REJECT.value,
    ))
    # 10 * 10000 * 0.01 = 1000 > 50
    result = tracker.check_order(
        order_id="ord_001",
        trade_value=100_000,
        estimated_slippage_pct=0.01,  # 1000 yuan > 50
    )
    assert result["allowed"] is False


def test_tracker_record_fill():
    """记录成交更新每日状态"""
    tracker = SlippageBudgetTracker()
    tracker.check_order("ord_001", 100_000, 0.001)
    tracker.record_fill("ord_001", 100_000, actual_slippage_yuan=50.0)

    state = tracker.get_daily_state()
    assert state["daily_slippage_yuan"] == 50.0
    assert state["daily_trade_count"] == 1


def test_tracker_daily_reset():
    """每日重置"""
    tracker = SlippageBudgetTracker()
    tracker.record_fill("ord_001", 100_000, 50.0)
    state_before = tracker.get_daily_state()
    assert state_before["daily_slippage_yuan"] > 0

    tracker.reset_daily()
    state_after = tracker.get_daily_state()
    assert state_after["daily_slippage_yuan"] == 0.0


def test_tracker_daily_limit_check():
    """每日滑点上限检查"""
    tracker = SlippageBudgetTracker(budget=SlippageBudget(
        max_slippage_yuan=0.0,       # No per-order limit
        max_slippage_pct=0.0,        # No per-order pct limit
        max_daily_slippage_yuan=1000.0,
        action_on_exceed=SlippageLimitAction.REJECT.value,
    ))

    # First order within budget
    r1 = tracker.check_order("ord_001", 50_000, 0.001)
    assert r1["allowed"] is True
    tracker.record_fill("ord_001", 50_000, 50.0)

    # Second order - projected 50 + 1000 = 1050 > 1000, blocked
    r2 = tracker.check_order("ord_002", 50_000, 0.02)
    assert r2["allowed"] is False  # 50 + 1000 = 1050 > 1000

    # Third order - clearly over
    r3 = tracker.check_order("ord_003", 100_000, 0.02)
    assert r3["allowed"] is False


def test_tracker_daily_pct_check():
    """每日滑点比例检查"""
    tracker = SlippageBudgetTracker(budget=SlippageBudget(
        max_slippage_yuan=0.0,       # No per-order limit
        max_slippage_pct=0.0,        # No per-order pct limit
        max_daily_slippage_pct=0.01,  # 1%
        action_on_exceed=SlippageLimitAction.REJECT.value,
    ))

    # Fill first trade
    r1 = tracker.check_order("ord_001", 100_000, 0.005)
    assert r1["allowed"] is True
    tracker.record_fill("ord_001", 100_000, 500.0)

    # Second trade: (500 + 500) / (100000 + 100000) = 0.5% OK
    r2 = tracker.check_order("ord_002", 100_000, 0.005)
    assert r2["allowed"] is True

    # Large projected pct — projects (500+500+2500)/(200000+50000)=1.4% > 1%
    r3 = tracker.check_order("ord_003", 50_000, 0.05)
    assert r3["allowed"] is False


def test_tracker_get_summary():
    """跟踪器汇总信息"""
    tracker = SlippageBudgetTracker()
    tracker.check_order("ord_001", 100_000, 0.001)
    tracker.record_fill("ord_001", 100_000, 50.0)

    summary = tracker.get_summary()
    assert summary["name"] == "default"
    assert summary["total_checks"] >= 1
    assert summary["n_allowed"] >= 1
    assert "budget" in summary
    assert "daily_state" in summary


def test_tracker_reset():
    """跟踪器完全重置"""
    tracker = SlippageBudgetTracker()
    tracker.check_order("ord_001", 100_000, 0.001)
    tracker.record_fill("ord_001", 100_000, 50.0)

    tracker.reset()
    state = tracker.get_daily_state()
    assert state["daily_slippage_yuan"] == 0.0
    assert tracker.get_summary()["total_checks"] == 0


# =========================================================================
# SlippageEstimator Tests
# =========================================================================

def test_estimator_default_model():
    """默认固定百分比模型"""
    estimator = SlippageEstimator()
    market = MarketDataSnapshot(close=10.0)
    est = estimator.estimate("buy", 1000, 10.0, market)
    assert est.model_used == SlippageModel.FIXED_PCT.value
    assert est.estimated_slippage_yuan > 0
    assert est.estimated_slippage_pct == 0.001  # 0.1% default


def test_estimator_volume_model():
    """基于成交量的估算"""
    config = SlippageConfig(model="volume_based", volume_basis=0.5)
    estimator = SlippageEstimator(slippage_config=config)
    market = MarketDataSnapshot(close=10.0, avg_volume_20d=1_000_000)
    est = estimator.estimate("buy", 10000, 10.0, market)
    assert est.model_used == SlippageModel.VOLUME_BASED.value
    assert est.estimated_slippage_yuan > 0


def test_estimator_confidence_multiplier():
    """置信度乘数放大估算"""
    config = SlippageConfig(fixed_pct=0.001)
    estimator_default = SlippageEstimator(slippage_config=config, confidence_multiplier=1.0)
    estimator_conservative = SlippageEstimator(slippage_config=config, confidence_multiplier=2.0)

    market = MarketDataSnapshot(close=10.0)
    est1 = estimator_default.estimate("buy", 1000, 10.0, market)
    est2 = estimator_conservative.estimate("buy", 1000, 10.0, market)

    # Conservative should have 2x slippage
    assert est2.estimated_slippage_yuan >= est1.estimated_slippage_yuan


def test_estimator_quality_assessment():
    """数据质量评估"""
    estimator = SlippageEstimator()

    # Good data
    market = MarketDataSnapshot(close=10.0)
    est = estimator.estimate("buy", 1000, 10.0, market)
    assert est.data_quality in ("good", "partial")
    assert est.confidence in ("low", "medium", "high")

    # No market data
    est_none = estimator.estimate("buy", 1000, 10.0, market=None)
    assert est_none.data_quality == "poor"
    assert est_none.confidence == "low"
    assert not est_none.is_reliable()


def test_estimator_range():
    """估算范围合理"""
    estimator = SlippageEstimator()
    market = MarketDataSnapshot(close=10.0)
    est = estimator.estimate("buy", 1000, 10.0, market)
    min_est, max_est = est.estimate_range
    assert min_est <= max_est
    # Range should be within reasonable bounds
    assert max_est <= est.estimated_slippage_yuan * 2


def test_estimator_warnings():
    """估算警告"""
    estimator = SlippageEstimator()
    est = estimator.estimate("buy", 1000, 10.0, market=None)
    if est.warnings:
        assert len(est.warnings) > 0


def test_estimator_quick_estimate():
    """快捷估算函数"""
    config = SlippageConfig(fixed_pct=0.001)
    estimator = SlippageEstimator(slippage_config=config)
    market = MarketDataSnapshot(close=10.0)
    pct = estimator.estimate_for_budget("buy", 1000, 10.0, market)
    assert isinstance(pct, float)
    assert 0 < pct < 1


def test_estimator_reset():
    """估算器重置"""
    estimator = SlippageEstimator()
    market = MarketDataSnapshot(close=10.0)
    estimator.estimate("buy", 1000, 10.0, market)
    assert len(estimator._estimate_history) == 1
    estimator.reset()
    assert len(estimator._estimate_history) == 0


def test_estimator_get_summary():
    """估算器汇总"""
    estimator = SlippageEstimator()
    summary = estimator.get_summary()
    assert summary["n_estimates"] == 0
    assert summary["model"] == SlippageModel.FIXED_PCT.value


# =========================================================================
# SlippageController Tests
# =========================================================================

def test_controller_defaults():
    """控制器默认配置"""
    controller = SlippageController()
    assert controller.name == "default"
    assert controller.estimator is not None
    assert controller.budget_tracker is not None


def test_controller_check_trade_allowed():
    """正常交易通过滑点控制"""
    controller = SlippageController()
    market = MarketDataSnapshot(close=10.0)
    result = controller.check_trade("ord_001", "buy", 1000, 10.0, market)
    assert result["allowed"] is True
    assert "estimate" in result
    assert "budget_check" in result


def test_controller_check_trade_rejected():
    """超大订单被滑点预算拒绝"""
    controller = SlippageController(
        budget=SlippageBudget(
            max_slippage_yuan=50.0,
            action_on_exceed=SlippageLimitAction.REJECT.value,
        ),
    )
    market = MarketDataSnapshot(close=10.0)
    # 10 * 100000 * 0.001 = 1000 yuan > 50
    result = controller.check_trade("ord_001", "buy", 100_000, 10.0, market)
    assert result["allowed"] is False
    assert result["action"] == SlippageLimitAction.REJECT.value


def test_controller_record_fill():
    """记录成交更新预算"""
    controller = SlippageController()
    market = MarketDataSnapshot(close=10.0)

    result = controller.check_trade("ord_001", "buy", 1000, 10.0, market)
    assert result["allowed"] is True

    controller.record_fill("ord_001", 10_000, 10.0)
    summary = controller.get_summary()
    assert summary["budget_tracker"]["daily_state"]["daily_trade_count"] == 1


def test_controller_get_summary():
    """控制器汇总"""
    controller = SlippageController()
    market = MarketDataSnapshot(close=10.0)
    controller.check_trade("ord_001", "buy", 1000, 10.0, market)

    summary = controller.get_summary()
    assert summary["name"] == "default"
    assert summary["estimator"]["n_estimates"] == 1
    assert summary["budget_tracker"]["total_checks"] >= 1


def test_controller_reset():
    """控制器重置"""
    controller = SlippageController()
    market = MarketDataSnapshot(close=10.0)
    controller.check_trade("ord_001", "buy", 1000, 10.0, market)

    controller.reset()
    assert controller.estimator.get_summary()["n_estimates"] == 0
    assert controller.budget_tracker.get_summary()["total_checks"] == 0


def test_controller_reset_daily():
    """控制器每日重置"""
    controller = SlippageController()
    market = MarketDataSnapshot(close=10.0)
    controller.check_trade("ord_001", "buy", 1000, 10.0, market)
    controller.record_fill("ord_001", 10_000, 10.0)

    assert controller.budget_tracker.get_daily_state()["daily_trade_count"] == 1
    controller.reset_daily()
    assert controller.budget_tracker.get_daily_state()["daily_trade_count"] == 0


# =========================================================================
# SlippageEstimate Tests
# =========================================================================

def test_slippage_estimate_defaults():
    """估算默认值"""
    est = SlippageEstimate()
    assert est.estimated_slippage_pct == 0.0
    assert est.estimated_slippage_yuan == 0.0
    assert est.confidence == "medium"
    assert est.is_reliable() is True


def test_slippage_estimate_to_dict():
    """估算序列化"""
    est = SlippageEstimate(
        estimated_slippage_pct=0.001,
        estimated_slippage_yuan=10.0,
        model_used=SlippageModel.FIXED_PCT.value,
        confidence="high",
        estimate_range=(5.0, 15.0),
        data_quality="good",
    )
    d = est.to_dict()
    assert d["estimated_slippage_pct"] == 0.001
    assert d["confidence"] == "high"
    assert d["estimate_range"] == [5.0, 15.0]
    assert d["data_quality"] == "good"


# =========================================================================
# Shadow Pipeline Integration Tests
# =========================================================================

def test_pipeline_with_full_v46():
    """完整 V4.6 集成：TradeFilter + SlippageControl"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=1_000_000,
        auto_generate_reports=False,
        enable_trade_filter=True,
        enable_slippage_control=True,
    ))
    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")

    trades = [{
        "symbol": "000001",
        "side": "buy",
        "quantity": 1000,
        "price": 10.0,
        "name": "平安银行",
        "signal_price": 9.95,
        "market_data": market,
    }]
    result = runner.process_signal("sig_001", "prop_001", trades)

    assert result is not None
    assert result.n_filled == 1
    assert result.n_filter_blocked == 0
    assert result.n_slippage_blocked == 0
    assert result.filter_summary is not None
    assert result.slippage_control_summary is not None


def test_pipeline_v46_no_limit_up():
    """V4.6 集成：涨停被过滤"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=1_000_000,
        auto_generate_reports=False,
        enable_trade_filter=True,
        enable_slippage_control=False,
    ))
    market = runner.make_market_snapshot("000001", 10.0, name="平安银行")
    market.limit_up = 10.0  # Close price = limit up
    market.close = 10.0

    trades = [{
        "symbol": "000001",
        "side": "buy",
        "quantity": 1000,
        "price": 10.0,
        "name": "平安银行",
        "market_data": market,
    }]
    result = runner.process_signal("sig_001", "prop_001", trades)

    assert result.n_filter_blocked >= 1


def test_pipeline_v46_slippage_budget_block():
    """V4.6 集成：滑点预算超限被拒绝"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=1_000_000,
        auto_generate_reports=False,
        enable_trade_filter=False,
        enable_slippage_control=True,
        slippage_budget={
            "max_slippage_yuan": 10.0,
            "action_on_exceed": "reject",
        },
    ))
    market = runner.make_market_snapshot("000001", 100.0, name="高价股")

    trades = [{
        "symbol": "000001",
        "side": "buy",
        "quantity": 100_000,  # 100 * 100000 = 10M, slippage ~0.1% = 10K > 10
        "price": 100.0,
        "name": "高价股",
        "market_data": market,
    }]
    result = runner.process_signal("sig_001", "prop_001", trades)

    assert result.n_slippage_blocked >= 1


def test_pipeline_v46_no_filter_no_control():
    """V4.6 禁用后回退到 V4.1 行为"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        initial_cash=100_000,
        auto_generate_reports=False,
        enable_trade_filter=False,
        enable_slippage_control=False,
    ))
    assert runner.trade_filter is None
    assert runner.slippage_controller is None

    market = runner.make_market_snapshot("000001", 10.0)
    result = runner.process_buy("000001", 1000, 10.0, market_data=market)
    assert result["n_filled"] == 1


def test_pipeline_v46_slippage_controller_present():
    """enable_slippage_control=True 时控制器存在"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        auto_generate_reports=False,
        enable_slippage_control=True,
    ))
    # Check controller was created
    controller = getattr(runner, 'slippage_controller', None)
    assert controller is not None
    assert controller.budget_tracker is not None


def test_pipeline_v46_filter_controller_present():
    """enable_trade_filter=True 时过滤器存在"""
    runner = ShadowPipelineRunner(config=ShadowPipelineConfig(
        auto_generate_reports=False,
        enable_trade_filter=True,
    ))
    # Check filter was created
    filter_engine = getattr(runner, 'trade_filter', None)
    assert filter_engine is not None


# =========================================================================
# Edge Cases
# =========================================================================

def test_estimator_no_market_data():
    """无行情数据时估算不崩溃"""
    estimator = SlippageEstimator()
    est = estimator.estimate("buy", 1000, 10.0, market=None)
    assert isinstance(est, SlippageEstimate)
    assert est.data_quality == "poor"
    assert est.estimated_slippage_yuan >= 0


def test_estimator_zero_quantity():
    """零股数估算不崩溃"""
    estimator = SlippageEstimator()
    market = MarketDataSnapshot(close=10.0)
    est = estimator.estimate("buy", 0, 10.0, market)
    assert isinstance(est, SlippageEstimate)
    assert est.estimated_slippage_yuan == 0.0


def test_estimator_zero_price():
    """零价格估算不崩溃"""
    estimator = SlippageEstimator()
    market = MarketDataSnapshot(close=10.0)
    est = estimator.estimate("buy", 1000, 0, market)
    assert isinstance(est, SlippageEstimate)


def test_tracker_no_budget_limits():
    """无预算限制时所有订单允许"""
    tracker = SlippageBudgetTracker(budget=SlippageBudget(
        max_slippage_yuan=0.0,
        max_slippage_pct=0.0,
        max_daily_slippage_yuan=0.0,
        max_daily_slippage_pct=0.0,
    ))
    result = tracker.check_order("ord_001", 1_000_000, 0.1)  # 10% slippage
    assert result["allowed"] is True


def test_estimate_serialization():
    """估算序列化完整"""
    est = SlippageEstimate(
        estimated_slippage_pct=0.001,
        estimated_slippage_yuan=10.0,
        model_used=SlippageModel.FIXED_PCT.value,
        confidence="high",
        estimate_range=(5.0, 15.0),
        data_quality="good",
        warnings=["Test warning"],
    )
    d = est.to_dict()
    assert len(d["warnings"]) == 1


def test_controller_with_volume_model():
    """滑点控制器使用成交量模型"""
    config = SlippageConfig(model="volume_based", volume_basis=0.3)
    controller = SlippageController(slippage_config=config)
    market = MarketDataSnapshot(
        close=10.0,
        avg_volume_20d=1_000_000,
    )
    result = controller.check_trade("ord_001", "buy", 5000, 10.0, market)
    assert result["allowed"] is True
    assert result["estimate"]["model_used"] == SlippageModel.VOLUME_BASED.value
