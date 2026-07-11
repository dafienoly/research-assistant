from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from factor_lab.vnext.backtest import PolicyHypothesisBacktester, RobustnessValidator
from factor_lab.vnext.contracts import ApprovedOrderEnvelope, DataStatus, MainlineState, TradingMode, Tradability
from factor_lab.vnext.data_quality import AssetRecord, DataQualityGate, MultiAssetUniverseRegistry
from factor_lab.vnext.datasets import MLRankingDatasetBuilder
from factor_lab.vnext.execution import (
    AuditJournal,
    GovernedExecutionEngine,
    MiniQMTLiveBroker,
    OrderDraft,
    PaperBroker,
    SafetyContext,
    ShadowBroker,
    TelegramApprovalGate,
    TradingModeStateMachine,
)
from factor_lab.vnext.market import (
    compute_breadth_divergence,
    compute_index_box,
    compute_policy_support_proxy,
)
from factor_lab.vnext.ml import CrossSectionalRanker, MLFactorSelector
from factor_lab.vnext.portfolio import PortfolioRiskAnalyzer
from factor_lab.vnext.regime import RegimeRouter
from factor_lab.vnext.report import VNextReportRenderer
from factor_lab.vnext.review import AntifragileReviewEngine
from factor_lab.vnext.semiconductor import SemiconductorMainlineStateMachine
from factor_lab.vnext.service import VNextService


def safety_context(**overrides):
    values = {
        "data_status": DataStatus.OK.value,
        "data_fresh": True,
        "account_permission": True,
        "funds_available": True,
        "positions_synced": True,
        "within_trading_session": True,
        "price_limit_clear": True,
        "suspension_clear": True,
        "st_clear": True,
        "liquidity_clear": True,
        "stock_weight_clear": True,
        "theme_exposure_clear": True,
        "portfolio_drawdown_clear": True,
        "daily_loss_clear": True,
        "kill_switch_triggered": False,
        "telegram_approved": True,
        "approval_id": "appr_test",
    }
    values.update(overrides)
    return SafetyContext(**values)


def order(**overrides):
    values = {
        "approval_id": "appr_test",
        "symbol": "600183.SH",
        "side": "BUY",
        "quantity": 100,
        "limit_price": 10.5,
        "strategy_source": "vnext-test",
        "rationale": "evidence based test draft",
        "regime": "TECH_ATTACK",
        "semiconductor_state": "SEMI_MAINLINE_CONFIRM",
        "model_score": 0.12,
        "portfolio_impact": {"marginal_sharpe": 0.05},
        "risk_summary": ["test only"],
        "data_freshness": "OK",
        "account_permission": "OK",
    }
    values.update(overrides)
    return OrderDraft(**values)


def test_missing_data_is_fail_visible(tmp_path):
    observation = DataQualityGate().inspect_file("missing", tmp_path / "absent.csv", required_fields=["close"])
    assert observation.status == DataStatus.MISSING
    assert observation.missing_fields == ["close"]


def test_stale_data_is_marked(tmp_path):
    path = tmp_path / "real.csv"
    path.write_text("date,close\n2026-01-01,1\n", encoding="utf-8")
    observation = DataQualityGate(max_age_days=1).inspect_file(
        "daily",
        path,
        required_fields=["date", "close"],
        as_of=pd.Timestamp("2026-07-10").date(),
        updated_at="2026-01-01T00:00:00+08:00",
    )
    assert observation.status == DataStatus.STALE


def test_watch_only_and_restricted_never_enter_execution_candidates():
    registry = MultiAssetUniverseRegistry(
        [
            AssetRecord("600183.SH", "生益科技", "A_SHARE", "stock", "attack", Tradability.TRADABLE, "MAINBOARD"),
            AssetRecord("688012.SH", "中微公司", "A_SHARE", "stock", "attack", Tradability.RESTRICTED, "STAR"),
            AssetRecord("SOX", "费半", "US", "index", "proxy", Tradability.WATCH_ONLY),
            AssetRecord("512480.SH", "半导体ETF", "A_SHARE", "etf", "substitute", Tradability.ETF_SUBSTITUTION, "ETF"),
        ]
    )
    symbols = {item["symbol"] for item in registry.execution_candidates()}
    assert symbols == {"600183.SH", "512480.SH"}
    assert registry.validate_account_rules() == []


def test_registry_detects_restricted_board_violation():
    registry = MultiAssetUniverseRegistry(
        [AssetRecord("300001.SZ", "受限", "A_SHARE", "stock", "attack", Tradability.TRADABLE, "CHINEXT")]
    )
    assert "restricted board" in registry.validate_account_rules()[0]


