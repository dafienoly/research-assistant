"""Read-only regulatory risk truth backed by a canonical DataHub snapshot."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.datahub_access import DATAHUB_ROOT


class RegulatoryWatchlist:
    """Query regulatory events without network access or consumer-side writes."""

    CACHE_PATH: Path = DATAHUB_ROOT / "events" / "regulatory_watchlist.json"

    def __init__(self, cache_path: Optional[str | Path] = None):
        self.CACHE_PATH = Path(cache_path) if cache_path is not None else self.CACHE_PATH
        self._events: list[dict] = []
        self._blacklist_symbols: set[str] = set()
        self._warning_symbols: set[str] = set()
        self._loaded = False
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self._loaded

    @property
    def error(self) -> str | None:
        return self._error

    def refresh(self) -> int:
        """Reload the canonical snapshot; external fetching belongs to ingestion."""
        if not self.load_cache():
            raise RuntimeError(self._error or "canonical regulatory snapshot unavailable")
        return len(self._events)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        code = "".join(character for character in symbol if character.isdigit())[:6]
        return code if len(code) == 6 else ""

    def _build_index(self, records: list[dict]) -> None:
        self._events = records
        self._blacklist_symbols.clear()
        self._warning_symbols.clear()
        for event in records:
            symbol = self._normalize_symbol(str(event.get("symbol", "")))
            if not symbol:
                continue
            severity = event.get("severity", "notice")
            if severity == "blacklist":
                self._blacklist_symbols.add(symbol)
            elif severity == "warning":
                self._warning_symbols.add(symbol)

    def load_cache(self) -> bool:
        if not self.CACHE_PATH.exists():
            self._error = f"canonical regulatory snapshot missing: {self.CACHE_PATH}"
            return False
        try:
            payload = json.loads(self.CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._error = f"canonical regulatory snapshot unreadable: {exc}"
            return False
        records = payload.get("events")
        if not isinstance(records, list):
            self._error = "canonical regulatory snapshot missing events"
            return False
        status = str(payload.get("status", "OK")).upper()
        if status not in {"OK", "EMPTY"}:
            self._error = f"canonical regulatory snapshot status={status}"
            return False
        self._build_index(records)
        self._loaded = True
        self._error = None
        return True

    def ensure_fresh(self) -> int:
        return self.refresh()

    def is_blacklisted(self, symbol: str) -> bool:
        if not self._loaded and not self.load_cache():
            return False
        return self._normalize_symbol(symbol) in self._blacklist_symbols

    def has_recent_regulatory_risk(self, symbol: str, days: int = 30) -> bool:
        if not self._loaded and not self.load_cache():
            return False
        code = self._normalize_symbol(symbol)
        if code in self._blacklist_symbols:
            return True
        cutoff = date.today() - timedelta(days=days)
        for event in self._events:
            if self._normalize_symbol(str(event.get("symbol", ""))) != code:
                continue
            if event.get("severity") not in {"blacklist", "warning"}:
                continue
            try:
                event_date = datetime.fromisoformat(str(event.get("date", ""))[:10]).date()
            except ValueError:
                continue
            if event_date >= cutoff:
                return True
        return False

    def get_events(self, symbol: str, days: Optional[int] = None) -> list[dict]:
        if not self._loaded and not self.load_cache():
            return []
        code = self._normalize_symbol(symbol)
        cutoff = date.today() - timedelta(days=days) if days is not None else None
        results = []
        for event in self._events:
            if self._normalize_symbol(str(event.get("symbol", ""))) != code:
                continue
            if cutoff is not None:
                try:
                    event_date = datetime.fromisoformat(str(event.get("date", ""))[:10]).date()
                except ValueError:
                    continue
                if event_date < cutoff:
                    continue
            results.append(event)
        return results

    def get_all_blacklisted(self) -> list[str]:
        if not self._loaded and not self.load_cache():
            return []
        return sorted(self._blacklist_symbols)

    def get_all_warnings(self) -> list[str]:
        if not self._loaded and not self.load_cache():
            return []
        return sorted(self._warning_symbols)

    def get_summary(self) -> dict:
        if not self._loaded and not self.load_cache():
            return {
                "status": "unavailable",
                "error": self._error,
                "n_blacklisted": 0,
                "n_warning": 0,
                "n_notice": 0,
                "total": 0,
            }
        return {
            "status": "ok",
            "n_blacklisted": len(self._blacklist_symbols),
            "n_warning": len(self._warning_symbols),
            "n_notice": sum(1 for event in self._events if event.get("severity") == "notice"),
            "total": len(self._events),
        }
