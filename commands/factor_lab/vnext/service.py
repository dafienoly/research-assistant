"""Application service composing VNext analysis, storage and UI contracts."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .contracts import DataStatus, TradingMode, now_iso
from .execution import TelegramApprovalGate
from .market import compute_index_box, compute_policy_support_proxy, compute_style_rotation_matrix
from .ml import CrossSectionalRanker
from .portfolio import PortfolioRiskAnalyzer
from .regime import RegimeRouter
from .report import VNextReportRenderer
from .semiconductor import SemiconductorMainlineStateMachine
from .snapshot import HubSnapshotBuilder
from .store import VNextArtifactStore


COMPONENTS = {
    "status",
    "data-health",
    "regime",
    "policy-put",
    "semi-mainline",
    "candidates",
    "portfolio-risk",
    "ml-ranker",
    "backtests",
    "paper",
    "shadow",
    "execution-status",
    "antifragile-review",
    "reports",
}


class VNextService:
    def __init__(
        self,
        project_root: str | Path | None = None,
        artifact_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[3])
        root = artifact_root or os.environ.get("HERMES_VNEXT_OUTPUT_DIR") or self.project_root / "data" / "vnext"
        self.store = VNextArtifactStore(root)
        self.approvals = TelegramApprovalGate(self.store.root / "approvals")

    def run_daily(self, as_of: str, *, input_path: str | Path | None = None, refresh_real_data: bool = True) -> dict[str, Any]:
        snapshot = self._load_snapshot(as_of, input_path=input_path, refresh_real_data=refresh_real_data)
        index_box = compute_index_box(
            snapshot.get("index_history", []),
            current=snapshot.get("current_index"),
            as_of=as_of,
            source="tushare:index_daily:000001.SH",
        )
        policy = compute_policy_support_proxy(snapshot, index_box, as_of=as_of)
        policy_score = policy.get("payload", {}).get("policy_support_proxy_score")
        semi_inputs = dict(snapshot.get("semi_inputs", {}))
        semi_inputs["policy_support"] = policy_score
        semi = SemiconductorMainlineStateMachine().evaluate(semi_inputs, as_of=as_of)
        regime_inputs = dict(snapshot.get("regime_inputs", {}))
        regime_inputs["policy_support"] = policy_score
        regime = RegimeRouter().route(regime_inputs, as_of=as_of)
        style_frame = self._style_frame(snapshot.get("style_returns", {}))
        style_rotation = compute_style_rotation_matrix(style_frame, as_of=as_of, source="tushare:fund_daily")
        portfolio = self._portfolio(snapshot, style_frame, as_of)
        ml_ranker = self._ml_ranker(as_of)
        candidates = self._candidates(snapshot, regime, semi, portfolio, ml_ranker, as_of)
        data_health = self.build_data_health(as_of, snapshot=snapshot)
        execution_status = self.execution_status(as_of)

        self.store.write("snapshot", as_of, snapshot)
        self.store.write("policy-put", as_of, {**policy, "index_box": index_box, "style_rotation": style_rotation})
        self.store.write("semi-mainline", as_of, semi)
        self.store.write("regime", as_of, regime)
        self.store.write("portfolio-risk", as_of, portfolio)
        self.store.write("ml-ranker", as_of, ml_ranker)
        self.store.write("candidates", as_of, candidates)
        self.store.write("data-health", as_of, data_health)
        self.store.write("execution-status", as_of, execution_status)
        for optional in ("backtests", "paper", "shadow", "antifragile-review"):
            if self.store.read(optional, as_of).get("status") == DataStatus.MISSING.value:
                self.store.write(optional, as_of, self.store.missing(optional, as_of, "component has not produced a real run for this date"))

        bundle = self.bundle(as_of)
        status = self._status(as_of, bundle)
        self.store.write("status", as_of, status)
        bundle["status"] = status
        report_path = self.store.report_path(as_of, "md")
        VNextReportRenderer().write(bundle, report_path)
        report_json = self.store.report_path(as_of, "json")
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        report_csv = self.store.report_path(as_of, "csv")
        candidate_rows = bundle.get("candidates", {}).get("payload", {}).get("raw_candidates", [])
        pd.DataFrame(candidate_rows).to_csv(report_csv, index=False, encoding="utf-8-sig")
        report_meta = {
            "status": DataStatus.OK.value,
            "as_of": as_of,
            "updated_at": now_iso(),
            "files": [
                {"format": "markdown", "path": str(report_path)},
                {"format": "json", "path": str(report_json)},
                {"format": "csv", "path": str(report_csv)},
            ],
        }
        self.store.write("reports", as_of, report_meta)
        return self.bundle(as_of)

    def bundle(self, as_of: str | None = None) -> dict[str, Any]:
        components = {
            "policy_put": self.store.read("policy-put", as_of),
            "semi_mainline": self.store.read("semi-mainline", as_of),
            "regime": self.store.read("regime", as_of),
            "portfolio_risk": self.store.read("portfolio-risk", as_of),
            "candidates": self.store.read("candidates", as_of),
            "data_health": self.store.read("data-health", as_of),
            "execution_status": self.store.read("execution-status", as_of),
            "ml_ranker": self.store.read("ml-ranker", as_of),
            "backtests": self.store.read("backtests", as_of),
            "paper": self.store.read("paper", as_of),
            "shadow": self.store.read("shadow", as_of),
            "antifragile_review": self.store.read("antifragile-review", as_of),
        }
        resolved_date = as_of or next((value.get("as_of") for value in components.values() if value.get("as_of")), None)
        return {"as_of": resolved_date, **components}

    def component(self, component: str, as_of: str | None = None) -> dict[str, Any]:
        if component not in COMPONENTS:
            raise ValueError(f"unknown VNext component: {component}")
        if component == "data-health" and self.store.read(component, as_of).get("status") == DataStatus.MISSING.value:
            return self.build_data_health(as_of or date.today().isoformat())
        if component == "execution-status" and self.store.read(component, as_of).get("status") == DataStatus.MISSING.value:
            return self.execution_status(as_of or date.today().isoformat())
        return self.store.read(component, as_of)

    def build_data_health(self, as_of: str, *, snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        audit_root = self.project_root / "data" / "audit" / "health"
        audit_specs = (
            ("datahub:coverage", audit_root / "coverage.json", "universe_status"),
            ("datahub:freshness", audit_root / "freshness.json", "status"),
            ("datahub:integrity", audit_root / "integrity.json", "status"),
            ("vnext:data-audit", self.project_root / "artifacts" / "vnext" / "data_audit_report.json", "status"),
        )
        items = [self._health_audit_item(name, path, status_field, as_of) for name, path, status_field in audit_specs]
        if snapshot:
            items.extend(list(snapshot.get("source_statuses", [])))
        bad = [item for item in items if item.get("status") != DataStatus.OK.value]
        ok = len(items) - len(bad)
        if not items or ok == 0:
            overall = DataStatus.MISSING
        elif bad:
            overall = DataStatus.PARTIAL
        else:
            overall = DataStatus.OK
        return {
            "status": overall.value,
            "as_of": as_of,
            "confidence": round(ok / len(items), 4) if items else 0.0,
            "sources": items,
            "missing_evidence": [item.get("source", "unknown") for item in bad],
            "truthfulness": "no mock/demo/fallback substitution",
            "updated_at": now_iso(),
        }

    @staticmethod
    def _health_audit_item(source: str, path: Path, status_field: str, as_of: str) -> dict[str, Any]:
        base = {
            "source": source,
            "path": str(path),
            "status": DataStatus.MISSING.value,
            "records_or_files": 0,
            "generated_at": None,
            "message": "canonical audit artifact missing",
        }
        if not path.is_file():
            return base
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {**base, "status": DataStatus.PARTIAL.value, "message": f"canonical audit unreadable: {exc}"}
        if not isinstance(payload, dict):
            return {**base, "status": DataStatus.PARTIAL.value, "message": "canonical audit is not a JSON object"}

        raw_status = str(payload.get(status_field, "MISSING")).upper()
        status = raw_status if raw_status in {item.value for item in DataStatus} else DataStatus.PARTIAL.value
        generated_at = payload.get("generated_at") or payload.get("observed_at")
        generated = pd.to_datetime(generated_at, errors="coerce", utc=True)
        target = pd.Timestamp(as_of, tz="Asia/Shanghai")
        age_days = max(0, (target.date() - generated.date()).days) if pd.notna(generated) else None
        if generated_at is None or pd.isna(generated):
            status = DataStatus.PARTIAL.value
        elif age_days is not None and age_days > 2:
            status = DataStatus.STALE.value

        evidence = {
            key: payload.get(key)
            for key in (
                "universe_status",
                "total_stocks",
                "stocks_with_data",
                "active_missing_files",
                "blocking_stock_count",
                "files_checked",
                "problematic_file_count",
                "data_freshness_status",
                "data_gap_status",
                "formal_ml_status",
                "shadow_status",
                "order_draft_status",
                "blocking_reasons",
                "warnings",
                "recovery",
            )
            if key in payload
        }
        return {
            **base,
            "status": status,
            "records_or_files": int(payload.get("files_checked") or payload.get("stocks_with_data") or 1),
            "generated_at": generated_at,
            "age_days": age_days,
            "evidence": evidence,
            "message": "canonical DataHub audit evidence",
        }

    def execution_status(self, as_of: str) -> dict[str, Any]:
        kill_switch = os.environ.get("HERMES_KILL_SWITCH", "false").lower() == "true"
        configured_mode = os.environ.get("HERMES_VNEXT_TRADING_MODE", TradingMode.PAPER.value)
        configuration_error = None
        try:
            requested_mode = TradingMode(configured_mode)
        except ValueError:
            requested_mode = TradingMode.LIVE_DISABLED
            configuration_error = f"invalid trading mode: {configured_mode}"
        if requested_mode == TradingMode.LIVE_ENABLED:
            requested_mode = TradingMode.LIVE_DISABLED
            configuration_error = "LIVE_ENABLED is unreachable while no_live_trade=true"
        mode = TradingMode.KILL_SWITCH_TRIGGERED if kill_switch else requested_mode
        approvals = self.approvals.list()
        pending = sum(record.get("status") in {"PENDING", "DELAYED", "APPROVED_UNSIGNABLE"} for record in approvals)
        probe = self.store.read("qmt-probe")
        probe_ok = probe.get("status") in {DataStatus.OK.value, DataStatus.PARTIAL.value}
        connected = probe_ok and bool(probe.get("connected"))
        account_readable = connected and bool(probe.get("account_readable"))
        positions_readable = connected and bool(probe.get("positions_readable"))
        signing_configured = bool(os.environ.get("HERMES_APPROVAL_SIGNING_KEY"))
        return {
            "status": DataStatus.OK.value,
            "as_of": as_of,
            "trading_mode": mode.value,
            "no_live_trade": True,
            "live_enabled": False,
            "kill_switch_triggered": kill_switch,
            "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
            "telegram_pending": pending,
            "approval_signing_configured": signing_configured,
            "approval_envelope_required": True,
            "accepted_input_contract": "ApprovedOrderEnvelope",
            "execution_readiness": DataStatus.PARTIAL.value if not signing_configured else DataStatus.OK.value,
            "configuration_error": configuration_error,
            "miniqmt": {
                "connection_status": DataStatus.OK.value if connected else DataStatus.MISSING.value,
                "account_permission_status": DataStatus.OK.value if account_readable else DataStatus.MISSING.value,
                "funds_status": DataStatus.MISSING.value,
                "position_sync_status": DataStatus.OK.value if positions_readable else DataStatus.MISSING.value,
                "order_channel_status": "DISABLED",
                "cancel_channel_status": "DISABLED",
                "trade_callback_status": DataStatus.MISSING.value,
                "last_probe": probe.get("updated_at") if probe_ok else None,
                "probe_status": probe.get("status", DataStatus.MISSING.value),
            },
            "message": "当前不会真实下单",
            "updated_at": now_iso(),
        }

    def _load_snapshot(self, as_of: str, *, input_path: str | Path | None, refresh_real_data: bool) -> dict[str, Any]:
        if input_path:
            path = Path(input_path)
            if not path.exists():
                return self.store.missing("snapshot", as_of, f"input snapshot missing: {path}")
            return json.loads(path.read_text(encoding="utf-8"))
        cached = self.store.read("snapshot", as_of)
        if not refresh_real_data and cached.get("status") != DataStatus.MISSING.value:
            return cached
        return HubSnapshotBuilder(self.project_root).build(as_of)

    @staticmethod
    def _style_frame(style_returns: Mapping[str, Any]) -> pd.DataFrame:
        series = {}
        for name, records in style_returns.items():
            values = pd.Series(
                {pd.Timestamp(item["date"]): float(item["return"]) for item in records if item.get("return") is not None},
                dtype=float,
            )
            if not values.empty:
                series[name] = values
        return pd.DataFrame(series).sort_index() if series else pd.DataFrame()

    @staticmethod
    def _portfolio(snapshot: Mapping[str, Any], style_frame: pd.DataFrame, as_of: str) -> dict[str, Any]:
        weights = snapshot.get("portfolio_weights", {})
        if style_frame.empty or not weights:
            return {
                "status": DataStatus.MISSING.value,
                "as_of": as_of,
                "confidence": 0.0,
                "evidence": [],
                "missing_evidence": ["portfolio_weights_or_multi_asset_returns"],
                "payload": {"false_diversification_warning": None},
            }
        return PortfolioRiskAnalyzer().analyze(
            style_frame,
            weights,
            as_of=as_of,
            exposures=snapshot.get("asset_exposures", {}),
            source="tushare:fund_daily",
        )

    @staticmethod
    def _candidates(
        snapshot: Mapping[str, Any],
        regime: Mapping[str, Any],
        semi: Mapping[str, Any],
        portfolio: Mapping[str, Any],
        ml_ranker: Mapping[str, Any],
        as_of: str,
    ) -> dict[str, Any]:
        raw = list(snapshot.get("candidates", []))
        ml_scores = {
            str(item.get("symbol")): item
            for item in ml_ranker.get("scores", [])
            if isinstance(item, Mapping) and item.get("symbol")
        }
        for item in raw:
            scored = ml_scores.get(str(item.get("symbol")), {})
            if scored:
                item["ml_rank_score"] = scored.get("candidate_score")
                item["ml_rank"] = scored.get("rank")
                item["model_version"] = scored.get("model_version")
                item["feature_attribution"] = scored.get("feature_attribution")
            item["regime_applicability"] = regime.get("confidence")
            item["mainline_fit"] = semi.get("confidence")
            item["research_signal"] = True
            checks = [item.get("liquidity_check"), item.get("price_limit_check"), item.get("st_suspension_check")]
            item["execution_eligible"] = all(check == DataStatus.OK.value for check in checks) and item.get("tradability") in {
                "tradable",
                "ETF_substitution",
            }
            if not item["execution_eligible"]:
                item["blocked_reason"] = "mandatory execution checks are missing or the asset is restricted"
        account = [item for item in raw if item.get("tradability") == "tradable"]
        restricted = [item for item in raw if item.get("tradability") == "restricted"]
        substitutes = [item for item in raw if item.get("tradability") == "ETF_substitution"]
        watch = [item for item in raw if item.get("tradability") in {"watch_only", "proxy_signal"}]
        blocked = [item for item in raw if not item.get("execution_eligible")]
        return {
            "status": DataStatus.OK.value if raw else DataStatus.MISSING.value,
            "as_of": as_of,
            "confidence": min(float(regime.get("confidence", 0)), float(semi.get("confidence", 0))) if raw else 0.0,
            "evidence": [f"raw_candidates={len(raw)}"],
            "missing_evidence": [] if raw else ["candidate_source"],
            "payload": {
                "raw_candidates": raw,
                "account_tradable_candidates": account,
                "restricted_board_candidates": restricted,
                "etf_substitution_candidates": substitutes,
                "watch_only_candidates": watch,
                "blocked_candidates": blocked,
                "paper_candidates": [item for item in raw if item.get("execution_eligible")],
                "shadow_candidates": [item for item in raw if item.get("execution_eligible")],
                "live_dry_run_candidates": [item for item in raw if item.get("execution_eligible")],
                "portfolio_false_diversification": portfolio.get("payload", {}).get("false_diversification_warning"),
            },
        }

    def _ml_ranker(self, as_of: str) -> dict[str, Any]:
        scoring_path = self.project_root / "data" / "vnext" / "ml" / f"scoring_{as_of}.csv"
        registry_path = self.store.root / "ml" / "model_registry.json"
        if not scoring_path.exists():
            return self.store.missing("ml-ranker", as_of, f"scoring data missing: {scoring_path}")
        if not registry_path.exists():
            return self.store.missing("ml-ranker", as_of, "model registry missing")
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            models = registry.get("models", [])
            if not models:
                return self.store.missing("ml-ranker", as_of, "no registered model")
            artifact = models[-1].get("model_artifact", {})
            ranker = CrossSectionalRanker.load_model(
                artifact["model_path"],
                expected_sha256=artifact.get("sha256"),
            )
            frame = pd.read_csv(scoring_path)
            symbols = frame["symbol"].astype(str).tolist() if "symbol" in frame else [str(index) for index in frame.index]
            card = ranker.model_card()
            return {
                "status": card["status"],
                "as_of": as_of,
                "confidence": card["confidence"],
                "risk_warning": card["risk_warning"],
                "model_card": card,
                "scores": ranker.score(frame, symbols=symbols),
                "direct_buy_sell_output": False,
                "data_sources": [str(scoring_path), str(registry_path)],
                "updated_at": now_iso(),
            }
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            return self.store.missing("ml-ranker", as_of, f"model scoring failed: {type(exc).__name__}")

    @staticmethod
    def _status(as_of: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
        regime = bundle.get("regime", {})
        semi = bundle.get("semi_mainline", {})
        data = bundle.get("data_health", {})
        execution = bundle.get("execution_status", {})
        return {
            "status": DataStatus.OK.value if data.get("status") == DataStatus.OK.value else DataStatus.PARTIAL.value,
            "as_of": as_of,
            "trading_mode": execution.get("trading_mode", TradingMode.READ_ONLY.value),
            "kill_switch_triggered": execution.get("kill_switch_triggered", False),
            "data_freshness": data.get("status", DataStatus.MISSING.value),
            "regime": regime.get("payload", {}).get("regime_name", "MISSING"),
            "regime_confidence": regime.get("confidence", 0),
            "semiconductor_state": semi.get("payload", {}).get("state", "MISSING"),
            "semiconductor_confidence": semi.get("confidence", 0),
            "allow_new_buy": regime.get("payload", {}).get("allow_new_buy", False),
            "allow_overnight": regime.get("payload", {}).get("allow_overnight", False),
            "telegram_pending": execution.get("telegram_pending", 0),
            "no_live_trade": True,
            "live_enabled": False,
            "updated_at": now_iso(),
        }
