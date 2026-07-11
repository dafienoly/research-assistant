#!/usr/bin/env python3
"""One safe minute-level guard cycle for holdings and persisted watch targets."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

COMMANDS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMANDS))

from factor_lab.broker.qmt_client import QMTClient  # noqa: E402
from factor_lab.decision_loop.calendar import TradingCalendarGate  # noqa: E402
from factor_lab.decision_loop.models import DataItemStatus, Position, QuoteSnapshot  # noqa: E402
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
    snapshot = service.positions.current()
    if not snapshot:
        print(
            json.dumps(
                {"status": "blocked", "reason": "no_confirmed_positions"},
                ensure_ascii=False,
            )
        )
        return 2
    watchlist = service.store.read_json(
        "watchlist/current.json", default={"targets": []}
    )
    watchlist_changed = False
    monitored = list(snapshot.positions)
    held_keys = {(position.symbol, position.book.value) for position in monitored}
    for target in watchlist.get("targets", []):
        key = (target.get("symbol", ""), target.get("book", "swing"))
        if not key[0] or key in held_keys:
            continue
        monitored.append(
            Position(
                symbol=key[0],
                name=target.get("name", ""),
                quantity=0,
                available_quantity=0,
                cost_price=float(target.get("reference_price") or 0),
                instrument_type=target.get("instrument_type", "stock"),
                book=key[1],
                theme="watch_target",
            )
        )
    client = QMTClient()
    if not client.is_configured():
        print(
            json.dumps(
                {"status": "blocked", "reason": "QMT_BRIDGE_BASE_URL_not_configured"},
                ensure_ascii=False,
            )
        )
        return 2
    response = client.get_quotes(sorted({position.symbol for position in monitored}))
    if response.get("status") != "ok":
        print(
            json.dumps(
                {"status": "blocked", "reason": "quote_fetch_failed"},
                ensure_ascii=False,
            )
        )
        return 2
    now = datetime.now().astimezone()
    calendar = TradingCalendarGate(service.store).resolve(now.date(), now)
    if not calendar["available"]:
        print(
            json.dumps(
                {"status": "blocked", "reason": "trade_calendar_unavailable"},
                ensure_ascii=False,
            )
        )
        return 2
    if not calendar["is_open"]:
        print(
            json.dumps(
                {"status": "non_trading_day", "calendar": calendar}, ensure_ascii=False
            )
        )
        return 0
    quotes = _quotes_by_symbol(response.get("data"))
    all_actions = []
    for position in monitored:
        row = quotes.get(position.symbol)
        if not row:
            continue
        last = float(row.get("last_price") or row.get("last") or row.get("price") or 0)
        if last <= 0:
            continue
        if position.cost_price <= 0:
            position = position.model_copy(update={"cost_price": last})
            for target in watchlist.get("targets", []):
                if target.get("symbol") == position.symbol and not target.get(
                    "reference_price"
                ):
                    target["reference_price"] = last
                    watchlist_changed = True
        quote = QuoteSnapshot(
            symbol=position.symbol,
            last_price=last,
            vwap=float(row.get("vwap")) if row.get("vwap") else None,
            volume=float(row.get("volume") or 0),
            average_volume=float(row.get("average_volume"))
            if row.get("average_volume")
            else None,
            observed_at=now,
            source="miniqmt",
            freshness_seconds=int(row.get("freshness_seconds") or 0),
        )
        data_items = [
            DataItemStatus(
                name="quotes",
                available=True,
                fresh=quote.freshness_seconds <= 90,
                source="miniqmt",
                as_of=now,
            ),
            DataItemStatus(
                name="positions",
                available=True,
                fresh=True,
                source=snapshot.source,
                as_of=snapshot.as_of,
            ),
            DataItemStatus(
                name="trade_calendar",
                available=True,
                fresh=True,
                source=calendar["source"],
                as_of=datetime.fromisoformat(calendar["checked_at"]),
            ),
            DataItemStatus(name="news", available=False, fresh=False),
            DataItemStatus(name="capital_flow", available=False, fresh=False),
            DataItemStatus(name="fundamentals", available=False, fresh=False),
        ]
        result = service.evaluate_position(
            Position.model_validate(position), quote, data_items
        )
        all_actions.extend(result["actions"])
    if watchlist_changed:
        service.store.write_json("watchlist/current.json", watchlist)
    print(
        json.dumps(
            {"status": "ok", "evaluated": len(monitored), "actions": all_actions},
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
