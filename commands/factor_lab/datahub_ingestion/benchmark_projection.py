"""Materialize equal-weight benchmark projections from canonical DataHub inputs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks_v4 import (
    BENCHMARK_MAX_HISTORY_ROWS,
    BENCHMARK_PROJECTION_DIR,
    VALID_BENCHMARK_NAMES,
    compute_benchmark_projection,
)
from data_recovery import atomic_write_frame


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def build_benchmark_projections(output_dir: Path = BENCHMARK_PROJECTION_DIR) -> dict[str, Any]:
    """Build every benchmark before publishing one complete manifest."""
    generated_at = datetime.now().astimezone().isoformat()
    datasets: dict[str, dict[str, Any]] = {}
    for name in sorted(VALID_BENCHMARK_NAMES):
        returns = compute_benchmark_projection(name)
        if returns.empty and name != "etf_basket_ew":
            raise RuntimeError(f"benchmark projection empty: {name}")
        frame = pd.DataFrame({"date": returns.index, "return": returns.to_numpy()})
        output = output_dir / f"{name}.csv"
        content_hash = atomic_write_frame(frame, output)
        datasets[name] = {
            "status": "OK" if not frame.empty else "EMPTY_OPTIONAL",
            "rows": len(frame),
            # Paths inside a dataset manifest must remain valid after restoring
            # the DataHub tree on another workstation or mount point.
            "path": output.name,
            "sha256": content_hash,
        }
    manifest = {
        "status": "OK",
        "generated_at": generated_at,
        "source": "canonical_datahub_daily_plus_universes",
        "max_history_rows_per_symbol": BENCHMARK_MAX_HISTORY_ROWS,
        "datasets": datasets,
    }
    _atomic_json(output_dir / "manifest.json", manifest)
    return manifest
