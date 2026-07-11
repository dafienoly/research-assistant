#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))

from factor_lab.datahub_ingestion.market_series import MarketSeriesIngestion  # noqa: E402
from factor_lab.vnext.datasets import PolicyBacktestDatasetBuilder  # noqa: E402


if __name__ == "__main__":
    end = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    start = sys.argv[2] if len(sys.argv) > 2 else "20200101"
    datasets = {
        "index_daily": list(PolicyBacktestDatasetBuilder.INDEX_CODES.values()),
        "fund_daily": list(PolicyBacktestDatasetBuilder.FUND_CODES.values()),
    }
    print(json.dumps(MarketSeriesIngestion(ROOT).fetch(datasets, start, end), ensure_ascii=False, indent=2))
