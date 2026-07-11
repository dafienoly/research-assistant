#!/usr/bin/env python3
"""Deprecated K-line remediation entry delegated to canonical DataHub ingestion.

The historical implementation owned a second provider client, rewrote legacy
CSV files in place, changed schemas and removed ``*_hist.csv`` files.  This
compatibility command deliberately owns none of those responsibilities.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands"
if str(COMMANDS) not in sys.path:
    sys.path.insert(0, str(COMMANDS))

from market_fetcher import cmd_update_daily  # noqa: E402


def run() -> None:
    """Run the locked, staged and auditable canonical daily pipeline."""
    print("=== canonical DataHub daily incremental ingestion ===")
    cmd_update_daily()
    print("✅ DataHub daily incremental ingestion completed")


if __name__ == "__main__":
    run()
