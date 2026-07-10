"""Interpretable ML factor selection and cross-sectional scoring.

Models produce scores, ranks and uncertainty only.  This module has no order or
broker dependency, which makes it impossible for a model prediction to bypass
portfolio, risk or approval gates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .contracts import DataStatus, now_iso


def _rank_ic(y_true: Sequence[float], y_pred: Sequence[float]) -> float | None:
    left = pd.Series(y_true, dtype="float64")
    right = pd.Series(y_pred, dtype="float64")
    value = left.corr(right, method="spearman")
    return None if pd.isna(value) else float(value)


class MLFactorSelector:
    """Select factors by cross-sectional RankIC and redundancy control."""

    def select(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        *,
        min_abs_rank_ic: float = 0.02,
        max_pair_correlation: float = 0.85,
    ) -> dict[str, Any]:
        aligned = features.join(target.rename("__target__"), how="inner")
        scores: list[dict[str, Any]] = []
        for feature in features.columns:
            pair = aligned[[feature, "__target__"]].dropna()
            ic = _rank_ic(pair["__target__"], pair[feature]) if len(pair) >= 20 else None
            scores.append({"factor": feature, "rank_ic": ic, "observations": len(pair)})
        eligible = [item for item in scores if item["rank_ic"] is not None and abs(item["rank_ic"]) >= min_abs_rank_ic]
        eligible.sort(key=lambda item: abs(item["rank_ic"]), reverse=True)
        selected: list[str] = []
        correlations = features.corr(method="spearman", min_periods=20).abs()
        rejected: list[dict[str, str]] = []
        for item in eligible:
            factor = item["factor"]
            conflict = next(
                (existing for existing in selected if correlations.get(existing, pd.Series()).get(factor, 0.0) > max_pair_correlation),
                None,
            )
            if conflict:
                rejected.append({"factor": factor, "reason": f"redundant_with:{conflict}"})
            else:
                selected.append(factor)
        return {
            "status": DataStatus.OK.value if selected else DataStatus.PARTIAL.value,
            "selected_factors": selected,
            "factor_metrics": scores,
            "rejected": rejected,
            "selection_policy": {
                "min_abs_rank_ic": min_abs_rank_ic,
                "max_pair_correlation": max_pair_correlation,
            },
            "updated_at": now_iso(),
        }


@dataclass(slots=True)
class TrainedRanker:
    model: Any
    feature_names: list[str]
    model_type: str
    model_version: str
    training_window: dict[str, str]
    oos_score: dict[str, float | None]
    feature_attribution: dict[str, float]


class CrossSectionalRanker:
    """Time-split Ridge/ElasticNet baseline for cross-sectional return ranking."""

    SUPPORTED_MODELS = {
        "ridge": "available",
        "elasticnet": "available",
        "random_forest": "optional",
        "xgboost_ranker": "optional_dependency",
        "lightgbm_ranker": "optional_dependency",
        "catboost_ranker": "optional_dependency",
        "mlp": "optional",
        "sequence_representation": "reserved_not_live",
    }
    MIN_PROMOTION_ABS_RANK_IC = 0.01
    STRONG_ABS_RANK_IC = 0.05

    def __init__(self, model_type: str = "ridge", random_state: int = 42) -> None:
        self.model_type = model_type
        self.random_state = random_state
        self.trained: TrainedRanker | None = None

    def _build_model(self) -> Any:
        try:
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.linear_model import ElasticNet, Ridge
            from sklearn.neural_network import MLPRegressor
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:
            raise RuntimeError("scikit-learn is required for the VNext ranker") from exc
        if self.model_type == "ridge":
            estimator = Ridge(alpha=1.0)
        elif self.model_type == "elasticnet":
            estimator = ElasticNet(alpha=0.001, l1_ratio=0.25, max_iter=5000, random_state=self.random_state)
        elif self.model_type == "random_forest":
            return RandomForestRegressor(
                n_estimators=200,
                max_depth=6,
                min_samples_leaf=10,
                random_state=self.random_state,
                n_jobs=-1,
            )
        elif self.model_type == "mlp":
            estimator = MLPRegressor(
                hidden_layer_sizes=(32, 16),
                alpha=0.01,
                early_stopping=True,
                max_iter=500,
                random_state=self.random_state,
            )
        else:
            raise ValueError(f"unsupported or unavailable model_type: {self.model_type}")
        return Pipeline([("scale", StandardScaler()), ("model", estimator)])

    def fit(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        dates: pd.Series,
        *,
        validation_fraction: float = 0.2,
    ) -> dict[str, Any]:
        if not 0.1 <= validation_fraction <= 0.5:
            raise ValueError("validation_fraction must be in [0.1, 0.5]")
        frame = features.copy()
        frame["__target__"] = target
        frame["__date__"] = pd.to_datetime(dates)
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
        if len(frame) < 50:
            raise ValueError("at least 50 real observations are required")
        frame = frame.sort_values("__date__")
        split = max(1, int(len(frame) * (1 - validation_fraction)))
        train = frame.iloc[:split]
        valid = frame.iloc[split:]
        feature_names = list(features.columns)
        model = self._build_model()
        model.fit(train[feature_names], train["__target__"])
        predicted = model.predict(valid[feature_names])
        rmse = float(np.sqrt(np.mean((valid["__target__"].to_numpy() - predicted) ** 2)))
        rank_ic = _rank_ic(valid["__target__"], predicted)
        attribution = self._feature_attribution(model, feature_names)
        signature = hashlib.sha256(
            json.dumps(
                {
                    "model": self.model_type,
                    "features": feature_names,
                    "start": str(train["__date__"].min()),
                    "end": str(train["__date__"].max()),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        version = f"{self.model_type}-{datetime.now(UTC).strftime('%Y%m%d')}-{signature}"
        self.trained = TrainedRanker(
            model=model,
            feature_names=feature_names,
            model_type=self.model_type,
            model_version=version,
            training_window={
                "start": train["__date__"].min().date().isoformat(),
                "end": train["__date__"].max().date().isoformat(),
                "validation_start": valid["__date__"].min().date().isoformat(),
                "validation_end": valid["__date__"].max().date().isoformat(),
            },
            oos_score={"rank_ic": rank_ic, "rmse": rmse},
            feature_attribution=attribution,
        )
        return self.model_card()

    @staticmethod
    def _feature_attribution(model: Any, feature_names: list[str]) -> dict[str, float]:
        estimator = model.named_steps["model"] if hasattr(model, "named_steps") else model
        values = getattr(estimator, "coef_", None)
        if values is None:
            values = getattr(estimator, "feature_importances_", None)
        if values is None:
            return {name: 0.0 for name in feature_names}
        array = np.asarray(values).reshape(-1)
        denominator = float(np.abs(array).sum()) or 1.0
        return {name: round(float(array[index] / denominator), 6) for index, name in enumerate(feature_names)}

    def score(
        self,
        features: pd.DataFrame,
        *,
        symbols: Sequence[str] | None = None,
        regime_applicability: Sequence[float] | None = None,
    ) -> list[dict[str, Any]]:
        if self.trained is None:
            raise RuntimeError("ranker is not trained")
        missing = sorted(set(self.trained.feature_names) - set(features.columns))
        if missing:
            raise ValueError(f"missing model features: {missing}")
        matrix = features[self.trained.feature_names].replace([np.inf, -np.inf], np.nan)
        valid = matrix.notna().all(axis=1)
        scores = pd.Series(np.nan, index=features.index, dtype=float)
        scores.loc[valid] = self.trained.model.predict(matrix.loc[valid])
        ranks = scores.rank(ascending=False, method="min", na_option="bottom")
        symbol_values = list(symbols) if symbols is not None else [str(index) for index in features.index]
        applicability = list(regime_applicability) if regime_applicability is not None else [1.0] * len(features)
        governance = self._governance()
        confidence_base = float(governance["confidence"])
        output: list[dict[str, Any]] = []
        for position, (_, row) in enumerate(features.iterrows()):
            prediction = scores.iloc[position]
            attr = {
                feature: round(float(row.get(feature, np.nan)) * weight, 6)
                if pd.notna(row.get(feature, np.nan))
                else None
                for feature, weight in self.trained.feature_attribution.items()
            }
            output.append(
                {
                    "symbol": symbol_values[position],
                    "candidate_score": None if pd.isna(prediction) else round(float(prediction), 8),
                    "rank": None if pd.isna(prediction) else int(ranks.iloc[position]),
                    "confidence": round(confidence_base * max(0.0, min(1.0, float(applicability[position]))), 4),
                    "feature_attribution": attr,
                    "regime_applicability": float(applicability[position]),
                    "model_version": self.trained.model_version,
                    "training_window": self.trained.training_window,
                    "oos_score": self.trained.oos_score,
                    "risk_warning": "missing_features" if not valid.iloc[position] else governance["risk_warning"],
                    "research_output_only": True,
                }
            )
        return output

    def _governance(self) -> dict[str, Any]:
        if self.trained is None:
            return {
                "status": DataStatus.MISSING.value,
                "confidence": 0.0,
                "model_uncertainty": 1.0,
                "promotion_eligible": False,
                "lifecycle_status": "WATCH",
                "risk_warning": "model_not_trained",
            }
        rank_ic = self.trained.oos_score.get("rank_ic")
        strength = abs(float(rank_ic)) if rank_ic is not None and np.isfinite(float(rank_ic)) else 0.0
        confidence = min(1.0, strength / self.STRONG_ABS_RANK_IC)
        eligible = strength >= self.MIN_PROMOTION_ABS_RANK_IC
        return {
            "status": DataStatus.OK.value if eligible else DataStatus.PARTIAL.value,
            "confidence": round(confidence, 4),
            "model_uncertainty": round(1.0 - confidence, 4),
            "promotion_eligible": eligible,
            "lifecycle_status": "CANDIDATE" if eligible else "WATCH",
            "risk_warning": None if eligible else "weak_oos_rank_ic_do_not_promote",
        }

    def model_card(self) -> dict[str, Any]:
        if self.trained is None:
            return {
                "status": DataStatus.MISSING.value,
                "model_type": self.model_type,
                "supported_models": self.SUPPORTED_MODELS,
                "reason": "model not trained",
            }
        governance = self._governance()
        return {
            **governance,
            "model_type": self.trained.model_type,
            "model_version": self.trained.model_version,
            "feature_names": self.trained.feature_names,
            "training_window": self.trained.training_window,
            "oos_score": self.trained.oos_score,
            "feature_importance_or_linear_attribution": self.trained.feature_attribution,
            "supported_models": self.SUPPORTED_MODELS,
            "direct_buy_sell_output": False,
            "updated_at": now_iso(),
        }

    def save_registry_entry(self, registry_path: str | Path) -> dict[str, Any]:
        if self.trained is None:
            raise RuntimeError("ranker is not trained")
        path = Path(registry_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"models": []}
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        card = self.model_card()
        payload.setdefault("models", [])
        payload["models"] = [model for model in payload["models"] if model.get("model_version") != card["model_version"]]
        payload["models"].append({**card, "lifecycle": str(card["lifecycle_status"]).lower()})
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return card

    def save_model(self, model_path: str | Path) -> dict[str, Any]:
        """Persist a locally trained model with a checksum for auditable scoring."""
        if self.trained is None:
            raise RuntimeError("ranker is not trained")
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("joblib is required to persist the VNext ranker") from exc
        path = Path(model_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        joblib.dump(self.trained, temporary)
        temporary.replace(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "model_path": str(path),
            "sha256": digest,
            "model_version": self.trained.model_version,
            "trusted_local_artifact_only": True,
        }

    @classmethod
    def load_model(cls, model_path: str | Path, *, expected_sha256: str | None = None) -> "CrossSectionalRanker":
        """Load only an explicitly selected local artifact and optionally verify its hash."""
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("joblib is required to load the VNext ranker") from exc
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"model artifact missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_sha256 and digest != expected_sha256:
            raise ValueError("model artifact checksum mismatch")
        trained = joblib.load(path)
        if not isinstance(trained, TrainedRanker):
            raise TypeError("model artifact does not contain a TrainedRanker")
        instance = cls(trained.model_type)
        instance.trained = trained
        return instance
