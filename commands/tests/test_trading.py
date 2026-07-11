from factor_lab.vnext.contracts import TradingMode
from factor_lab.vnext.execution import AuditJournal, GovernedExecutionEngine, PaperBroker
from factor_lab.vnext.trading import PaperShadowLoop, summarize_execution_comparison


def test_trading_loop_reports_no_draft_without_orders(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    approval_key = "-".join(("test", "signing", "key"))
    loop = PaperShadowLoop(
        GovernedExecutionEngine(TradingMode.PAPER, journal),
        PaperBroker(journal),
        lambda: [],
        signing_secret=approval_key,
    )
    result = loop.run_once()
    assert result["orders_seen"] == 0
    assert result["real_broker_called"] is False


def test_comparison_is_missing_instead_of_fabricating_pnl():
    comparison = summarize_execution_comparison([{"results": [{"status": "BLOCKED", "reason": "stale_data"}]}])
    assert comparison["status"] == "MISSING"
    assert comparison["paper_vs_shadow_gap"] is None
    assert comparison["backtest_vs_paper_gap"] is None
    assert comparison["blocked_reasons"] == ["stale_data"]
