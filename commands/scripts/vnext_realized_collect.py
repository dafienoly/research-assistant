#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))

from factor_lab.vnext.realized_observations import RealizedObservationCollector  # noqa: E402


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().astimezone().date().isoformat()
    print(json.dumps(RealizedObservationCollector().run(ROOT, day), ensure_ascii=False, indent=2))
