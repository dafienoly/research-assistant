#!/usr/bin/env python3
"""Build canonical DataHub benchmark projections."""

from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path

from factor_lab.datahub_ingestion.benchmark_projection import build_benchmark_projections


def main() -> int:
    lock_dir = Path(os.environ.get("HERMES_LOCK_DIR", Path.home() / ".hermes/locks"))
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / "datahub-global.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        print(json.dumps(build_benchmark_projections(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
