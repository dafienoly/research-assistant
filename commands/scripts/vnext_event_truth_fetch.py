#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion  # noqa: E402
from factor_lab.vnext.snapshot import ASSET_PROXIES  # noqa: E402


if __name__ == "__main__":
    end = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    start = sys.argv[2] if len(sys.argv) > 2 else "20200101"
    symbols = sorted({symbol for symbol, _ in ASSET_PROXIES.values()})
    print(json.dumps(EventTruthIngestion(ROOT).fetch(symbols, start, end), ensure_ascii=False, indent=2))
