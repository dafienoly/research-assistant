"""Authoritative daily trade-calendar gate with bounded retry caching."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from .storage import DecisionLoopStore


class TradingCalendarGate:
    def __init__(
        self,
        store: DecisionLoopStore | None = None,
        provider: Callable[[str], object] | None = None,
    ):
        self.store = store or DecisionLoopStore()
        self.provider = provider or self._datahub_provider

    def resolve(self, trading_date: date, now: datetime | None = None) -> dict:
        now = now or datetime.now().astimezone()
        key = trading_date.isoformat()
        cached = self.store.read_json(f"calendar/{key}.json")
        if cached:
            checked = datetime.fromisoformat(cached["checked_at"])
            ttl = (
                timedelta(hours=20) if cached.get("available") else timedelta(minutes=5)
            )
            if now - checked < ttl:
                return cached
        try:
            raw = self.provider(trading_date.strftime("%Y%m%d"))
            is_open = self._extract_is_open(raw, trading_date)
            result = {
                "available": True,
                "is_open": is_open,
                "source": "datahub.trade_calendar",
                "checked_at": now.isoformat(),
                "date": key,
            }
        except Exception as exc:
            result = {
                "available": False,
                "is_open": None,
                "source": "unavailable",
                "checked_at": now.isoformat(),
                "date": key,
                "error": type(exc).__name__,
            }
        self.store.write_json(f"calendar/{key}.json", result)
        return result

    @staticmethod
    def _datahub_provider(date_text: str):
        from factor_lab.datahub_access import calendar_row

        return calendar_row(datetime.strptime(date_text, "%Y%m%d").date())

    @staticmethod
    def _extract_is_open(raw: object, trading_date: date) -> bool:
        if hasattr(raw, "to_dict"):
            rows = raw.to_dict("records")
        elif isinstance(raw, dict):
            rows = raw.get("items") or raw.get("data") or [raw]
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = []
        target = trading_date.strftime("%Y%m%d")
        for row in rows:
            row_date = str(row.get("cal_date") or row.get("date") or "").replace(
                "-", ""
            )
            if row_date == target:
                return bool(int(row.get("is_open", row.get("is_trading_day", 0))))
        raise ValueError("trade calendar response has no target date")
