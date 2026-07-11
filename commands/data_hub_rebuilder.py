"""Compatibility facade for canonical DataHub factor-input projections."""

from __future__ import annotations

import sys
from pathlib import Path

from factor_lab.datahub_ingestion.factor_inputs import FactorInputProjection


ROOT = Path(__file__).resolve().parents[1]


def _build(target: str) -> dict:
    return FactorInputProjection(ROOT).build(target)


def rebuild_fundamentals_timeseries() -> dict:
    return _build("fundamentals")


def refresh_fund_flow_timeseries(batch_size: int = 20) -> dict:
    del batch_size  # compatibility only; projection always consumes the complete canonical snapshot
    return _build("fund-flow")


def rebuild_news_sentiment_timeseries(top_n: int = 50) -> dict:
    del top_n  # compatibility only; coverage is defined by the regulatory snapshot manifest
    return _build("sentiment")


def main() -> int:
    targets = {
        "fundamentals": rebuild_fundamentals_timeseries,
        "fund-flow": refresh_fund_flow_timeseries,
        "sentiment": rebuild_news_sentiment_timeseries,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in ("all", *targets):
        print("用法: python3 data_hub_rebuilder.py <fundamentals|fund-flow|sentiment|all>")
        return 1
    requested = list(targets) if sys.argv[1] == "all" else [sys.argv[1]]
    results = {target: targets[target]() for target in requested}
    for target, result in results.items():
        print(f"{target}: {result['status']} rows={result['rows']}")
    return 0 if all(result["status"] in {"OK", "EMPTY"} for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
