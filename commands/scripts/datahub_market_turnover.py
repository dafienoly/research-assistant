#!/usr/bin/env python3
"""Build the canonical all-market turnover projection under the global writer lock."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from factor_lab.datahub_ingestion.market_turnover import build_market_turnover_projection


def main() -> int:
    lock_dir = Path(os.environ.get("HERMES_LOCK_DIR", Path.home() / ".hermes/locks"))
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / "datahub-global.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        print(json.dumps(build_market_turnover_projection(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
