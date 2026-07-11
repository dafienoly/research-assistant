"""Named Hermes domain-engine adapters and one auditable daily decision contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from pydantic import Field

from .contracts import ContractModel, QualityStatus, now_iso, sha256_payload
from .market import (
    compute_breadth_divergence,
    compute_index_box,
    compute_policy_support_proxy,
    compute_style_rotation_matrix,
)
from .regime import RegimeRouter
from .semiconductor import SemiconductorMainlineStateMachine
from .target_weights import ASSET_PROXY_SYMBOLS


class DomainDecision(ContractModel):
    as_of: str
    data_snapshot_id: str
    state: str
    regime: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    missing_evidence: list[str]
    transition_reason: str
    recommended_risk_budget: float = Field(ge=0.0, le=1.0)
    semiconductor_budget: float = Field(ge=0.0, le=1.0)
    defensive_budget: float = Field(ge=0.0, le=1.0)
    cash_budget: float = Field(ge=0.0, le=1.0)
    allow_new_buy: bool
    allow_overnight: bool
    quality_status: QualityStatus
    universe: dict[str, Any]
    index_box: dict[str, Any]
    policy_put: dict[str, Any]
    breadth_divergence: dict[str, Any]
    style_rotation: dict[str, Any]
    semiconductor_mainline: dict[str, Any]
    regime_router: dict[str, Any]
    decision_hash: str = ""
    generated_at: str = Field(default_factory=now_iso)

    def model_post_init(self, __context: Any) -> None:
        if not self.decision_hash:
            object.__setattr__(
                self,
                "decision_hash",
                sha256_payload(self.model_dump(mode="json", exclude={"decision_hash", "generated_at"})),
            )


class MultiAssetUniverseRegistry:
    def build(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        weights = snapshot.get("portfolio_weights", {})
        entries = []
        for role, symbol in ASSET_PROXY_SYMBOLS.items():
            if role not in weights:
                continue
            entries.append(
                {
                    "role": role,
                    "instrument_id": symbol,
                    "market": "A_SHARE",
                    "instrument_type": "ETF_OR_LISTED_PROXY",
                    "raw_weight": float(weights[role]),
                    "data_snapshot_id": snapshot.get("data_snapshot_id"),
                }
            )
        return {
            "status": QualityStatus.OK.value if entries else QualityStatus.MISSING.value,
            "data_snapshot_id": snapshot.get("data_snapshot_id"),
            "entries": entries,
            "roles": [entry["role"] for entry in entries],
            "cash_role_explicit": True,
            "account_permission_required_downstream": True,
        }


class IndexBoxEstimator:
    def estimate(self, snapshot: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
        return compute_index_box(
            snapshot.get("index_history", []),
            current=snapshot.get("current_index"),
            as_of=as_of,
            source="tushare:index_daily:000001.SH",
        )


class PolicySupportProxy:
    def evaluate(self, snapshot: Mapping[str, Any], index_box: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
        return compute_policy_support_proxy(snapshot, index_box, as_of=as_of)


class BreadthDivergenceEngine:
    def evaluate(self, snapshot: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
        score, evidence, missing = compute_breadth_divergence(
            advancing=snapshot.get("advancing"),
            declining=snapshot.get("declining"),
            index_reversal_strength=snapshot.get("intraday_reversal_strength"),
            semiconductor_relative_strength=snapshot.get("semiconductor_relative_strength"),
            large_cap_tech_support=snapshot.get("large_cap_tech_support"),
        )
        return {
            "status": QualityStatus.MISSING.value if score is None else QualityStatus.OK.value if not missing else QualityStatus.PARTIAL.value,
            "as_of": as_of,
            "breadth_divergence_score": score,
            "evidence": evidence,
            "missing_evidence": missing,
        }


class StyleRotationMatrix:
    def evaluate(self, snapshot: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
        series = {}
        for name, records in snapshot.get("style_returns", {}).items():
            values = {
                pd.Timestamp(item["date"]): float(item["return"])
                for item in records
                if item.get("return") is not None
            }
            if values:
                series[name] = pd.Series(values, dtype=float)
        frame = pd.DataFrame(series).sort_index() if series else pd.DataFrame()
        return compute_style_rotation_matrix(frame, as_of=as_of, source="immutable_snapshot:style_returns")


class DomainDecisionOrchestrator:
    def run(self, project_root: str | Path, *, as_of: str, output_path: str | Path) -> DomainDecision:
        root = Path(project_root)
        snapshot = json.loads((root / "data" / "vnext" / "snapshot" / f"{as_of}.json").read_text(encoding="utf-8"))
        universe = MultiAssetUniverseRegistry().build(snapshot)
        index_box = IndexBoxEstimator().estimate(snapshot, as_of=as_of)
        policy = PolicySupportProxy().evaluate(snapshot, index_box, as_of=as_of)
        breadth = BreadthDivergenceEngine().evaluate(snapshot, as_of=as_of)
        style = StyleRotationMatrix().evaluate(snapshot, as_of=as_of)
        policy_score = policy.get("payload", {}).get("policy_support_proxy_score")
        semi_inputs = dict(snapshot.get("semi_inputs", {}))
        semi_inputs["policy_support"] = policy_score
        semi = SemiconductorMainlineStateMachine().evaluate(semi_inputs, as_of=as_of)
        regime_inputs = dict(snapshot.get("regime_inputs", {}))
        regime_inputs["policy_support"] = policy_score
        regime = RegimeRouter().route(regime_inputs, as_of=as_of)
        semi_payload = semi.get("payload", {})
        regime_payload = regime.get("payload", {})
        subcomponents = [index_box, policy, breadth, style, semi, regime]
        missing = sorted(
            {
                item
                for component in subcomponents
                for item in component.get("missing_evidence", [])
            }
        )
        statuses = {str(component.get("status")) for component in subcomponents}
        if QualityStatus.MISSING.value in statuses:
            quality = QualityStatus.PARTIAL if len(statuses) > 1 else QualityStatus.MISSING
        elif QualityStatus.PARTIAL.value in statuses or missing:
            quality = QualityStatus.PARTIAL
        else:
            quality = QualityStatus.OK
        evidence = [
            item
            for component in subcomponents
            for item in component.get("evidence", [])
        ]
        decision = DomainDecision(
            as_of=as_of,
            data_snapshot_id=str(snapshot["data_snapshot_id"]),
            state=str(semi_payload.get("state", "UNKNOWN")),
            regime=str(regime_payload.get("regime_name", "UNKNOWN")),
            confidence=min(float(semi.get("confidence", 0)), float(regime.get("confidence", 0))),
            evidence=evidence,
            missing_evidence=missing,
            transition_reason=str(semi_payload.get("state_transition_reason", "missing transition reason")),
            recommended_risk_budget=float(regime_payload.get("recommended_risk_budget", 0)),
            semiconductor_budget=float(regime_payload.get("semiconductor_budget", 0)),
            defensive_budget=float(regime_payload.get("defensive_budget", 0)),
            cash_budget=float(regime_payload.get("cash_budget", 1)),
            allow_new_buy=bool(regime_payload.get("allow_new_buy", False)),
            allow_overnight=bool(regime_payload.get("allow_overnight", False)),
            quality_status=quality,
            universe=universe,
            index_box=index_box,
            policy_put=policy,
            breadth_divergence=breadth,
            style_rotation=style,
            semiconductor_mainline=semi,
            regime_router=regime,
        )
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(destination)
        return decision
