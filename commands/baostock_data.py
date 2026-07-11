"""Retired Baostock facade delegated to canonical DataHub owners.

The filename remains only for operator-script compatibility.  Provider access,
dataset schemas, feature construction and CSV publication are owned elsewhere.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from factor_lab.datahub_ingestion.factor_inputs import FactorInputProjection


ROOT = Path(__file__).resolve().parents[1]


def _run_daily_datahub() -> dict:
    result = subprocess.run(
        ["bash", str(ROOT / "commands/scripts/datahub_cron.sh"), "daily-incremental"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"canonical DataHub daily ingestion failed: exit {result.returncode}")
    return {"status": "OK", "owner": "datahub_cron:daily-incremental"}


def run_all(codes: list[str] | None = None) -> dict:
    """Run canonical ingestion once; explicit legacy code scopes are not accepted."""
    if codes:
        raise ValueError("legacy per-code Baostock refresh retired; use canonical DataHub ingestion")
    daily = _run_daily_datahub()
    fundamentals = FactorInputProjection(ROOT).build("fundamentals")
    return {"daily": daily, "fundamentals": fundamentals, "status": fundamentals["status"]}


if __name__ == "__main__":
    result = run_all()
    print(f"canonical DataHub refresh: {result['status']}")
