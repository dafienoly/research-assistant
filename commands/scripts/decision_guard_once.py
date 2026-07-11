#!/usr/bin/env python3
"""Run one non-overlapping decision cycle and emit its unified contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

COMMANDS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMANDS))
try:
    from dotenv import load_dotenv
    load_dotenv(COMMANDS.parent / ".env", override=False)
except ImportError:
    pass

from factor_lab.decision_loop.cycle import MinuteDecisionCycle  # noqa: E402
from factor_lab.decision_loop.service import DecisionLoopService  # noqa: E402


def _quotes_by_symbol(raw: object) -> dict[str, dict]:
    if isinstance(raw, dict):
        if all(isinstance(value, dict) for value in raw.values()):
            return raw
        rows = raw.get("quotes") or raw.get("items") or []
    else:
        rows = raw if isinstance(raw, list) else []
    return {
        str(row.get("symbol") or row.get("code")): row
        for row in rows
        if isinstance(row, dict)
    }


def main() -> int:
    service = DecisionLoopService()
    result = MinuteDecisionCycle(service).run()
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, default=str))
    return 0 if result.status in {"ok", "degraded", "skipped"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
