#!/usr/bin/env python3
"""Deliver pending decision-loop notifications from the durable outbox."""

from __future__ import annotations

import json

from factor_lab.decision_loop.service import DecisionLoopService


if __name__ == "__main__":
    service = DecisionLoopService()
    print(json.dumps(service.notifications.deliver_pending(), ensure_ascii=False, indent=2))
