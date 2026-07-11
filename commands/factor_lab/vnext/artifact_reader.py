"""Read-only, allowlisted projection of formal VNext acceptance artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import DataStatus


RUN_ARTIFACTS = (
    "domain_decision.json",
    "target_weights.json",
    "portfolio_optimization.json",
    "ml_ranker_manifest.json",
    "fast_backtest_manifest.json",
    "event_backtest_manifest.json",
    "reconciliation_report.json",
    "execution_certification.json",
    "antifragile_review.json",
)


class VNextArtifactReader:
    """Expose formal artifacts without accepting filesystem paths from callers."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve() / "artifacts" / "vnext"

    def run(self, run_id: str) -> dict[str, Any]:
        self._validate_id(run_id)
        artifacts: dict[str, dict[str, Any]] = {}
        for filename in RUN_ARTIFACTS:
            payload = self._read(filename)
            if payload is not None:
                artifacts[filename.removesuffix(".json")] = payload
        matching = {
            name: payload
            for name, payload in artifacts.items()
            if run_id in self._identifiers(payload) or run_id == "latest"
        }
        if not matching:
            raise FileNotFoundError(f"VNext run not found: {run_id}")
        statuses = [str(payload.get("status") or payload.get("quality_status") or "PARTIAL") for payload in matching.values()]
        degraded = [status for status in statuses if status != DataStatus.OK.value]
        return {
            "run_id": run_id,
            "as_of": next((str(item.get("as_of")) for item in matching.values() if item.get("as_of")), None),
            "status": DataStatus.PARTIAL.value if degraded else DataStatus.OK.value,
            "evidence": [f"formal_artifacts={len(matching)}"],
            "missing_evidence": [f"degraded_status={status}" for status in degraded],
            "confidence": round((len(statuses) - len(degraded)) / len(statuses), 4),
            "provider": ["local:artifacts/vnext"],
            "warnings": [],
            "lineage": self._lineage(matching),
            "payload": matching,
        }

    def snapshot(self, snapshot_id: str) -> dict[str, Any]:
        self._validate_id(snapshot_id)
        snapshot = self._read("snapshot_manifest.json")
        if snapshot is None or snapshot.get("data_snapshot_id") != snapshot_id:
            raise FileNotFoundError(f"VNext snapshot not found: {snapshot_id}")
        return {
            "run_id": snapshot_id,
            "as_of": snapshot.get("as_of"),
            "status": snapshot.get("status", DataStatus.MISSING.value),
            "evidence": [
                f"verified_count={snapshot.get('verified_count', 0)}",
                f"manifest_count={snapshot.get('manifest_count', 0)}",
            ],
            "missing_evidence": list(snapshot.get("errors", [])),
            "confidence": (
                round(float(snapshot.get("verified_count", 0)) / float(snapshot.get("manifest_count", 1)), 4)
                if snapshot.get("manifest_count")
                else 0.0
            ),
            "provider": sorted({str(item.get("provider")) for item in snapshot.get("entries", []) if item.get("provider")}),
            "warnings": ["silent_fallback_used"] if snapshot.get("silent_fallback_used") else [],
            "lineage": {
                "data_snapshot_id": snapshot_id,
                "combined_content_hash": snapshot.get("combined_content_hash"),
            },
            "payload": snapshot,
        }

    def reconciliation(self, run_id: str) -> dict[str, Any]:
        self._validate_id(run_id)
        report = self._read("reconciliation_report.json")
        if report is None or (run_id != "latest" and run_id not in self._identifiers(report)):
            raise FileNotFoundError(f"VNext reconciliation not found: {run_id}")
        return {
            "run_id": run_id,
            "as_of": report.get("as_of"),
            "status": report.get("status", DataStatus.MISSING.value),
            "evidence": [
                f"return_gap={report.get('return_gap')}",
                f"drawdown_gap={report.get('drawdown_gap')}",
            ],
            "missing_evidence": list(report.get("missing_evidence", [])),
            "confidence": 1.0 if report.get("status") == DataStatus.OK.value else 0.0,
            "provider": ["vectorbt-fast-lane", "event-truth-lane"],
            "warnings": list(report.get("warnings", [])),
            "lineage": {
                "data_snapshot_id": report.get("data_snapshot_id"),
                "target_weights_hash": report.get("target_weights_hash"),
            },
            "payload": report,
        }

    @staticmethod
    def _validate_id(value: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
            raise ValueError("invalid VNext artifact identifier")

    def _read(self, name: str) -> dict[str, Any] | None:
        if name not in {*RUN_ARTIFACTS, "snapshot_manifest.json"}:
            raise ValueError("artifact is not allowlisted")
        path = self.root / name
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"artifact must be an object: {name}")
        return payload

    @staticmethod
    def _identifiers(payload: dict[str, Any]) -> set[str]:
        return {
            str(value)
            for key in ("as_of", "run_id", "run_hash", "data_snapshot_id", "target_weights_hash")
            if (value := payload.get(key))
        }

    @staticmethod
    def _lineage(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "data_snapshot_ids": sorted({str(item["data_snapshot_id"]) for item in artifacts.values() if item.get("data_snapshot_id")}),
            "target_weights_hashes": sorted({str(item["target_weights_hash"]) for item in artifacts.values() if item.get("target_weights_hash")}),
            "artifact_names": sorted(artifacts),
        }
