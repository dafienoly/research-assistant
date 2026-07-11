"""Point-in-time Ridge/XGBoost ranking lab with purge, embargo and lifecycle gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import ndcg_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRanker

from .contracts import DataStatus, now_iso, sha256_payload


FEATURES = [
    "ret5",
    "ret20",
    "reversal5",
    "volatility20",
    "price_to_ma20",
    "volume_ratio20",
    "amount_log",
]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _rank_ic_by_date(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, Any]:
    scored = frame[["date", "forward_return"]].copy()
    scored["prediction"] = prediction
    daily = scored.groupby("date", sort=True).apply(
        lambda group: group["forward_return"].corr(group["prediction"], method="spearman"),
        include_groups=False,
    )
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "daily_rank_ic_mean": float(daily.mean()) if len(daily) else None,
        "daily_rank_ic_median": float(daily.median()) if len(daily) else None,
        "daily_rank_ic_positive_rate": float((daily > 0).mean()) if len(daily) else None,
        "rank_ic_days": int(len(daily)),
        "global_rank_ic": float(scored["forward_return"].corr(scored["prediction"], method="spearman")),
        "rmse": float(np.sqrt(np.mean(np.square(scored["forward_return"].to_numpy() - prediction)))),
    }


def _relevance_labels(frame: pd.DataFrame) -> np.ndarray:
    percentile = frame.groupby("date")["forward_return"].rank(pct=True, method="average")
    return np.minimum((percentile * 5).astype(int), 4).to_numpy()


def _group_sizes(frame: pd.DataFrame) -> list[int]:
    return frame.groupby("date", sort=False).size().astype(int).tolist()


class PointInTimeFeatureView:
    def load_sample(
        self,
        path: str | Path,
        *,
        as_of: str,
        sample_modulus: int = 32,
        max_rows: int = 250_000,
        chunksize: int = 250_000,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        source = Path(path)
        if sample_modulus < 1:
            raise ValueError("sample_modulus must be positive")
        selected: list[pd.DataFrame] = []
        scanned = 0
        required = ["date", "symbol", *FEATURES, "forward_return"]
        for chunk in pd.read_csv(source, usecols=required, chunksize=chunksize):
            scanned += len(chunk)
            chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
            chunk = chunk[chunk["date"] <= pd.Timestamp(as_of)].dropna(subset=required)
            identity = chunk["date"].dt.strftime("%Y%m%d") + ":" + chunk["symbol"].astype(str)
            hashes = pd.util.hash_pandas_object(identity, index=False).astype("uint64")
            chunk = chunk.loc[(hashes % sample_modulus) == 0].copy()
            if not chunk.empty:
                chunk["__sample_hash__"] = hashes.loc[chunk.index].to_numpy()
                selected.append(chunk)
        if not selected:
            raise ValueError("point-in-time sample is empty")
        frame = pd.concat(selected, ignore_index=True)
        frame = frame.sort_values(["__sample_hash__", "date", "symbol"]).head(max_rows)
        frame = frame.drop(columns="__sample_hash__").sort_values(["date", "symbol"]).reset_index(drop=True)
        manifest = {
            "source_path": str(source.resolve()),
            "source_sha256": _file_sha256(source),
            "source_bytes": source.stat().st_size,
            "scanned_rows": scanned,
            "sample_rows": len(frame),
            "sample_modulus": sample_modulus,
            "max_rows": max_rows,
            "date_min": frame["date"].min().date().isoformat(),
            "date_max": frame["date"].max().date().isoformat(),
            "symbols": int(frame["symbol"].nunique()),
            "features": FEATURES,
            "target": "forward_return_5d",
            "point_in_time": True,
            "feature_lookahead": False,
        }
        return frame, manifest


def purged_embargo_split(
    frame: pd.DataFrame,
    *,
    purge_days: int = 5,
    embargo_days: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    dates = pd.Index(sorted(frame["date"].dropna().unique()))
    if len(dates) < 80:
        raise ValueError("at least 80 unique dates are required")
    train_cut = int(len(dates) * 0.70)
    validation_cut = int(len(dates) * 0.85)
    train_dates = dates[:train_cut]
    validation_dates = dates[min(train_cut + purge_days, validation_cut):validation_cut]
    test_dates = dates[min(validation_cut + embargo_days, len(dates)):]
    if len(validation_dates) < 5 or len(test_dates) < 5:
        raise ValueError("purged split leaves insufficient validation/test dates")
    train = frame[frame["date"].isin(train_dates)].sort_values(["date", "symbol"])
    validation = frame[frame["date"].isin(validation_dates)].sort_values(["date", "symbol"])
    test = frame[frame["date"].isin(test_dates)].sort_values(["date", "symbol"])
    manifest = {
        "purge_trading_days": purge_days,
        "embargo_trading_days": embargo_days,
        "train": [train["date"].min().date().isoformat(), train["date"].max().date().isoformat()],
        "validation": [validation["date"].min().date().isoformat(), validation["date"].max().date().isoformat()],
        "test": [test["date"].min().date().isoformat(), test["date"].max().date().isoformat()],
        "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
    }
    return train, validation, test, manifest


class MLRankerGovernanceLab:
    def run(
        self,
        project_root: str | Path,
        *,
        as_of: str,
        output_path: str | Path,
        sample_modulus: int = 32,
        max_rows: int = 250_000,
        n_estimators: int = 120,
    ) -> dict[str, Any]:
        root = Path(project_root)
        training_path = root / "data" / "vnext" / "ml" / "training.csv"
        scoring_path = root / "data" / "vnext" / "ml" / f"scoring_{as_of}.csv"
        audit = json.loads((root / "artifacts" / "vnext" / "data_audit_report.json").read_text(encoding="utf-8"))
        frame, feature_manifest = PointInTimeFeatureView().load_sample(
            training_path,
            as_of=as_of,
            sample_modulus=sample_modulus,
            max_rows=max_rows,
        )
        train, validation, test, split_manifest = purged_embargo_split(frame)
        ridge = Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=1.0))])
        ridge.fit(train[FEATURES], train["forward_return"])
        ridge_prediction = ridge.predict(test[FEATURES])
        ridge_oos = _rank_ic_by_date(test, ridge_prediction)

        ranker = XGBRanker(
            objective="rank:ndcg",
            eval_metric="ndcg@10",
            n_estimators=n_estimators,
            learning_rate=0.05,
            max_depth=5,
            min_child_weight=10,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            tree_method="hist",
            random_state=42,
            n_jobs=4,
        )
        train_label = _relevance_labels(train)
        validation_label = _relevance_labels(validation)
        ranker.fit(
            train[FEATURES],
            train_label,
            group=_group_sizes(train),
            eval_set=[(validation[FEATURES], validation_label)],
            eval_group=[_group_sizes(validation)],
            verbose=False,
        )
        xgb_prediction = ranker.predict(test[FEATURES])
        xgb_oos = _rank_ic_by_date(test, xgb_prediction)
        ndcg_values = []
        scored_test = test[["date", "forward_return"]].copy()
        scored_test["prediction"] = xgb_prediction
        for _, group in scored_test.groupby("date", sort=True):
            if len(group) >= 2:
                true_relevance = group["forward_return"].rank(pct=True).to_numpy()[None, :]
                ndcg_values.append(float(ndcg_score(true_relevance, group["prediction"].to_numpy()[None, :], k=10)))
        xgb_oos["ndcg_at_10_mean"] = float(np.mean(ndcg_values)) if ndcg_values else None

        model_identity = {
            "as_of": as_of,
            "sample": feature_manifest["source_sha256"],
            "split": split_manifest,
            "features": FEATURES,
            "estimators": n_estimators,
        }
        signature = sha256_payload(model_identity)[:16]
        model_dir = root / "data" / "vnext" / "ml" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        ridge_path = model_dir / f"ridge-pit-{as_of}-{signature}.joblib"
        ridge_tmp = ridge_path.with_suffix(".joblib.tmp")
        joblib.dump(ridge, ridge_tmp)
        ridge_tmp.replace(ridge_path)
        xgb_path = model_dir / f"xgboost-ranker-{as_of}-{signature}.json"
        # XGBoost chooses its serialization format from the final suffix.  Keep
        # ``.json`` last while writing atomically so the payload is genuinely
        # JSON rather than UBJSON stored under a misleading filename.
        xgb_tmp = xgb_path.with_name(f".{xgb_path.stem}.tmp.json")
        ranker.save_model(xgb_tmp)
        xgb_tmp.replace(xgb_path)

        scoring = pd.read_csv(scoring_path).dropna(subset=FEATURES)
        scoring_prediction = ranker.predict(scoring[FEATURES])
        scoring_output = pd.DataFrame(
            {
                "date": scoring["date"],
                "symbol": scoring["symbol"],
                "score": scoring_prediction,
            }
        )
        scoring_output["rank"] = scoring_output["score"].rank(ascending=False, method="min").astype(int)
        scoring_output["confidence"] = min(
            1.0,
            max(0.0, abs(float(xgb_oos.get("daily_rank_ic_mean") or 0)) / 0.05),
        )
        scoring_output["model_version"] = f"xgboost-ranker-{as_of}-{signature}"
        scoring_output["research_output_only"] = True
        scoring_output = scoring_output.sort_values("rank")
        scores_path = root / "data" / "vnext" / "ml" / f"xgboost_scores_{as_of}.csv"
        scores_tmp = scores_path.with_suffix(".csv.tmp")
        scoring_output.to_csv(scores_tmp, index=False, encoding="utf-8-sig")
        scores_tmp.replace(scores_path)

        ridge_ic = float(ridge_oos.get("daily_rank_ic_mean") or 0)
        xgb_ic = float(xgb_oos.get("daily_rank_ic_mean") or 0)
        statistical_candidate = xgb_ic >= 0.01 and xgb_ic > ridge_ic
        data_gate = audit.get("status") == DataStatus.OK.value
        promotion = statistical_candidate and data_gate
        lifecycle = "CHAMPION_CANDIDATE" if promotion else "WATCH"
        risk_warning = []
        if not statistical_candidate:
            risk_warning.append("xgboost_oos_rank_ic_does_not_clear_promotion_threshold_or_baseline")
        if not data_gate:
            risk_warning.append("data_audit_not_ok")
        importances = {
            feature: round(float(value), 8)
            for feature, value in zip(FEATURES, ranker.feature_importances_, strict=True)
        }
        registry_entry = {
            "model_version": f"xgboost-ranker-{as_of}-{signature}",
            "model_type": "XGBRanker",
            "lifecycle": lifecycle,
            "promotion_eligible": promotion,
            "retirement_rule": "RETIRE if rolling OOS RankIC <= 0 for 3 reviews or data lineage invalidates",
            "downgrade_rule": "DOWNGRADE when OOS RankIC decays below 0.01 or regime applicability breaks",
            "training_window": split_manifest["train"],
            "validation_window": split_manifest["validation"],
            "test_window": split_manifest["test"],
            "oos_score": xgb_oos,
            "baseline_oos_score": ridge_oos,
            "feature_importance": importances,
            "explanation_method": "xgboost_gain_importance_no_shap_dependency",
            "model_artifact": {"path": str(xgb_path), "sha256": _file_sha256(xgb_path)},
            "baseline_artifact": {"path": str(ridge_path), "sha256": _file_sha256(ridge_path)},
            "risk_warning": risk_warning,
            "direct_buy_sell_output": False,
            "order_output": False,
            "generated_at": now_iso(),
        }
        registry_path = root / "data" / "vnext" / "ml" / "model_registry_vnext.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {"models": []}
        registry["models"] = [
            model for model in registry.get("models", []) if model.get("model_version") != registry_entry["model_version"]
        ] + [registry_entry]
        _atomic_json(registry_path, registry)
        result = {
            "schema_version": "1.0",
            "status": DataStatus.OK.value if promotion else DataStatus.PARTIAL.value,
            "as_of": as_of,
            "feature_view": feature_manifest,
            "split": split_manifest,
            "baseline": {"model_type": "Ridge", "oos_score": ridge_oos},
            "ranker": registry_entry,
            "scoring": {
                "rows": len(scoring_output),
                "scores_path": str(scores_path),
                "scores_sha256": _file_sha256(scores_path),
                "top_100": scoring_output.head(100).to_dict(orient="records"),
            },
            "data_audit_status": audit.get("status"),
            "promotion_status": "PROMOTED" if promotion else "BLOCKED",
            "model_output_fields": [
                "score",
                "rank",
                "confidence",
                "feature_attribution",
                "regime_applicability",
                "model_version",
                "training_window",
                "OOS_score",
                "risk_warning",
            ],
            "direct_buy_sell_output": False,
            "order_output": False,
            "real_broker_called": False,
            "generated_at": now_iso(),
        }
        result["run_hash"] = sha256_payload({key: value for key, value in result.items() if key != "generated_at"})
        _atomic_json(Path(output_path), result)
        return result
