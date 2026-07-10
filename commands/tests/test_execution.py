from factor_lab.vnext.contracts import DataStatus
from factor_lab.vnext.execution import AuditJournal, MiniQMTLiveBroker, OrderDraft, SafetyContext


def test_miniqmt_live_submit_is_unconditionally_blocked(tmp_path):
    order = OrderDraft("a", "600000.SH", "BUY", 100, 10, "test", "test", "RANGE_BOUND", "SEMI_DORMANT", None, {}, [], "OK", "OK")
    context = SafetyContext(
        data_status=DataStatus.OK.value,
        data_fresh=True,
        account_permission=True,
        funds_available=True,
        positions_synced=True,
        within_trading_session=True,
        price_limit_clear=True,
        suspension_clear=True,
        st_clear=True,
        liquidity_clear=True,
        stock_weight_clear=True,
        theme_exposure_clear=True,
        portfolio_drawdown_clear=True,
        daily_loss_clear=True,
        kill_switch_triggered=False,
        telegram_approved=True,
        approval_id="a",
    )
    broker = MiniQMTLiveBroker(object(), AuditJournal(tmp_path / "audit.jsonl"))
    broker.no_live_trade = False
    broker.live_enabled = True
    result = broker.submit(order, context)
    assert result["status"] == "BLOCKED"
    assert result["real_broker_called"] is False
