"""Compatibility commands delegated to canonical DataHub ingestion owners."""

from __future__ import annotations

import subprocess
from pathlib import Path

from config import PATHS, read_csv_safe
from factor_lab.datahub_access import read_live_snapshot
from factor_lab.datahub_ingestion.live_snapshot import LiveSnapshotIngestion


ROOT = Path(__file__).resolve().parents[1]


class MarketDataFetcher:
    """Legacy facade that performs no provider access or dataset writes itself."""

    def update_live_snapshot(self, priority_codes: list[str] | None = None) -> dict:
        manifest = LiveSnapshotIngestion().fetch_locked(priority_codes)
        return {"total": manifest["rows"], "priority": manifest["priority_rows"]}

    def update_priority_snapshot(self, codes: list[str]) -> list[dict]:
        LiveSnapshotIngestion().fetch_locked(codes)
        return list(read_live_snapshot(codes).values())


def _run_daily_datahub() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "commands/scripts/datahub_cron.sh"), "daily-incremental"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"canonical DataHub daily ingestion failed: exit {result.returncode}")


def cmd_update_daily() -> None:
    """Compatibility alias for the canonical daily DataHub pipeline."""
    _run_daily_datahub()


def cmd_update_live_snapshot() -> None:
    result = MarketDataFetcher().update_live_snapshot()
    print(f"✅ DataHub 实时快照已更新: {result['total']} 只股票")


def cmd_update_priority_minute() -> None:
    rows = read_csv_safe(PATHS["tags"] / "semiconductor_chain_tags.csv")
    codes = [row.get("code", "") for row in rows if row.get("code")]
    if not codes:
        print("⚠️ 优先池为空")
        return
    result = MarketDataFetcher().update_live_snapshot(codes)
    print(f"✅ DataHub 优先池快照已更新: {result['priority']} 只")


def cmd_update_fundamentals() -> None:
    """Compatibility alias; financial data remains owned by the daily DataHub pipeline."""
    _run_daily_datahub()
