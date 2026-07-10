"""Evidence-driven semiconductor mainline state machine."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ComponentResult, DataStatus, MainlineState, clamp, finite_number


ACTION_BY_STATE = {
    MainlineState.SEMI_DORMANT: "watch_only",
    MainlineState.SEMI_POLICY_WARMUP: "controlled_attack",
    MainlineState.SEMI_MAINLINE_START: "controlled_attack",
    MainlineState.SEMI_MAINLINE_CONFIRM: "aggressive_attack",
    MainlineState.SEMI_ACCELERATION: "hold_core",
    MainlineState.SEMI_HIGH_DIVERGENCE: "reduce_chasing",
    MainlineState.SEMI_ROTATION_INTERNAL: "ETF_substitution",
    MainlineState.SEMI_PULLBACK_HEALTHY: "hold_core",
    MainlineState.SEMI_POLICY_RESCUE: "controlled_attack",
    MainlineState.SEMI_DISTRIBUTION: "defensive_wait",
    MainlineState.SEMI_RETREAT: "defensive_wait",
    MainlineState.SEMI_FAILURE: "exit_or_avoid",
}


PREFERRED_INSTRUMENT = {
    "aggressive_attack": "account_tradable_mainboard_core",
    "controlled_attack": "semiconductor_etf_or_mainboard_core",
    "hold_core": "existing_core_or_semiconductor_etf",
    "ETF_substitution": "semiconductor_or_star_chip_etf",
    "reduce_chasing": "core_only_or_cash",
    "defensive_wait": "cash_dividend_gold_bond",
    "exit_or_avoid": "cash_or_risk_hedge",
    "watch_only": "watchlist",
}


class SemiconductorMainlineStateMachine:
    """Classify the phase of the mainline; it never emits executable orders."""

    REQUIRED_INPUTS = (
        "relative_strength",
        "etf_volume_strength",
        "anchor_support",
        "subsector_breadth",
        "policy_support",
        "distribution_risk",
        "drawdown_pressure",
        "liquidity_support",
    )

    def evaluate(
        self,
        inputs: Mapping[str, Any],
        *,
        as_of: str,
        previous_state: MainlineState | str | None = None,
    ) -> dict[str, Any]:
        values = {name: finite_number(inputs.get(name)) for name in self.REQUIRED_INPUTS}
        missing = [name for name, value in values.items() if value is None]
        confidence = (len(values) - len(missing)) / len(values)
        if confidence < 0.375:
            state = MainlineState.SEMI_DORMANT
            reason = "insufficient real evidence; state is downgraded to observation"
            status = DataStatus.MISSING
        else:
            score = {key: clamp(value) if value is not None else 0.5 for key, value in values.items()}
            state, reason = self._classify(score)
            status = DataStatus.OK if not missing else DataStatus.PARTIAL

        previous = MainlineState(previous_state) if previous_state else None
        action = ACTION_BY_STATE[state]
        evidence = [f"{name}={value:.3f}" for name, value in values.items() if value is not None]
        return ComponentResult(
            status=status,
            as_of=as_of,
            confidence=confidence,
            evidence=evidence,
            missing_evidence=missing,
            data_sources=list(inputs.get("data_sources", [])),
            payload={
                "state": state.value,
                "previous_state": previous.value if previous else None,
                "state_transition_reason": reason,
                "state_changed": previous is not None and previous != state,
                "preferred_instrument": PREFERRED_INSTRUMENT[action],
                "recommended_action_bias": action,
                "research_only": True,
            },
        ).to_dict()

    @staticmethod
    def _classify(score: Mapping[str, float]) -> tuple[MainlineState, str]:
        rs = score["relative_strength"]
        volume = score["etf_volume_strength"]
        anchor = score["anchor_support"]
        breadth = score["subsector_breadth"]
        policy = score["policy_support"]
        distribution = score["distribution_risk"]
        drawdown = score["drawdown_pressure"]
        liquidity = score["liquidity_support"]

        if rs < 0.22 and drawdown > 0.72 and distribution > 0.60:
            return MainlineState.SEMI_FAILURE, "relative strength broke while drawdown and distribution risk are high"
        if distribution > 0.76 and (rs < 0.58 or volume > 0.75):
            return MainlineState.SEMI_DISTRIBUTION, "high distribution risk with weakening or stalled relative strength"
        if drawdown > 0.68 and rs < 0.42:
            return MainlineState.SEMI_RETREAT, "drawdown pressure is high and relative strength is weak"
        if policy > 0.68 and anchor > 0.55 and rs >= 0.42:
            return MainlineState.SEMI_POLICY_RESCUE, "policy-support proxy and technology anchors confirm rescue behavior"
        if rs > 0.75 and distribution > 0.55:
            return MainlineState.SEMI_HIGH_DIVERGENCE, "strong trend coexists with elevated distribution divergence"
        if rs > 0.82 and volume > 0.72 and breadth > 0.68 and liquidity > 0.55:
            return MainlineState.SEMI_ACCELERATION, "relative strength, ETF volume and subsector breadth are accelerating"
        if rs > 0.66 and volume > 0.58 and anchor > 0.58 and breadth > 0.55:
            return MainlineState.SEMI_MAINLINE_CONFIRM, "multiple independent mainline confirmations are present"
        if rs > 0.56 and (volume > 0.54 or anchor > 0.57):
            return MainlineState.SEMI_MAINLINE_START, "relative strength leads with initial volume or anchor confirmation"
        if rs > 0.52 and breadth < 0.46 and anchor > 0.50:
            return MainlineState.SEMI_ROTATION_INTERNAL, "mainline holds but strength is rotating across subsectors"
        if drawdown > 0.40 and rs > 0.50 and distribution < 0.50:
            return MainlineState.SEMI_PULLBACK_HEALTHY, "pullback retains relative strength without distribution evidence"
        if policy > 0.52 or (anchor > 0.50 and volume > 0.48):
            return MainlineState.SEMI_POLICY_WARMUP, "support proxies are warming up before broad confirmation"
        return MainlineState.SEMI_DORMANT, "evidence does not confirm an active semiconductor mainline"
