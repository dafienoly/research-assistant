#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factor_lab.decision_loop.certification import DecisionLoopCertification  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(DecisionLoopCertification().evaluate(), ensure_ascii=False, indent=2))
