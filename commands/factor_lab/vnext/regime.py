"""Multi-asset regime router with explicit evidence degradation."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ComponentResult, DataStatus, RegimeName, clamp, finite_number


BUDGETS = {
    RegimeName.TECH_ATTACK: (0.78, 0.62, 0.10, 0.12),
    RegimeName.RISK_ON_BROAD: (0.82, 0.38, 0.10, 0.08),
    RegimeName.DEFENSIVE_ROTATION: (0.35, 0.15, 0.50, 0.15),
    RegimeName.LIQUIDITY_SHOCK: (0.12, 0.05, 0.48, 0.40),
    RegimeName.OVERSEAS_TECH_LEAD: (0.55, 0.35, 0.20, 0.25),
    RegimeName.A_SHARE_POLICY_ALPHA: (0.62, 0.45, 0.20, 0.18),
    RegimeName.RANGE_BOUND: (0.42, 0.25, 0.28, 0.30),
    RegimeName.CASH_OR_WAIT: (0.08, 0.02, 0.22, 0.70),
}


class RegimeRouter:
    REQUIRED = (
        "market_trend",
        "breadth",
        "liquidity",
        "technology_strength",
        "semiconductor_strength",
        "defensive_strength",
        "policy_support",
        "overseas_tech_lead",
        "volatility_stress",
    )

    def route(self, inputs: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
        raw = {name: finite_number(inputs.get(name)) for name in self.REQUIRED}
        missing = [name for name, value in raw.items() if value is None]
        availability = (len(raw) - len(missing)) / len(raw)
        values = {name: clamp(value) if value is not None else 0.5 for name, value in raw.items()}
        regime, reason = self._classify(values, availability)
        risk, semi, defensive, cash = BUDGETS[regime]
        confidence = clamp(availability * self._separation_confidence(values, regime))
        if availability < 0.45:
            regime = RegimeName.CASH_OR_WAIT
            risk, semi, defensive, cash = BUDGETS[regime]
            reason = "real inputs are insufficient; router fails safe to CASH_OR_WAIT"
        status = DataStatus.OK if not missing else (DataStatus.MISSING if availability < 0.45 else DataStatus.PARTIAL)
        allow_new_buy = regime not in {RegimeName.LIQUIDITY_SHOCK, RegimeName.CASH_OR_WAIT} and confidence >= 0.55
        allow_overnight = regime in {
            RegimeName.TECH_ATTACK,
            RegimeName.RISK_ON_BROAD,
            RegimeName.A_SHARE_POLICY_ALPHA,
        } and confidence >= 0.62
        return ComponentResult(
            status=status,
            as_of=as_of,
            confidence=confidence,
            evidence=[f"{name}={value:.3f}" for name, value in raw.items() if value is not None] + [reason],
            missing_evidence=missing,
            data_sources=list(inputs.get("data_sources", [])),
            payload={
                "regime_name": regime.value,
                "recommended_risk_budget": risk,
                "semiconductor_budget": semi,
                "defensive_budget": defensive,
                "cash_budget": cash,
                "allow_overnight": allow_overnight,
                "allow_new_buy": allow_new_buy,
                "watch_only_reason": None if allow_new_buy else reason,
                "research_only": True,
            },
        ).to_dict()

    @staticmethod
    def _classify(values: Mapping[str, float], availability: float) -> tuple[RegimeName, str]:
        if availability < 0.45:
            return RegimeName.CASH_OR_WAIT, "insufficient evidence"
        if values["volatility_stress"] > 0.76 and values["liquidity"] < 0.32:
            return RegimeName.LIQUIDITY_SHOCK, "volatility stress and liquidity contraction dominate"
        if values["policy_support"] > 0.67 and values["technology_strength"] > 0.53:
            return RegimeName.A_SHARE_POLICY_ALPHA, "policy-support proxy aligns with domestic technology strength"
        if values["overseas_tech_lead"] > 0.72 and values["technology_strength"] > 0.48:
            return RegimeName.OVERSEAS_TECH_LEAD, "overseas technology leads and domestic mapping remains constructive"
        if (
            values["technology_strength"] > 0.68
            and values["semiconductor_strength"] > 0.65
            and values["liquidity"] > 0.48
        ):
            return RegimeName.TECH_ATTACK, "technology and semiconductors lead with adequate liquidity"
        if values["market_trend"] > 0.62 and values["breadth"] > 0.58:
            return RegimeName.RISK_ON_BROAD, "broad trend and breadth confirm risk-on participation"
        if values["defensive_strength"] > 0.64 and values["technology_strength"] < 0.46:
            return RegimeName.DEFENSIVE_ROTATION, "defensive assets lead while technology weakens"
        if values["market_trend"] < 0.28 and values["breadth"] < 0.34:
            return RegimeName.CASH_OR_WAIT, "trend and breadth are both weak"
        return RegimeName.RANGE_BOUND, "signals are mixed and consistent with range-bound rotation"

    @staticmethod
    def _separation_confidence(values: Mapping[str, float], regime: RegimeName) -> float:
        if regime == RegimeName.TECH_ATTACK:
            signal = (values["technology_strength"] + values["semiconductor_strength"] + values["liquidity"]) / 3
        elif regime == RegimeName.LIQUIDITY_SHOCK:
            signal = (values["volatility_stress"] + 1 - values["liquidity"]) / 2
        elif regime == RegimeName.A_SHARE_POLICY_ALPHA:
            signal = (values["policy_support"] + values["technology_strength"]) / 2
        elif regime == RegimeName.DEFENSIVE_ROTATION:
            signal = (values["defensive_strength"] + 1 - values["technology_strength"]) / 2
        else:
            signal = 0.65
        return clamp(0.45 + 0.55 * signal)
