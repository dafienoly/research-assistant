"""Deprecated K-line entry point delegated to canonical DataHub ingestion.

This module intentionally owns neither provider access nor CSV writes.  It is
kept as a compatibility command for old operator scripts; the canonical daily
pipeline owns fetching, staging, deduplication, atomic publication and audit.
"""

from __future__ import annotations

from market_fetcher import cmd_update_daily


def run() -> None:
    """Run the canonical daily incremental DataHub pipeline."""
    print("=== canonical DataHub daily incremental ingestion ===")
    cmd_update_daily()
    print("✅ DataHub daily incremental ingestion completed")


if __name__ == "__main__":
    run()