def test_index_box_policy_and_breadth_scores_are_computable():
    history = np.linspace(3900, 4100, 140)
    box = compute_index_box(history, current=3940, as_of="2026-07-10", source="tushare")
    snapshot = {
        "advancing": 900,
        "declining": 4000,
        "intraday_reversal_strength": 0.8,
        "semiconductor_relative_strength": 0.72,
        "technology_relative_strength": 0.66,
        "etf_abnormal_volume": 0.75,
        "large_cap_tech_support": 0.7,
        "data_sources": ["real-test-fixture"],
    }
    policy = compute_policy_support_proxy(snapshot, box, as_of="2026-07-10")
    payload = policy["payload"]
    assert 0 <= payload["index_box_position"] <= 1
    assert 0 <= payload["policy_support_proxy_score"] <= 1
    assert 0 <= payload["breadth_divergence_score"] <= 1
    assert box["payload"]["dynamic_box"]["position"] is not None


def test_breadth_missing_does_not_become_fake_zero():
    score, _, missing = compute_breadth_divergence(
        advancing=None,
        declining=None,
        index_reversal_strength=None,
        semiconductor_relative_strength=None,
        large_cap_tech_support=None,
    )
    assert score is None
    assert "market_breadth" in missing


def test_semiconductor_state_machine_transitions():
    machine = SemiconductorMainlineStateMachine()
    result = machine.evaluate(
        {
            "relative_strength": 0.86,
            "etf_volume_strength": 0.8,
            "anchor_support": 0.75,
            "subsector_breadth": 0.76,
            "policy_support": 0.4,
            "distribution_risk": 0.2,
            "drawdown_pressure": 0.1,
            "liquidity_support": 0.7,
        },
        as_of="2026-07-10",
        previous_state=MainlineState.SEMI_MAINLINE_CONFIRM,
    )
    assert result["payload"]["state"] == MainlineState.SEMI_ACCELERATION.value
    assert result["payload"]["state_changed"] is True
    assert result["payload"]["recommended_action_bias"] == "hold_core"


def test_semiconductor_missing_evidence_downgrades():
    result = SemiconductorMainlineStateMachine().evaluate({}, as_of="2026-07-10")
    assert result["status"] == DataStatus.MISSING.value
    assert result["payload"]["state"] == MainlineState.SEMI_DORMANT.value


def test_regime_router_confidence_degrades_with_missing_inputs():
    complete = RegimeRouter().route(
        {
            "market_trend": 0.7,
            "breadth": 0.65,
            "liquidity": 0.7,
            "technology_strength": 0.8,
            "semiconductor_strength": 0.8,
            "defensive_strength": 0.2,
            "policy_support": 0.5,
            "overseas_tech_lead": 0.5,
            "volatility_stress": 0.2,
        },
        as_of="2026-07-10",
    )
    missing = RegimeRouter().route({"technology_strength": 0.8}, as_of="2026-07-10")
    assert complete["payload"]["regime_name"] == "TECH_ATTACK"
    assert missing["payload"]["regime_name"] == "CASH_OR_WAIT"
    assert missing["confidence"] < complete["confidence"]
    assert missing["payload"]["allow_new_buy"] is False


def test_false_diversification_and_marginal_sharpe():
    rng = np.random.default_rng(7)
    base = rng.normal(0.0005, 0.02, 150)
    returns = pd.DataFrame(
        {
            "equipment": base,
            "pcb": base * 0.98 + rng.normal(0, 0.001, 150),
            "optical": base * 1.02 + rng.normal(0, 0.001, 150),
            "gold": rng.normal(0.0002, 0.006, 150),
        }
    )
    weights = {name: 0.25 for name in returns.columns}
    exposures = {
        "equipment": {"technology_beta": 1, "semiconductor_beta": 1},
        "pcb": {"technology_beta": 1, "semiconductor_beta": 0.8},
        "optical": {"technology_beta": 1, "semiconductor_beta": 0.7},
        "gold": {"technology_beta": 0, "semiconductor_beta": 0},
    }
    result = PortfolioRiskAnalyzer().analyze(returns, weights, as_of="2026-07-10", exposures=exposures)
    payload = result["payload"]
    assert payload["false_diversification_warning"] is True
    assert set(payload["marginal_sharpe_contribution"]) == set(weights)
    impact = PortfolioRiskAnalyzer().candidate_impact(returns, {"equipment": 0.5, "pcb": 0.5}, "gold")
    assert impact["status"] == DataStatus.OK.value
    assert impact["marginal_sharpe"] is not None


