"""Core-side launcher for the isolated vectorbt research worker."""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .contracts import QualityStatus, TargetPortfolioWeights, now_iso, sha256_payload


class VectorbtBoundaryError(RuntimeError):
    pass


def inspect_worker_boundary(worker_path: str | Path) -> dict[str, Any]:
    """Reject imports that would let the research worker reach execution or data clients."""
    path = Path(worker_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden_roots = {"requests", "httpx", "tushare", "akshare", "xtquant", "vnpy"}
    forbidden_fragments = ("broker", "execution", "qmt_client")
    violations = sorted(
        name
        for name in imports
        if name.split(".")[0] in forbidden_roots or any(fragment in name.lower() for fragment in forbidden_fragments)
    )
    return {
        "status": "OK" if not violations else "BLOCKED",
        "worker_path": str(path),
        "imports": sorted(set(imports)),
        "violations": violations,
        "broker_import_allowed": False,
        "data_client_import_allowed": False,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class VectorbtFastLaneAdapter:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.python = self.project_root / ".venv_vectorbt" / "bin" / "python"
        self.worker = self.project_root / "commands" / "vectorbt_worker.py"
        self.lock_file = self.project_root / "requirements" / "vectorbt.lock"

    def run(
        self,
        *,
        as_of: str,
        snapshot_manifest_path: str | Path,
        target_weights_path: str | Path,
        output_path: str | Path,
    ) -> dict[str, Any]:
        if not self.python.exists() or not self.lock_file.exists():
            raise VectorbtBoundaryError("isolated vectorbt environment or lock file missing")
        boundary = inspect_worker_boundary(self.worker)
        if boundary["status"] != "OK":
            raise VectorbtBoundaryError(f"worker boundary violation: {boundary['violations']}")
        snapshot_path = Path(snapshot_manifest_path).resolve()
        weights_path = Path(target_weights_path).resolve()
        destination = Path(output_path).resolve()
        for path in (snapshot_path, weights_path, destination):
            if self.project_root not in path.parents:
                raise VectorbtBoundaryError(f"path outside project root: {path}")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        weights_raw = json.loads(weights_path.read_text(encoding="utf-8"))
        weights = TargetPortfolioWeights.model_validate(weights_raw)
        if snapshot.get("status") != QualityStatus.OK.value or not snapshot.get("snapshot_id_valid"):
            raise VectorbtBoundaryError("immutable snapshot manifest is not verified")
        if weights.data_snapshot_id != snapshot.get("data_snapshot_id"):
            raise VectorbtBoundaryError("target weights and snapshot IDs differ")
        if weights.quality_status in {QualityStatus.MISSING, QualityStatus.STALE, QualityStatus.BLOCKED}:
            raise VectorbtBoundaryError(f"target weight quality is {weights.quality_status.value}")
        run_id = f"fast-{as_of}-{sha256_payload({'snapshot': weights.data_snapshot_id, 'weights': weights.target_weights_hash})[:16]}"
        bundle = {
            "schema_version": "1.0",
            "run_id": run_id,
            "as_of": as_of,
            "data_snapshot_id": weights.data_snapshot_id,
            "target_weights_hash": weights.target_weights_hash,
            "target_weights": weights.to_dict(),
            "snapshot_manifest_path": str(snapshot_path),
            "snapshot_manifest_sha256": sha256_payload(snapshot),
            "snapshot_entries": snapshot.get("entries", []),
            "research_config": {
                "initial_cash": 1_000_000,
                "fees": 0.0005,
                "slippage_bps": 10,
                "static_rebalance_days": 20,
                "momentum_lookbacks": [5, 20, 60],
                "top_k": [2, 3, 5],
                "rebalance_frequencies_days": [5, 20],
            },
            "boundaries": {
                "data_download_allowed": False,
                "external_network_allowed": False,
                "broker_access_allowed": False,
                "execution_truth": False,
                "paper_or_live_promotion_allowed": False,
            },
            "created_at": now_iso(),
        }
        bundle["input_bundle_hash"] = sha256_payload(bundle)
        input_path = self.project_root / "artifacts" / "vnext" / "manifests" / f"{run_id}.input.json"
        _atomic_json(input_path, bundle)
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONNOUSERSITE": "1",
            "HERMES_PROJECT_ROOT": str(self.project_root),
            "HERMES_NO_LIVE_TRADE": "true",
        }
        completed = subprocess.run(
            [str(self.python), str(self.worker), "--input", str(input_path), "--output", str(destination)],
            cwd=self.project_root,
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise VectorbtBoundaryError(
                f"isolated worker failed rc={completed.returncode}: {(completed.stderr or completed.stdout)[-1000:]}"
            )
        result = json.loads(destination.read_text(encoding="utf-8"))
        if result.get("input_bundle_hash") != bundle["input_bundle_hash"]:
            raise VectorbtBoundaryError("worker result input hash mismatch")
        if result.get("real_broker_called") is not False or result.get("data_download_used") is not False:
            raise VectorbtBoundaryError("worker violated research-only boundary")
        result["boundary_audit"] = boundary
        result["lock_file"] = str(self.lock_file)
        result["input_manifest"] = str(input_path)
        _atomic_json(destination, result)
        return result
