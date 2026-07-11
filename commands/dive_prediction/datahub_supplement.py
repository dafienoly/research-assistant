"""Legacy dive-data command delegated to canonical DataHub ingestion owners."""

from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path

from factor_lab.datahub_ingestion.locking import datahub_write_lock
from factor_lab.datahub_ingestion.market_series import MarketSeriesIngestion


ROOT = Path(__file__).resolve().parents[2]
INDEX_SYMBOL = "931743.CSI"


def _run_daily_datahub() -> dict:
    result = subprocess.run(
        ["bash", str(ROOT / "commands/scripts/datahub_cron.sh"), "daily-incremental"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"canonical DataHub daily ingestion failed: exit {result.returncode}")
    return {"status": "OK", "owner": "datahub_cron:daily-incremental"}


def pull_stock_kline() -> dict:
    """Compatibility alias for canonical daily market ingestion."""
    return _run_daily_datahub()


def pull_fund_flow() -> dict:
    """Compatibility alias for canonical partitioned fund-flow ingestion."""
    return _run_daily_datahub()


def pull_index() -> dict:
    """Ingest the semiconductor equipment/material index through DataHub."""
    with datahub_write_lock():
        return MarketSeriesIngestion(ROOT).fetch(
            {"index_daily": [INDEX_SYMBOL]},
            start_date="20210101",
            end_date=date.today().strftime("%Y%m%d"),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", action="store_true")
    parser.add_argument("--fund", action="store_true")
    parser.add_argument("--index", action="store_true")
    args = parser.parse_args(argv)
    do_all = not (args.stocks or args.fund or args.index)

    if do_all or args.stocks or args.fund:
        result = _run_daily_datahub()
        print(f"daily market/fund-flow: {result['status']}")
    if do_all or args.index:
        result = pull_index()
        print(f"index {INDEX_SYMBOL}: {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
