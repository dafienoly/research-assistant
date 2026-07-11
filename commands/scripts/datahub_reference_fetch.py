#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))

from factor_lab.datahub_ingestion.reference import ReferenceIngestion  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(ReferenceIngestion(ROOT).fetch_stock_basic(), ensure_ascii=False, indent=2))
