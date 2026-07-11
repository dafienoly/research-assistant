"""Accumulate realized regime/style labels and continuous Paper/Shadow equity evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class RealizedObservationCollector:
    def run(self, project_root: str | Path, as_of: str) -> dict:
        root = Path(project_root).resolve()
        output_root = root / "data/vnext/realized"
        output_root.mkdir(parents=True, exist_ok=True)
        domain = self._read(root / "artifacts/vnext/domain_decision.json")
        forecast = {
            "as_of": as_of,
            "regime_forecast": domain.get("regime"),
            "semi_state_forecast": domain.get("state"),
            "style_rotation_forecast": domain.get("style_rotation"),
            "decision_hash": domain.get("decision_hash"),
            "recorded_at": datetime.now().astimezone().isoformat(),
        }
        self._upsert_jsonl(output_root / "forecasts.jsonl", forecast, "as_of")
        curves = {}
        for mode in ("paper", "shadow"):
            artifact = self._read(root / f"data/vnext/{mode}/latest.json")
            observation = self._equity_observation(artifact)
            if observation:
                observation.update({"as_of": as_of, "mode": mode.upper()})
                self._upsert_jsonl(output_root / f"{mode}_equity.jsonl", observation, "as_of")
                curves[mode] = "RECORDED"
            else:
                curves[mode] = "MISSING_REAL_EQUITY"
        result = {
            "status": "PARTIAL",
            "as_of": as_of,
            "forecast_recorded": True,
            "realized_label_status": "PENDING_NEXT_OBSERVATION",
            "equity_curves": curves,
            "no_synthetic_equity": True,
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        (output_root / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    @staticmethod
    def _equity_observation(artifact: dict) -> dict | None:
        for key in ("ending_equity", "account_equity", "equity"):
            value = artifact.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return {"equity": float(value), "source_field": key, "source_updated_at": artifact.get("updated_at")}
        return None

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _upsert_jsonl(path: Path, row: dict, key: str) -> None:
        existing = []
        if path.exists():
            existing = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        existing = [item for item in existing if item.get(key) != row.get(key)] + [row]
        path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing), encoding="utf-8")
