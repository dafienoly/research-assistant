#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factor_lab.decision_loop.postmarket_review import PostMarketReviewService  # noqa: E402


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().astimezone().date().isoformat()
    service = PostMarketReviewService()
    records = service.generate(day)
    print(json.dumps({"records": [row.model_dump(mode="json") for row in records], "weekly_candidates": service.propose_weekly_candidates(day[:7])}, ensure_ascii=False, indent=2))
