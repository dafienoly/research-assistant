"""Deprecated Tushare writer delegated to the canonical DataHub pipeline.

This compatibility module intentionally owns no provider client, output
directory, per-symbol merge, CSV write or retry policy.
"""

from __future__ import annotations

import argparse

from market_fetcher import cmd_update_daily


def run_incremental(days_back: int = 5) -> None:
    """Compatibility entry; the canonical owner decides the incremental window."""
    if days_back < 1:
        raise ValueError("days_back must be positive")
    cmd_update_daily()


def run_full() -> None:
    """Compatibility entry; full publication remains owned by DataHub."""
    cmd_update_daily()


def main() -> None:
    parser = argparse.ArgumentParser(description="Delegate to canonical DataHub ingestion")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--days-back", type=int, default=5)
    args = parser.parse_args()
    if args.incremental:
        run_incremental(args.days_back)
    else:
        run_full()


if __name__ == "__main__":
    main()
