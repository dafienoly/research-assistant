"""Constrained portfolio optimizers and false-diversification research lab."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .contracts import DataStatus, TargetPortfolioWeights, now_iso, sha256_payload
from .portfolio import PortfolioRiskAnalyzer


def _normalise_to_budget(seed: np.ndarray, budget: float, upper: np.ndarray) -> np.ndarray:
    weights = np.maximum(seed.astype(float), 0.0)
    if float(weights.sum()) <= 0:
        weights = (upper > 0).astype(float)
    weights = weights / max(float(weights.sum()), 1e-12) * budget
    for _ in range(20):
        over = weights > upper
        if not over.any():
            break
        excess = float((weights[over] - upper[over]).sum())
        weights[over] = upper[over]
        available = (~over) & (weights < upper - 1e-12)
        if not available.any():
            break
        room = upper[available] - weights[available]
        weights[available] += excess * room / room.sum()
    return weights


class PortfolioOptimizer:
    METHODS = (
        "constrained_equal_weight",
        "inverse_volatility",
        "risk_parity",
        "minimum_variance",
        "robust_max_sharpe",
        "cost_aware",
    )

    def optimize(
        self,
        returns: pd.DataFrame,
        *,
        method: str,
        invested_budget: float,
        upper_bounds: Mapping[str, float],
        current_weights: Mapping[str, float] | None = None,
        theme_exposures: Mapping[str, Mapping[str, float]] | None = None,
        theme_limits: Mapping[str, float] | None = None,
        turnover_penalty: float = 0.02,
    ) -> dict[str, Any]:
        if method not in self.METHODS:
            raise ValueError(f"unsupported optimization method: {method}")
        if not 0 < invested_budget <= 1:
            raise ValueError("invested_budget must be in (0, 1]")
        clean = returns.replace([np.inf, -np.inf], np.nan).dropna(how="all").fillna(0.0)
        if len(clean) < 20 or clean.shape[1] < 2:
            raise ValueError("at least 20 observations and 2 assets are required")
        assets = list(clean.columns)
        upper = np.array([max(0.0, min(1.0, float(upper_bounds.get(asset, 0.0)))) for asset in assets])
        if float(upper.sum()) + 1e-9 < invested_budget:
            raise ValueError("upper bounds cannot satisfy invested budget")
        current = np.array([float((current_weights or {}).get(asset, 0.0)) for asset in assets])
        covariance = clean.cov().to_numpy() * 252.0
        diagonal = np.diag(np.diag(covariance))
        robust_covariance = 0.7 * covariance + 0.3 * diagonal
        expected = clean.mean().to_numpy() * 252.0
        robust_expected = 0.5 * expected
        volatility = np.sqrt(np.maximum(np.diag(robust_covariance), 1e-12))
        if method == "inverse_volatility":
            seed = 1.0 / volatility
        else:
            seed = np.ones(len(assets))
        initial = _normalise_to_budget(seed, invested_budget, upper)
        exposures = theme_exposures or {}
        limits = theme_limits or {}
        constraints: list[dict[str, Any]] = [{"type": "eq", "fun": lambda weight: float(weight.sum() - invested_budget)}]
        for theme, limit in limits.items():
            vector = np.array([float(exposures.get(asset, {}).get(theme, 0.0)) for asset in assets])
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda weight, vector=vector, limit=float(limit): float(limit - vector @ weight),
                }
            )

        def portfolio_variance(weight: np.ndarray) -> float:
            return float(weight @ robust_covariance @ weight)

        risk_parity_target = initial.copy()
        active_mask = upper > 0
        for _ in range(500):
            variance = max(portfolio_variance(risk_parity_target), 1e-12)
            contributions = risk_parity_target * (robust_covariance @ risk_parity_target) / variance
            active_contributions = contributions[active_mask]
            desired = 1.0 / max(int(active_mask.sum()), 1)
            ratios = np.ones_like(risk_parity_target)
            ratios[active_mask] = np.sqrt(desired / np.maximum(active_contributions, 1e-10))
            updated = _normalise_to_budget(risk_parity_target * ratios, invested_budget, upper)
            if float(np.max(np.abs(updated - risk_parity_target))) < 1e-10:
                break
            risk_parity_target = updated

        def negative_robust_sharpe(weight: np.ndarray) -> float:
            variance = max(portfolio_variance(weight), 1e-12)
            return -float(robust_expected @ weight / np.sqrt(variance))

        def cost_aware_objective(weight: np.ndarray) -> float:
            smooth_turnover = np.sqrt(np.square(weight - current) + 1e-10).sum()
            return negative_robust_sharpe(weight) + turnover_penalty * float(smooth_turnover)

        def squared_distance(weight: np.ndarray, *, target: np.ndarray) -> float:
            return float(np.square(weight - target).sum())

        if method == "constrained_equal_weight":
            target = np.full(len(assets), invested_budget / len(assets))
            objective = partial(squared_distance, target=target)
        elif method == "inverse_volatility":
            target = _normalise_to_budget(1.0 / volatility, invested_budget, upper)
            objective = partial(squared_distance, target=target)
        elif method == "risk_parity":
            objective = partial(squared_distance, target=risk_parity_target)
        elif method == "minimum_variance":
            objective = portfolio_variance
        elif method == "robust_max_sharpe":
            objective = negative_robust_sharpe
        else:
            objective = cost_aware_objective

        result = minimize(
            objective,
            initial,
            method="SLSQP",
            bounds=[(0.0, float(value)) for value in upper],
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12},
        )
        weight = np.clip(result.x, 0.0, upper)
        if abs(float(weight.sum()) - invested_budget) > 1e-6:
            raise RuntimeError(f"optimizer violated invested budget: {weight.sum()}")
        theme_values = {
            theme: float(
                np.array([float(exposures.get(asset, {}).get(theme, 0.0)) for asset in assets]) @ weight
            )
            for theme in limits
        }
        violations = [theme for theme, value in theme_values.items() if value > float(limits[theme]) + 1e-6]
        if violations:
            raise RuntimeError(f"optimizer violated theme limits: {violations}")
        portfolio_returns = clean.mul(pd.Series(weight, index=assets), axis=1).sum(axis=1)
        annualized_vol = float(portfolio_returns.std(ddof=1) * np.sqrt(252))
        annualized_return = float(portfolio_returns.mean() * 252)
        return {
            "status": DataStatus.OK.value if result.success else DataStatus.PARTIAL.value,
            "method": method,
            "weights": {asset: round(float(weight[index]), 10) for index, asset in enumerate(assets)},
            "cash_weight": round(1.0 - float(weight.sum()), 10),
            "invested_budget": invested_budget,
            "objective_value": float(result.fun),
            "solver_success": bool(result.success),
            "solver_message": str(result.message),
            "iterations": int(getattr(result, "nit", 0)),
            "annualized_return_estimate": annualized_return,
            "annualized_volatility": annualized_vol,
            "sharpe_estimate": annualized_return / annualized_vol if annualized_vol > 1e-12 else None,
            "turnover": float(np.abs(weight - current).sum()),
            "theme_exposures": theme_values,
            "hard_constraints": {
                "sum_weights": round(float(weight.sum()), 10),
                "upper_bounds": {asset: float(upper[index]) for index, asset in enumerate(assets)},
                "theme_limits": dict(limits),
                "violations": [],
            },
        }


def _pca_diagnostics(returns: pd.DataFrame) -> dict[str, Any]:
    standardized = (returns - returns.mean()) / returns.std(ddof=1).replace(0, np.nan)
    clean = standardized.fillna(0.0)
    covariance = clean.cov().to_numpy()
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    values = values[order]
    vectors = vectors[:, order]
    total = max(float(values.sum()), 1e-12)
    market = returns.mean(axis=1)
    common_beta = {
        asset: float(returns[asset].cov(market) / max(market.var(), 1e-12))
        for asset in returns.columns
    }
    return {
        "explained_variance_ratio": [round(float(value / total), 6) for value in values],
        "first_component_share": round(float(values[0] / total), 6),
        "first_component_loadings": {
            asset: round(float(vectors[index, 0]), 6) for index, asset in enumerate(returns.columns)
        },
        "common_beta": {asset: round(value, 6) for asset, value in common_beta.items()},
    }


class PortfolioOptimizationLab:
    def run(self, project_root: str | Path, *, as_of: str, output_path: str | Path) -> dict[str, Any]:
        root = Path(project_root)
        snapshot = json.loads((root / "data" / "vnext" / "snapshot" / f"{as_of}.json").read_text(encoding="utf-8"))
        target = TargetPortfolioWeights.model_validate_json(
            (root / "artifacts" / "vnext" / "target_weights.json").read_text(encoding="utf-8")
        )
        series = {}
        for role, records in snapshot.get("style_returns", {}).items():
            values = {pd.Timestamp(row["date"]): float(row["return"]) for row in records if row.get("return") is not None}
            if values:
                series[role] = pd.Series(values, dtype=float)
        returns = pd.DataFrame(series).sort_index().dropna(how="all")
        role_by_symbol = target.constraints.get("role_by_symbol", {})
        symbol_by_role = {role: symbol for symbol, role in role_by_symbol.items()}
        target_by_role = {
            role: float(target.risk_adjusted_weights.get(symbol, 0.0))
            for role, symbol in symbol_by_role.items()
            if role in returns.columns
        }
        roles = [role for role in returns.columns if role in target_by_role]
        returns = returns[roles].fillna(0.0)
        invested = float(sum(target_by_role.values()))
        upper = {role: (0.0 if target_by_role.get(role, 0.0) == 0 else 0.35) for role in roles}
        exposures = snapshot.get("asset_exposures", {})
        optimizer = PortfolioOptimizer()
        methods = {}
        diagnostics = {}
        for method in PortfolioOptimizer.METHODS:
            result = optimizer.optimize(
                returns,
                method=method,
                invested_budget=invested,
                upper_bounds=upper,
                current_weights=target_by_role,
                theme_exposures=exposures,
                theme_limits={"technology_beta": 0.45, "semiconductor_beta": 0.25},
            )
            methods[method] = result
            diagnostics[method] = PortfolioRiskAnalyzer().analyze(
                returns,
                result["weights"],
                as_of=as_of,
                exposures=exposures,
                source=f"immutable_snapshot:{target.data_snapshot_id}",
            )
        payload = {
            "schema_version": "1.0",
            "status": DataStatus.OK.value if all(result["solver_success"] for result in methods.values()) else DataStatus.PARTIAL.value,
            "as_of": as_of,
            "data_snapshot_id": target.data_snapshot_id,
            "target_weights_hash": target.target_weights_hash,
            "invested_budget": invested,
            "cash_minimum": 1.0 - invested,
            "eligible_roles": roles,
            "methods": methods,
            "risk_diagnostics": diagnostics,
            "pca_common_beta": _pca_diagnostics(returns),
            "hard_constraints_enforced": True,
            "account_permissions_source": "TargetPortfolioWeights",
            "order_output": False,
            "real_broker_called": False,
            "generated_at": now_iso(),
        }
        payload["run_hash"] = sha256_payload({key: value for key, value in payload.items() if key != "generated_at"})
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(destination)
        return payload
