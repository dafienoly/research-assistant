"""Multi-asset portfolio diagnostics and false-diversification detection."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .contracts import ComponentResult, DataStatus, clamp


def _normalise_weights(weights: Mapping[str, float], columns: list[str]) -> pd.Series:
    series = pd.Series({name: float(weights.get(name, 0.0)) for name in columns}, dtype="float64")
    series = series.clip(lower=0)
    total = float(series.sum())
    if total <= 0:
        raise ValueError("portfolio weights must contain a positive allocation")
    return series / total


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return abs(float(drawdown.min()))


def _annualised_sharpe(returns: pd.Series, risk_free_rate: float = 0.0) -> float | None:
    clean = returns.dropna()
    if len(clean) < 2:
        return None
    volatility = float(clean.std(ddof=1))
    if volatility <= 1e-12:
        return None
    return float((clean.mean() - risk_free_rate / 252.0) / volatility * np.sqrt(252.0))


def _drawdown_overlap(returns: pd.DataFrame) -> pd.DataFrame:
    equity = (1 + returns.fillna(0)).cumprod()
    underwater = equity.lt(equity.cummax())
    result = pd.DataFrame(index=returns.columns, columns=returns.columns, dtype=float)
    for left in returns.columns:
        for right in returns.columns:
            union = underwater[left] | underwater[right]
            result.loc[left, right] = (
                float((underwater[left] & underwater[right]).sum() / union.sum()) if union.sum() else 0.0
            )
    return result


class PortfolioRiskAnalyzer:
    """Compute risk contribution, correlations and diversification truthfulness."""

    def analyze(
        self,
        returns: pd.DataFrame,
        weights: Mapping[str, float],
        *,
        as_of: str,
        exposures: Mapping[str, Mapping[str, float]] | None = None,
        source: str = "",
    ) -> dict[str, Any]:
        clean = returns.copy().replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all")
        if clean.empty or len(clean) < 5:
            return ComponentResult(
                status=DataStatus.MISSING,
                as_of=as_of,
                confidence=0.0,
                missing_evidence=["multi_asset_return_history"],
                data_sources=[source] if source else [],
                payload={"false_diversification_warning": None},
            ).to_dict()
        columns = [column for column in clean.columns if float(weights.get(column, 0)) > 0]
        if not columns:
            raise ValueError("none of the weighted assets exist in the returns table")
        clean = clean[columns]
        weight = _normalise_weights(weights, columns)
        aligned = clean.fillna(0.0)
        portfolio_returns = aligned.mul(weight, axis=1).sum(axis=1)

        correlation: dict[str, Any] = {}
        for window in (20, 60, 120):
            sample = aligned.tail(window)
            correlation[str(window)] = sample.corr().round(4).where(lambda frame: frame.notna(), None).to_dict()
        downside = aligned.loc[portfolio_returns < 0]
        downside_corr = downside.corr().round(4) if len(downside) >= 3 else pd.DataFrame(index=columns, columns=columns)
        overlap = _drawdown_overlap(aligned)

        covariance = aligned.cov() * 252.0
        portfolio_variance = float(weight.values @ covariance.values @ weight.values)
        portfolio_volatility = float(np.sqrt(max(portfolio_variance, 0.0)))
        component_risk = covariance.values @ weight.values
        if portfolio_volatility > 1e-12:
            marginal_vol = component_risk / portfolio_volatility
            risk_contrib = weight.values * marginal_vol / portfolio_volatility
        else:
            marginal_vol = np.zeros(len(columns))
            risk_contrib = np.zeros(len(columns))

        sharpe = _annualised_sharpe(portfolio_returns)
        max_drawdown = _max_drawdown(portfolio_returns)
        marginal_sharpe: dict[str, float | None] = {}
        marginal_drawdown: dict[str, float] = {}
        epsilon = 0.01
        for asset in columns:
            bumped = weight.copy()
            bumped.loc[asset] += epsilon
            bumped /= bumped.sum()
            bumped_returns = aligned.mul(bumped, axis=1).sum(axis=1)
            bumped_sharpe = _annualised_sharpe(bumped_returns)
            marginal_sharpe[asset] = (
                round((bumped_sharpe - sharpe) / epsilon, 6)
                if bumped_sharpe is not None and sharpe is not None
                else None
            )
            marginal_drawdown[asset] = round((_max_drawdown(bumped_returns) - max_drawdown) / epsilon, 6)

        corr60 = aligned.tail(60).corr().abs()
        upper = corr60.where(np.triu(np.ones(corr60.shape), k=1).astype(bool)).stack()
        average_abs_corr = float(upper.mean()) if not upper.empty else 0.0
        hhi = float((weight**2).sum())
        effective_assets = 1.0 / hhi if hhi > 0 else 0.0
        high_corr_pairs = [
            {"left": left, "right": right, "abs_correlation": round(float(value), 4)}
            for (left, right), value in upper.items()
            if value >= 0.75
        ]

        exposure_map = exposures or {}
        tech_beta = sum(weight.get(asset, 0.0) * float(exposure_map.get(asset, {}).get("technology_beta", 0.0)) for asset in columns)
        semi_beta = sum(weight.get(asset, 0.0) * float(exposure_map.get(asset, {}).get("semiconductor_beta", 0.0)) for asset in columns)
        theme_concentration = max(tech_beta, semi_beta)
        false_diversification = bool(
            average_abs_corr >= 0.72
            or theme_concentration >= 0.72
            or (len(columns) >= 4 and effective_assets < 2.5)
        )
        concentration_score = clamp(0.45 * hhi + 0.30 * average_abs_corr + 0.25 * theme_concentration)
        diversification_score = clamp(1.0 - concentration_score)
        missing = []
        if len(aligned) < 120:
            missing.append("rolling_120d_history")
        if not exposure_map:
            missing.append("asset_beta_exposures")
        availability = float(aligned.notna().sum().sum() / aligned.size)
        confidence = availability * (0.8 if missing else 1.0)
        status = DataStatus.OK if not missing else DataStatus.PARTIAL
        return ComponentResult(
            status=status,
            as_of=as_of,
            confidence=confidence,
            evidence=[
                f"assets={len(columns)}",
                f"observations={len(aligned)}",
                f"average_abs_corr_60d={average_abs_corr:.4f}",
            ],
            missing_evidence=missing,
            data_sources=[source] if source else [],
            payload={
                "weights": {key: round(float(value), 6) for key, value in weight.items()},
                "rolling_correlation": correlation,
                "downside_correlation": downside_corr.where(downside_corr.notna(), None).to_dict(),
                "drawdown_overlap": overlap.round(4).to_dict(),
                "portfolio_volatility": round(portfolio_volatility, 6),
                "portfolio_sharpe": round(sharpe, 6) if sharpe is not None else None,
                "max_drawdown": round(max_drawdown, 6),
                "risk_contribution": {asset: round(float(risk_contrib[i]), 6) for i, asset in enumerate(columns)},
                "marginal_volatility": {asset: round(float(marginal_vol[i]), 6) for i, asset in enumerate(columns)},
                "marginal_sharpe_contribution": marginal_sharpe,
                "marginal_drawdown_contribution": marginal_drawdown,
                "risk_concentration_score": round(concentration_score, 6),
                "diversification_score": round(diversification_score, 6),
                "effective_asset_count": round(effective_assets, 4),
                "technology_beta_exposure": round(tech_beta, 6),
                "semiconductor_beta_exposure": round(semi_beta, 6),
                "false_diversification_warning": false_diversification,
                "high_correlation_pairs": high_corr_pairs,
            },
        ).to_dict()

    def candidate_impact(
        self,
        returns: pd.DataFrame,
        weights: Mapping[str, float],
        candidate: str,
        *,
        candidate_weight: float = 0.05,
    ) -> dict[str, Any]:
        if candidate not in returns.columns:
            return {"status": DataStatus.MISSING.value, "candidate": candidate, "reason": "candidate returns missing"}
        existing = [name for name in returns.columns if name in weights and name != candidate]
        if not existing:
            return {"status": DataStatus.MISSING.value, "candidate": candidate, "reason": "base portfolio missing"}
        base_weight = _normalise_weights(weights, existing)
        base_returns = returns[existing].fillna(0).mul(base_weight, axis=1).sum(axis=1)
        scaled = base_weight * (1.0 - candidate_weight)
        new_returns = returns[existing].fillna(0).mul(scaled, axis=1).sum(axis=1) + returns[candidate].fillna(0) * candidate_weight
        base_sharpe = _annualised_sharpe(base_returns)
        new_sharpe = _annualised_sharpe(new_returns)
        return {
            "status": DataStatus.OK.value,
            "candidate": candidate,
            "candidate_weight": candidate_weight,
            "base_sharpe": base_sharpe,
            "new_sharpe": new_sharpe,
            "marginal_sharpe": (new_sharpe - base_sharpe) if new_sharpe is not None and base_sharpe is not None else None,
            "base_max_drawdown": _max_drawdown(base_returns),
            "new_max_drawdown": _max_drawdown(new_returns),
        }
