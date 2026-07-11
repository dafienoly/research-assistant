from __future__ import annotations

from factor_lab.vnext.contracts import QualityStatus, ResearchSignal, Tradability
from factor_lab.vnext.target_weights import TargetWeightPipeline, TopNTargetWeightAdapter


def _signal(symbol: str, rank: int, quality: QualityStatus = QualityStatus.OK) -> ResearchSignal:
    return ResearchSignal(
        signal_run_id=f"signal-{symbol}",
        as_of="2026-07-10",
        instrument_id=symbol,
        factor_score=1 / rank,
        rank=rank,
        confidence=0.8,
        regime_applicability=0.8,
        semi_state_applicability=0.7,
        evidence_bundle_id=f"evidence-{symbol}",
        quality_status=quality,
        source_strategy="test-factor",
    )


def test_target_pipeline_zeroes_restricted_and_watch_only_and_marks_etf_substitution():
    book = TargetWeightPipeline().build(
        raw_weights={"688012.SH": 0.4, "000001.SZ": 0.3, "600000.SH": 0.3},
        current_weights=None,
        tradability={
            "688012.SH": Tradability.RESTRICTED,
            "000001.SZ": Tradability.TRADABLE,
            "600000.SH": Tradability.WATCH_ONLY,
        },
        substitutions={"688012.SH": "512480.SH"},
        account_id="account",
        as_of="2026-07-10",
        data_snapshot_id="snapshot",
        universe_snapshot_id="universe",
        source_strategy="factor",
        strategy_version="v1",
        model_version=None,
        regime_state="RANGE_BOUND",
        semi_mainline_state="SEMI_FAILURE",
        confidence=0.8,
        max_invested_weight=0.7,
        quality_status=QualityStatus.BACKTEST_ONLY,
    )
    lines = {line.instrument_id: line for line in book.weights}
    assert lines["688012.SH"].risk_adjusted_target_weight == 0
    assert lines["600000.SH"].risk_adjusted_target_weight == 0
    assert lines["512480.SH"].tradability == Tradability.ETF_SUBSTITUTION
    assert lines["512480.SH"].substitution_of == "restricted_basket:688012.SH"
    assert lines["512480.SH"].risk_adjusted_target_weight == 0.4
    assert abs(book.cash_weight - 0.3) < 1e-9
    assert book.constraints["current_holdings_snapshot_available"] is False
    assert book.constraints["order_drafts_generated"] is False


def test_legacy_topn_adapter_preserves_selected_candidate_set_and_never_creates_orders():
    signals = [_signal("000001.SZ", 1), _signal("000002.SZ", 2), _signal("000003.SZ", 3)]
    book = TopNTargetWeightAdapter().adapt(
        signals,
        top_n=2,
        tradability={symbol.instrument_id: Tradability.TRADABLE for symbol in signals},
        substitutions=None,
        account_id="account",
        data_snapshot_id="snapshot",
        regime_state="BULL",
        semi_mainline_state="SEMI_MAINLINE_CONFIRM",
    )
    assert book.constraints["selected_instruments"] == ["000001.SZ", "000002.SZ"]
    assert {symbol for symbol, weight in book.raw_weights.items() if weight > 0} == {
        "000001.SZ",
        "000002.SZ",
    }
    assert book.constraints["order_drafts_generated"] is False


def test_stale_and_missing_signals_cannot_enter_topn_weights():
    signals = [
        _signal("000001.SZ", 1, QualityStatus.STALE),
        _signal("000002.SZ", 2, QualityStatus.MISSING),
        _signal("000003.SZ", 3, QualityStatus.BACKTEST_ONLY),
    ]
    book = TopNTargetWeightAdapter().adapt(
        signals,
        top_n=3,
        tradability={"000003.SZ": Tradability.TRADABLE},
        substitutions=None,
        account_id="account",
        data_snapshot_id="snapshot",
        regime_state="RANGE_BOUND",
        semi_mainline_state="SEMI_DORMANT",
    )
    assert set(book.raw_weights) == {"000003.SZ"}
    assert book.quality_status == QualityStatus.BACKTEST_ONLY
