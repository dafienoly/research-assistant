"""Hermes-owned signal-to-target-weight adapters and risk overlay pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import (
    QualityStatus,
    ResearchSignal,
    TargetPortfolioWeights,
    TargetWeightLine,
    Tradability,
    sha256_payload,
)


ASSET_PROXY_SYMBOLS = {
    "semiconductor": "512480.SH",
    "technology": "515000.SH",
    "star_chip": "588200.SH",
    "hong_kong_tech": "513180.SH",
    "dividend": "510880.SH",
    "financial": "510230.SH",
    "consumer": "159928.SZ",
    "cyclical": "512400.SH",
    "military": "512660.SH",
    "ai_compute": "515070.SH",
    "gold": "518880.SH",
    "bond": "511010.SH",
    "nasdaq_proxy": "513100.SH",
}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class TargetWeightPipeline:
    """Apply account eligibility, explicit substitutions and risk budget caps."""

    def build(
        self,
        *,
        raw_weights: Mapping[str, float],
        current_weights: Mapping[str, float] | None,
        tradability: Mapping[str, Tradability],
        substitutions: Mapping[str, str] | None,
        account_id: str,
        as_of: str,
        data_snapshot_id: str,
        universe_snapshot_id: str,
        source_strategy: str,
        strategy_version: str,
        model_version: str | None,
        regime_state: str,
        semi_mainline_state: str,
        confidence: float,
        max_invested_weight: float,
        quality_status: QualityStatus,
        evidence: Sequence[str] = (),
        missing_evidence: Sequence[str] = (),
        constraints: Mapping[str, Any] | None = None,
    ) -> TargetPortfolioWeights:
        if not raw_weights:
            raise ValueError("raw_weights cannot be empty")
        if not 0 <= max_invested_weight <= 1:
            raise ValueError("max_invested_weight must be in [0, 1]")
        raw = {str(symbol): float(weight) for symbol, weight in raw_weights.items()}
        if any(weight < 0 or weight > 1 for weight in raw.values()):
            raise ValueError("raw weights must be in [0, 1]")
        if sum(raw.values()) > 1.0 + 1e-8:
            raise ValueError("raw weights cannot sum above 1")
        current = {str(symbol): float(weight) for symbol, weight in (current_weights or {}).items()}
        substitution_map = {str(symbol): str(etf) for symbol, etf in (substitutions or {}).items()}
        eligible: dict[str, float] = {}
        lineage: dict[str, list[str]] = {}
        all_symbols = set(raw)
        for symbol, weight in raw.items():
            permission = tradability.get(symbol, Tradability.BLOCKED)
            if permission in {Tradability.TRADABLE, Tradability.RISK_HEDGE, Tradability.EXECUTION_CANDIDATE}:
                eligible[symbol] = weight
                continue
            substitute = substitution_map.get(symbol)
            eligible[symbol] = 0.0
            if permission == Tradability.RESTRICTED and substitute:
                all_symbols.add(substitute)
                eligible[substitute] = eligible.get(substitute, 0.0) + weight
                lineage.setdefault(substitute, []).append(symbol)

        for symbol in all_symbols:
            raw.setdefault(symbol, 0.0)
            eligible.setdefault(symbol, 0.0)
        eligible_total = sum(eligible.values())
        scale = min(1.0, max_invested_weight / eligible_total) if eligible_total > 0 else 0.0
        adjusted = {symbol: weight * scale for symbol, weight in eligible.items()}
        invested = sum(adjusted.values())
        cash_weight = max(0.0, 1.0 - invested)
        run_identity = {
            "account_id": account_id,
            "as_of": as_of,
            "data_snapshot_id": data_snapshot_id,
            "raw_weights": raw,
            "tradability": {symbol: tradability.get(symbol, Tradability.BLOCKED).value for symbol in raw},
            "substitutions": substitution_map,
            "regime_state": regime_state,
            "semi_mainline_state": semi_mainline_state,
            "max_invested_weight": max_invested_weight,
            "strategy_version": strategy_version,
        }
        portfolio_run_id = f"weights-{as_of}-{sha256_payload(run_identity)[:16]}"
        evidence_bundle_id = f"evidence-{sha256_payload(list(evidence))[:16]}"
        lines: list[TargetWeightLine] = []
        for symbol in sorted(raw):
            if symbol in lineage:
                permission = Tradability.ETF_SUBSTITUTION
                substitution_of = "restricted_basket:" + "|".join(sorted(lineage[symbol]))
            else:
                permission = tradability.get(symbol, Tradability.BLOCKED)
                substitution_of = None
            current_weight = current.get(symbol, 0.0)
            target = adjusted.get(symbol, 0.0)
            lines.append(
                TargetWeightLine(
                    instrument_id=symbol,
                    current_weight=current_weight,
                    raw_target_weight=raw[symbol],
                    eligible_target_weight=eligible[symbol],
                    risk_adjusted_target_weight=target,
                    weight_delta=target - current_weight,
                    source_strategy=source_strategy,
                    model_version=model_version,
                    confidence=confidence,
                    risk_budget=max_invested_weight,
                    tradability=permission,
                    substitution_of=substitution_of,
                    quality_status=quality_status,
                    evidence=list(evidence),
                    missing_evidence=list(missing_evidence),
                )
            )
        book_constraints = {
            "max_invested_weight": max_invested_weight,
            "eligibility_enforced": True,
            "restricted_weight_zero": True,
            "watch_only_weight_zero": True,
            "explicit_etf_substitution": True,
            "current_holdings_snapshot_available": bool(current_weights),
            "order_drafts_generated": False,
            "no_live_trade": True,
            **dict(constraints or {}),
        }
        return TargetPortfolioWeights(
            portfolio_run_id=portfolio_run_id,
            account_id=account_id,
            as_of=as_of,
            universe_snapshot_id=universe_snapshot_id,
            data_snapshot_id=data_snapshot_id,
            strategy_version=strategy_version,
            model_version=model_version,
            regime_state=regime_state,
            semi_mainline_state=semi_mainline_state,
            weights=lines,
            raw_weights={line.instrument_id: line.raw_target_weight for line in lines},
            eligibility_adjusted_weights={line.instrument_id: line.eligible_target_weight for line in lines},
            risk_adjusted_weights={line.instrument_id: line.risk_adjusted_target_weight for line in lines},
            cash_weight=cash_weight,
            constraints=book_constraints,
            substitutions={
                line.instrument_id: str(line.substitution_of)
                for line in lines
                if line.substitution_of is not None
            },
            evidence_bundle_id=evidence_bundle_id,
            quality_status=quality_status,
        )


class TopNTargetWeightAdapter:
    """Compatibility bridge from ranked ResearchSignal rows to target weights."""

    def __init__(self, pipeline: TargetWeightPipeline | None = None) -> None:
        self.pipeline = pipeline or TargetWeightPipeline()

    def adapt(
        self,
        signals: Sequence[ResearchSignal],
        *,
        top_n: int,
        tradability: Mapping[str, Tradability],
        substitutions: Mapping[str, str] | None,
        account_id: str,
        data_snapshot_id: str,
        regime_state: str,
        semi_mainline_state: str,
        max_invested_weight: float = 1.0,
    ) -> TargetPortfolioWeights:
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        usable = [
            signal
            for signal in signals
            if signal.quality_status not in {QualityStatus.MISSING, QualityStatus.STALE, QualityStatus.BLOCKED}
        ]
        selected = sorted(
            usable,
            key=lambda signal: (
                signal.rank if signal.rank is not None else 10**9,
                -signal.confidence,
                signal.instrument_id,
            ),
        )[:top_n]
        if not selected:
            raise ValueError("no usable research signals")
        raw = {signal.instrument_id: 1.0 / len(selected) for signal in selected}
        quality = (
            QualityStatus.BACKTEST_ONLY
            if any(signal.quality_status == QualityStatus.BACKTEST_ONLY for signal in selected)
            else QualityStatus.OK
        )
        return self.pipeline.build(
            raw_weights=raw,
            current_weights=None,
            tradability=tradability,
            substitutions=substitutions,
            account_id=account_id,
            as_of=max(signal.as_of for signal in selected),
            data_snapshot_id=data_snapshot_id,
            universe_snapshot_id=f"topn-{sha256_payload([signal.instrument_id for signal in selected])[:16]}",
            source_strategy="legacy_topn_adapter",
            strategy_version="topn-target-weights-v1",
            model_version=next((signal.model_version for signal in selected if signal.model_version), None),
            regime_state=regime_state,
            semi_mainline_state=semi_mainline_state,
            confidence=min(signal.confidence for signal in selected),
            max_invested_weight=max_invested_weight,
            quality_status=quality,
            evidence=[f"signal:{signal.signal_run_id}:{signal.instrument_id}" for signal in selected],
            missing_evidence=[item for signal in selected for item in signal.missing_evidence],
            constraints={"legacy_topn": top_n, "selected_instruments": [signal.instrument_id for signal in selected]},
        )


class DailyArtifactTargetWeightAdapter:
    """Build the real daily multi-asset target book from VNext artifacts."""

    def __init__(self, pipeline: TargetWeightPipeline | None = None) -> None:
        self.pipeline = pipeline or TargetWeightPipeline()

    def build(self, project_root: str | Path, *, as_of: str, output_path: str | Path) -> TargetPortfolioWeights:
        root = Path(project_root)
        snapshot = json.loads((root / "data" / "vnext" / "snapshot" / f"{as_of}.json").read_text(encoding="utf-8"))
        regime = json.loads((root / "data" / "vnext" / "regime" / f"{as_of}.json").read_text(encoding="utf-8"))
        semi = json.loads((root / "data" / "vnext" / "semi-mainline" / f"{as_of}.json").read_text(encoding="utf-8"))
        audit = json.loads((root / "artifacts" / "vnext" / "data_audit_report.json").read_text(encoding="utf-8"))
        domain_path = root / "artifacts" / "vnext" / "domain_decision.json"
        domain = json.loads(domain_path.read_text(encoding="utf-8")) if domain_path.exists() else {}
        if domain and domain.get("data_snapshot_id") != snapshot.get("data_snapshot_id"):
            raise ValueError("domain decision and snapshot IDs differ")
        roles = {str(role): float(weight) for role, weight in snapshot.get("portfolio_weights", {}).items()}
        semi_state = str(domain.get("state") or semi.get("payload", {}).get("state", "UNKNOWN"))
        overlay_removed: list[str] = []
        if semi_state in {"SEMI_DISTRIBUTION", "SEMI_RETREAT", "SEMI_FAILURE"}:
            for role in ("semiconductor", "star_chip"):
                if roles.get(role, 0) > 0:
                    roles[role] = 0.0
                    overlay_removed.append(role)
        raw = {ASSET_PROXY_SYMBOLS[role]: weight for role, weight in roles.items() if role in ASSET_PROXY_SYMBOLS}
        regime_payload = regime.get("payload", {})
        cash_budget = float(domain.get("cash_budget", regime_payload.get("cash_budget", 1.0)))
        data_ok = audit.get("status") == QualityStatus.OK.value
        quality = QualityStatus.OK if data_ok else QualityStatus.BACKTEST_ONLY
        role_by_symbol = {ASSET_PROXY_SYMBOLS[role]: role for role in roles if role in ASSET_PROXY_SYMBOLS}
        tradability = {
            symbol: Tradability.RISK_HEDGE if role_by_symbol[symbol] in {"gold", "bond"} else Tradability.TRADABLE
            for symbol in raw
        }
        evidence = [
            f"snapshot:{snapshot.get('data_snapshot_id')}",
            f"regime:{regime_payload.get('regime_name')}",
            f"semi:{semi_state}",
            f"data_audit:{audit.get('status')}",
        ]
        if domain:
            evidence.append(f"domain_decision:{domain.get('decision_hash')}")
        book = self.pipeline.build(
            raw_weights=raw,
            current_weights=None,
            tradability=tradability,
            substitutions=None,
            account_id="research-account-no-position-snapshot",
            as_of=as_of,
            data_snapshot_id=str(snapshot["data_snapshot_id"]),
            universe_snapshot_id=f"multi-asset-{snapshot['data_snapshot_id']}",
            source_strategy="vnext_multi_asset_overlay",
            strategy_version="target-weights-v1",
            model_version=None,
            regime_state=str(domain.get("regime") or regime_payload.get("regime_name", "UNKNOWN")),
            semi_mainline_state=semi_state,
            confidence=float(domain.get("confidence", min(float(regime.get("confidence", 0)), float(semi.get("confidence", 0))))),
            max_invested_weight=max(0.0, min(1.0, 1.0 - cash_budget)),
            quality_status=quality,
            evidence=evidence,
            missing_evidence=list(audit.get("blocking_reasons", [])),
            constraints={
                "role_by_symbol": role_by_symbol,
                "semi_overlay_removed": overlay_removed,
                "data_audit_status": audit.get("status"),
                "formal_execution_eligible": data_ok,
                "domain_decision_hash": domain.get("decision_hash"),
                "domain_quality_status": domain.get("quality_status"),
            },
        )
        _atomic_json(Path(output_path), book.to_dict())
        return book
