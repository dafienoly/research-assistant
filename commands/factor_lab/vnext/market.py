"""Policy-support proxy, index-box, breadth divergence and style rotation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .contracts import ComponentResult, DataStatus, clamp, finite_number


DEFAULT_INDEX_BOX = {
    "index": "SSE_OR_CSI_ALL_PROXY",
    "lower_bound": 3900.0,
    "policy_put_zone": 3950.0,
    "neutral_line": 4000.0,
    "upper_warning": 4050.0,
    "upper_risk": 4100.0,
    "upper_bound": 4200.0,
}


def _percentile_position(value: float, low: float, high: float) -> float | None:
    if high <= low:
        return None
    return clamp((value - low) / (high - low))


def compute_index_box(
    close_history: Sequence[float],
    *,
    current: float | None = None,
    fixed_box: Mapping[str, Any] | None = None,
    as_of: str = "",
    source: str = "",
) -> dict[str, Any]:
    values = pd.Series(close_history, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    fixed = {**DEFAULT_INDEX_BOX, **dict(fixed_box or {})}
    current_value = finite_number(current)
    if current_value is None and not values.empty:
        current_value = float(values.iloc[-1])
    if current_value is None:
        return ComponentResult(
            status=DataStatus.MISSING,
            as_of=as_of,
            confidence=0.0,
            missing_evidence=["index_close"],
            data_sources=[source] if source else [],
            payload={"fixed_box": fixed, "dynamic_box": None, "zone": "MISSING"},
        ).to_dict()

    def window_stat(window: int, fn: str) -> float | None:
        if len(values) < min(window, 20):
            return None
        sample = values.iloc[-window:]
        return float(sample.min() if fn == "low" else sample.max())

    low60 = window_stat(60, "low")
    high60 = window_stat(60, "high")
    low120 = window_stat(120, "low")
    high120 = window_stat(120, "high")
    q20 = float(values.iloc[-120:].quantile(0.2)) if len(values) >= 20 else None
    q80 = float(values.iloc[-120:].quantile(0.8)) if len(values) >= 20 else None
    dynamic_low_candidates = [x for x in (low60, low120, q20) if x is not None]
    dynamic_high_candidates = [x for x in (high60, high120, q80) if x is not None]
    dynamic_low = float(np.median(dynamic_low_candidates)) if dynamic_low_candidates else None
    dynamic_high = float(np.median(dynamic_high_candidates)) if dynamic_high_candidates else None

    fixed_position = _percentile_position(current_value, float(fixed["lower_bound"]), float(fixed["upper_bound"]))
    dynamic_position = (
        _percentile_position(current_value, dynamic_low, dynamic_high)
        if dynamic_low is not None and dynamic_high is not None
        else None
    )

    if current_value < float(fixed["lower_bound"]):
        zone = "BREAK_BOX_RISK"
    elif current_value <= float(fixed["policy_put_zone"]):
        zone = "POLICY_SUPPORT_ZONE"
    elif current_value >= float(fixed["upper_risk"]):
        zone = "UPPER_RISK_ZONE"
    elif current_value >= float(fixed["upper_warning"]):
        zone = "UPPER_WARNING_ZONE"
    else:
        zone = "NEUTRAL_ZONE"

    missing = []
    if dynamic_position is None:
        missing.append("rolling_60d_120d_history")
    confidence = 1.0 if not missing else 0.55
    status = DataStatus.OK if not missing else DataStatus.PARTIAL
    return ComponentResult(
        status=status,
        as_of=as_of,
        confidence=confidence,
        evidence=[f"index_close={current_value:.4f}", f"fixed_zone={zone}"],
        missing_evidence=missing,
        data_sources=[source] if source else [],
        payload={
            "index": fixed["index"],
            "current": current_value,
            "zone": zone,
            "fixed_box": fixed,
            "fixed_position": fixed_position,
            "dynamic_box": {
                "rolling_60d_low": low60,
                "rolling_120d_low": low120,
                "rolling_60d_high": high60,
                "rolling_120d_high": high120,
                "rolling_percentile_20": q20,
                "rolling_percentile_80": q80,
                "learned_lower": dynamic_low,
                "learned_upper": dynamic_high,
                "position": dynamic_position,
            },
            "threshold_comparison": {
                "fixed_hypothesis_is_assumption": True,
                "fixed_threshold_validation_required": True,
                "dynamic_available": dynamic_position is not None,
            },
        },
    ).to_dict()


def compute_breadth_divergence(
    *,
    advancing: Any,
    declining: Any,
    index_reversal_strength: Any,
    semiconductor_relative_strength: Any,
    large_cap_tech_support: Any,
) -> tuple[float | None, list[str], list[str]]:
    adv = finite_number(advancing)
    dec = finite_number(declining)
    reversal = finite_number(index_reversal_strength)
    semi = finite_number(semiconductor_relative_strength)
    anchor = finite_number(large_cap_tech_support)
    missing: list[str] = []
    if adv is None or dec is None or adv + dec <= 0:
        missing.append("market_breadth")
        distress = None
    else:
        distress = clamp(dec / (adv + dec))
    for name, value in (
        ("index_reversal_strength", reversal),
        ("semiconductor_relative_strength", semi),
        ("large_cap_tech_support", anchor),
    ):
        if value is None:
            missing.append(name)
    components = [
        (distress, 0.35),
        (reversal, 0.25),
        (semi, 0.25),
        (anchor, 0.15),
    ]
    usable = [(clamp(value), weight) for value, weight in components if value is not None]
    if not usable:
        return None, [], missing
    weight_sum = sum(weight for _, weight in usable)
    score = sum(value * weight for value, weight in usable) / weight_sum
    evidence = [f"breadth_distress={distress:.3f}" if distress is not None else ""]
    evidence.extend(
        f"{name}={value:.3f}"
        for name, value in (
            ("index_reversal_strength", reversal),
            ("semiconductor_relative_strength", semi),
            ("large_cap_tech_support", anchor),
        )
        if value is not None
    )
    return round(clamp(score), 4), [item for item in evidence if item], missing


def compute_policy_support_proxy(
    snapshot: Mapping[str, Any],
    index_box: Mapping[str, Any],
    *,
    as_of: str,
) -> dict[str, Any]:
    payload = index_box.get("payload", index_box)
    fixed_position = finite_number(payload.get("fixed_position"))
    zone = payload.get("zone", "MISSING")
    inputs = {
        "index_lower_proximity": (1.0 - fixed_position) if fixed_position is not None else None,
        "intraday_reversal_strength": finite_number(snapshot.get("intraday_reversal_strength")),
        "semiconductor_relative_strength": finite_number(snapshot.get("semiconductor_relative_strength")),
        "technology_relative_strength": finite_number(snapshot.get("technology_relative_strength")),
        "etf_abnormal_volume": finite_number(snapshot.get("etf_abnormal_volume")),
        "large_cap_tech_support": finite_number(snapshot.get("large_cap_tech_support")),
    }
    weights = {
        "index_lower_proximity": 0.20,
        "intraday_reversal_strength": 0.20,
        "semiconductor_relative_strength": 0.18,
        "technology_relative_strength": 0.12,
        "etf_abnormal_volume": 0.15,
        "large_cap_tech_support": 0.15,
    }
    usable = [(name, clamp(value), weights[name]) for name, value in inputs.items() if value is not None]
    missing = [name for name, value in inputs.items() if value is None]
    score = None
    if usable:
        total_weight = sum(weight for _, _, weight in usable)
        score = sum(value * weight for _, value, weight in usable) / total_weight

    breadth_score, breadth_evidence, breadth_missing = compute_breadth_divergence(
        advancing=snapshot.get("advancing"),
        declining=snapshot.get("declining"),
        index_reversal_strength=snapshot.get("intraday_reversal_strength"),
        semiconductor_relative_strength=snapshot.get("semiconductor_relative_strength"),
        large_cap_tech_support=snapshot.get("large_cap_tech_support"),
    )
    if breadth_score is not None and score is not None:
        score = 0.75 * score + 0.25 * breadth_score
    missing = sorted(set(missing + breadth_missing))
    source_count = len(inputs) + 1
    confidence = (source_count - len(missing)) / source_count
    status = DataStatus.MISSING if score is None else (DataStatus.OK if not missing else DataStatus.PARTIAL)

    upper_inputs = [
        fixed_position,
        finite_number(snapshot.get("technology_weakness")),
        finite_number(snapshot.get("etf_stall_volume")),
        finite_number(snapshot.get("style_rotation_away")),
    ]
    upper_available = [clamp(value) for value in upper_inputs if value is not None]
    upper_risk = sum(upper_available) / len(upper_available) if upper_available else None

    evidence = [f"index_zone={zone}"]
    evidence.extend(f"{name}={value:.3f}" for name, value, _ in usable)
    evidence.extend(breadth_evidence)
    return ComponentResult(
        status=status,
        as_of=as_of,
        confidence=confidence,
        evidence=evidence,
        missing_evidence=missing,
        data_sources=list(snapshot.get("data_sources", [])),
        payload={
            "policy_support_proxy_score": round(clamp(score), 4) if score is not None else None,
            "breadth_divergence_score": breadth_score,
            "upper_box_distribution_risk": round(clamp(upper_risk), 4) if upper_risk is not None else None,
            "index_box_position": fixed_position,
            "index_zone": zone,
            "assumption_warning": "proxy score is evidence-based; it is not a direct national-team variable",
        },
    ).to_dict()


def compute_style_rotation_matrix(
    returns: pd.DataFrame,
    *,
    as_of: str,
    source: str,
) -> dict[str, Any]:
    clean = returns.copy().replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all")
    if clean.empty or clean.shape[1] < 2:
        return ComponentResult(
            status=DataStatus.MISSING,
            as_of=as_of,
            confidence=0.0,
            missing_evidence=["multi_asset_returns"],
            data_sources=[source] if source else [],
            payload={"assets": [], "correlation": {}, "relative_strength": {}},
        ).to_dict()
    window = clean.tail(60)
    corr = window.corr(min_periods=max(5, min(20, len(window)))).round(4)
    cumulative = window.apply(
        lambda series: (1 + series.dropna()).prod() - 1 if series.notna().any() else np.nan
    ).dropna().sort_values(ascending=False)
    available_ratio = float(clean.notna().sum().sum() / clean.size)
    status = DataStatus.OK if available_ratio >= 0.9 else DataStatus.PARTIAL
    return ComponentResult(
        status=status,
        as_of=as_of,
        confidence=available_ratio,
        evidence=[f"assets={clean.shape[1]}", f"observations={len(window)}"],
        missing_evidence=[] if status == DataStatus.OK else ["partial_style_returns"],
        data_sources=[source] if source else [],
        payload={
            "assets": list(clean.columns),
            "correlation": corr.astype(object).where(pd.notna(corr), None).to_dict(),
            "relative_strength": {key: round(float(value), 6) for key, value in cumulative.items()},
            "style_rotation_score": round(float(cumulative.std(ddof=0)), 6),
            "leaders": list(cumulative.head(3).index),
            "laggards": list(cumulative.tail(3).index),
        },
    ).to_dict()
