#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

from factor_lab.datahub_ingestion.suspensions import SuspensionIngestion  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(SuspensionIngestion(ROOT).refresh_from_health(), ensure_ascii=False, indent=2))