def test_ml_factor_selector_and_ranker_never_emit_buy_sell():
    rng = np.random.default_rng(9)
    n = 160
    features = pd.DataFrame({"quality": rng.normal(size=n), "momentum": rng.normal(size=n), "duplicate": rng.normal(size=n)})
    target = features["quality"] * 0.04 + features["momentum"] * 0.02 + rng.normal(0, 0.01, n)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    selector = MLFactorSelector().select(features, target, min_abs_rank_ic=0.01)
    assert "quality" in selector["selected_factors"]
    ranker = CrossSectionalRanker("ridge")
    card = ranker.fit(features, target, pd.Series(dates))
    scores = ranker.score(features.tail(5), symbols=[f"S{i}" for i in range(5)])
    assert card["direct_buy_sell_output"] is False
    assert all("candidate_score" in item and "rank" in item for item in scores)
    assert all("buy" not in item and "sell" not in item for item in scores)


def test_paper_and_shadow_brokers_never_call_real_broker(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    paper = PaperBroker(journal).submit(order(), safety_context())
    shadow = ShadowBroker(journal).submit(order(), safety_context())
    assert paper["real_broker_called"] is False
    assert shadow["real_broker_called"] is False
    assert paper["status"] == "PAPER_FILLED"
    assert shadow["status"] == "SHADOW_RECORDED"


def test_kill_switch_blocks_every_execution_route(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    engine = GovernedExecutionEngine(TradingMode.PAPER, journal)
    approval_key = "-".join(("test", "signing", "key"))
    draft = order()
    envelope = ApprovedOrderEnvelope.sign(
        order_draft=draft,
        approved_by="tester",
        allowed_mode=TradingMode.PAPER,
        risk_snapshot_id="risk_test",
        secret=approval_key,
    )
    result = engine.submit(
        PaperBroker(journal),
        envelope,
        safety_context(kill_switch_triggered=True),
        signing_secret=approval_key,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "kill_switch"
    assert result["real_broker_called"] is False


def test_miniqmt_live_is_disabled_and_no_live_trade_cannot_be_bypassed(tmp_path):
    class ExplodingClient:
        def place_order(self, *args, **kwargs):
            raise AssertionError("real broker must never be called")

    broker = MiniQMTLiveBroker(ExplodingClient(), AuditJournal(tmp_path / "audit.jsonl"))
    assert broker.no_live_trade is True
    assert broker.live_enabled is False
    broker.no_live_trade = False
    broker.live_enabled = True
    result = broker.submit(order(), safety_context())
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "no_live_trade_safety_invariant"
    assert result["real_broker_called"] is False


def test_telegram_approval_missing_cannot_pass_and_modify_requires_reapproval(tmp_path):
    gate = TelegramApprovalGate(tmp_path)
    assert gate.is_approved("unknown") is False
    record = gate.create(order(), kill_switch=False, miniqmt_mode="LIVE_DRY_RUN")
    modified = gate.decide(record["approval_id"], "MODIFY", approver="tester", reason="reduce size", modifications={"quantity": 100})
    assert modified["requires_reapproval"] is True
    assert gate.is_approved(record["approval_id"]) is False


def test_telegram_cannot_approve_watch_only_or_kill_switch(tmp_path):
    gate = TelegramApprovalGate(tmp_path)
    watch = gate.create(order(approval_id="watch", watch_only=True), kill_switch=False, miniqmt_mode="READ_ONLY")
    with pytest.raises(PermissionError):
        gate.decide(watch["approval_id"], "APPROVE", approver="tester", reason="bad")
    killed = gate.create(order(approval_id="killed"), kill_switch=True, miniqmt_mode="KILL_SWITCH_TRIGGERED")
    with pytest.raises(PermissionError):
        gate.decide(killed["approval_id"], "APPROVE", approver="tester", reason="bad")


def test_sell_draft_requires_real_positions(tmp_path):
    engine = GovernedExecutionEngine(TradingMode.PAPER, AuditJournal(tmp_path / "audit.jsonl"))
    with pytest.raises(PermissionError):
        engine.create_order_draft(
            symbol="600183.SH", side="SELL", quantity=100, limit_price=10, strategy_source="test",
            rationale="test", regime="RANGE_BOUND", semiconductor_state="SEMI_DORMANT", model_score=None,
            portfolio_impact={}, risk_summary=[], data_freshness="OK", account_permission="OK", positions=None,
        )


def test_trading_mode_state_machine_requires_prerequisites_and_never_reaches_live():
    state = TradingModeStateMachine()
    assert state.transition(TradingMode.PAPER) == TradingMode.PAPER
    with pytest.raises(PermissionError):
        state.transition(TradingMode.SHADOW)
    assert state.transition(TradingMode.SHADOW, prerequisites={"paper_stable": True}) == TradingMode.SHADOW
    with pytest.raises(PermissionError):
        state.transition(TradingMode.LIVE_ENABLED)


def test_antifragile_review_emits_structured_decision_and_sample(tmp_path):
    event = {name: 0.75 for name in AntifragileReviewEngine.DIMENSIONS}
    event.update({"return": 0.03, "benchmark_return": 0.01, "semiconductor_beta_return": 0.015, "risk_control_effectiveness": 0.8})
    review = AntifragileReviewEngine().review(event, as_of="2026-07-10")
    assert review["decision"] in {"KEEP", "TUNE", "DOWNGRADE", "RETIRE", "ESCALATE", "WATCH"}
    assert review["structured_training_sample"]["outcome_return"] == 0.03
    path = tmp_path / "samples.jsonl"
    AntifragileReviewEngine.append_training_sample(path, review)
    assert json.loads(path.read_text(encoding="utf-8"))["label"] == review["decision"]


def test_policy_backtest_and_robustness_cover_costs_and_regimes():
    rng = np.random.default_rng(12)
    n = 180
    frame = pd.DataFrame(
        {
            "support_signal": np.arange(n) % 10 == 0,
            "semi": rng.normal(0.0008, 0.02, n),
            "csi300": rng.normal(0.0002, 0.012, n),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )
    hypotheses = PolicyHypothesisBacktester().evaluate(
        frame,
        signal_columns=["support_signal"],
        target_columns=["semi"],
        benchmark_columns=["csi300"],
        horizons=[1, 3, 5],
    )
    assert len(hypotheses["hypothesis_results"]) == 3
    regimes = pd.Series(np.resize(["BULL", "BEAR", "RANGE_BOUND", "LIQUIDITY_SHOCK"], n), index=frame.index)
    robust = RobustnessValidator().evaluate(
        frame["semi"],
        {"csi300": frame["csi300"]},
        turnover=0.2,
        regimes=regimes,
        cost_bps=[5, 10],
        slippage_bps=[3, 6],
        impact_bps=[0, 5],
    )
    assert len(robust["cost_slippage_impact_sensitivity"]) == 8
    assert robust["missing_regimes"] == []


def test_policy_backtest_keeps_available_benchmarks_and_marks_missing_ones():
    frame = pd.DataFrame(
        {
            "signal": [True, False] * 40,
            "semi": np.linspace(-0.01, 0.01, 80),
            "csi300": np.zeros(80),
        },
        index=pd.date_range("2025-01-01", periods=80, freq="B"),
    )
    result = PolicyHypothesisBacktester().evaluate(
        frame,
        signal_columns=["signal"],
        target_columns=["semi"],
        benchmark_columns=["csi300", "old_topn"],
    )
    assert result["status"] == DataStatus.PARTIAL.value
    assert result["missing_evidence"] == ["old_topn"]
    assert result["hypothesis_results"]


def test_ml_dataset_builder_uses_real_rows_and_removes_forward_label_from_scoring(tmp_path):
    daily = tmp_path / "data" / "normalized" / "market"
    daily.mkdir(parents=True)
    dates = pd.date_range("2025-01-01", periods=80, freq="B")
    for symbol, scale in (("600001.SH", 1.0), ("600002.SH", 1.1)):
        frame = pd.DataFrame(
            {
                "ts_code": symbol,
                "trade_date": dates.strftime("%Y%m%d"),
                "close": np.linspace(10, 20, len(dates)) * scale,
                "vol": np.linspace(1000, 2000, len(dates)),
                "amount": np.linspace(10000, 30000, len(dates)),
            }
        )
        frame.to_csv(daily / f"{symbol}.csv", index=False)
    training = tmp_path / "training.csv"
    scoring = tmp_path / "scoring.csv"
    result = MLRankingDatasetBuilder(tmp_path).build("2025-01-01", "2025-05-01", training, scoring)
    assert result["status"] == DataStatus.OK.value
    assert result["training_rows"] > 0
    assert "forward_return" in pd.read_csv(training).columns
    assert "forward_return" not in pd.read_csv(scoring).columns
    assert (training.with_suffix(".csv.metadata.json")).exists()


def test_report_contains_evidence_missing_confidence_and_safety():
    component = {
        "status": "PARTIAL",
        "confidence": 0.5,
        "evidence": ["real evidence"],
        "missing_evidence": ["missing input"],
        "payload": {},
    }
    text = VNextReportRenderer().render(
        {
            "as_of": "2026-07-10",
            "policy_put": component,
            "semi_mainline": component,
            "regime": component,
            "portfolio_risk": component,
            "candidates": component,
            "data_health": component,
            "execution_status": {"trading_mode": "READ_ONLY", "no_live_trade": True},
        }
    )
    assert "Evidence" not in text or "支持证据" in text
    assert "缺失证据" in text
    assert "置信度" in text
    assert "不会触发真实委托" in text
    assert "20 项必答检查" in text


def test_vnext_api_surface_and_approval_action_never_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_VNEXT_OUTPUT_DIR", str(tmp_path / "artifacts"))
    service = VNextService(artifact_root=tmp_path / "artifacts")
    service.store.write("status", "2026-07-10", {"status": "PARTIAL", "as_of": "2026-07-10", "no_live_trade": True})
    approval = service.approvals.create(order(approval_id="api_test"), kill_switch=False, miniqmt_mode="LIVE_DRY_RUN")

    from factor_lab.api_server.main import app

    token = os.environ.get("HERMES_UI_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with TestClient(app, headers=headers) as client:
        status_response = client.get("/api/vnext/status?date=2026-07-10")
        assert status_response.status_code == 200
        assert status_response.json()["data"]["no_live_trade"] is True
        approve_response = client.post(
            f"/api/vnext/approvals/{approval['approval_id']}/approve",
            json={"approver": "tester", "reason": "state-only approval"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["data"]["execution_triggered"] is False
        assert client.get("/api/vnext/regime?date=2026-07-10").json()["data"]["status"] == DataStatus.MISSING.value


def test_daily_service_writes_json_csv_markdown_and_never_fakes_optional_components(tmp_path):
    dates = pd.date_range("2026-01-01", periods=130, freq="B")
    style_returns = {
        "semiconductor": [{"date": value.date().isoformat(), "return": 0.001} for value in dates],
        "gold": [{"date": value.date().isoformat(), "return": 0.0002} for value in dates],
        "bond": [{"date": value.date().isoformat(), "return": 0.0001} for value in dates],
    }
    snapshot = {
        "status": "OK",
        "as_of": "2026-07-10",
        "data_sources": ["test fixture only"],
        "source_statuses": [],
        "index_history": np.linspace(3900, 4050, 140).tolist(),
        "current_index": 3950,
        "advancing": 1000,
        "declining": 4000,
        "intraday_reversal_strength": 0.8,
        "semiconductor_relative_strength": 0.7,
        "technology_relative_strength": 0.65,
        "etf_abnormal_volume": 0.7,
        "large_cap_tech_support": 0.65,
        "semi_inputs": {
            "relative_strength": 0.7,
            "etf_volume_strength": 0.7,
            "anchor_support": 0.65,
            "subsector_breadth": 0.6,
            "distribution_risk": 0.2,
            "drawdown_pressure": 0.2,
            "liquidity_support": 0.7,
        },
        "regime_inputs": {
            "market_trend": 0.6,
            "breadth": 0.2,
            "liquidity": 0.7,
            "technology_strength": 0.7,
            "semiconductor_strength": 0.7,
            "defensive_strength": 0.2,
            "overseas_tech_lead": 0.5,
            "volatility_stress": 0.2,
        },
        "style_returns": style_returns,
        "portfolio_weights": {"semiconductor": 0.5, "gold": 0.3, "bond": 0.2},
        "asset_exposures": {
            "semiconductor": {"technology_beta": 1, "semiconductor_beta": 1},
            "gold": {"technology_beta": 0, "semiconductor_beta": 0},
            "bond": {"technology_beta": 0, "semiconductor_beta": 0},
        },
        "candidates": [],
    }
    input_path = tmp_path / "snapshot.json"
    input_path.write_text(json.dumps(snapshot), encoding="utf-8")
    service = VNextService(project_root=tmp_path, artifact_root=tmp_path / "artifacts")
    bundle = service.run_daily("2026-07-10", input_path=input_path)
    assert bundle["regime"]["status"] in {"OK", "PARTIAL"}
    assert bundle["ml_ranker"]["status"] == DataStatus.MISSING.value
    assert service.store.report_path("2026-07-10", "md").exists()
    assert service.store.report_path("2026-07-10", "json").exists()
    assert service.store.report_path("2026-07-10", "csv").exists()
