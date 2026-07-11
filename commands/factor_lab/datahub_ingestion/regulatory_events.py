"""Ingest auditable regulatory-announcement truth for planned trade symbols."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


BLACKLIST_TERMS = ("立案调查", "行政处罚", "重大违法", "强制退市", "退市风险")
WARNING_TERMS = ("监管函", "警示函", "责令改正", "纪律处分", "违规", "问询函")


class RegulatoryEventIngestion:
    """Fetch announcements only in ingestion and publish explicit symbol coverage."""

    def __init__(
        self,
        project_root: str | Path,
        fetcher: Callable[[str], list[dict]] | None = None,
    ) -> None:
        self.root = Path(project_root).resolve()
        self.output = self.root / "data/normalized/events/regulatory_watchlist.json"
        self.fetcher = fetcher or self._default_fetcher()

    def fetch(self, symbols: list[str]) -> dict:
        requested = sorted({self._normalize(symbol) for symbol in symbols if self._normalize(symbol)})
        covered = []
        failed = []
        events = []
        for symbol in requested:
            try:
                announcements = self.fetcher(symbol) or []
                covered.append(symbol)
            except Exception as error:
                failed.append({"symbol": symbol, "error": type(error).__name__})
                continue
            for announcement in announcements:
                title = str(announcement.get("title", "")).strip()
                severity = self._severity(title)
                if severity == "notice":
                    continue
                event_date = self._date(announcement.get("date"))
                if event_date is None:
                    continue
                events.append({
                    "symbol": symbol,
                    "date": event_date,
                    "severity": severity,
                    "title": title,
                    "source": announcement.get("source", "announcement_provider"),
                    "source_ref": announcement.get("id") or announcement.get("url") or announcement.get("adjunct_url"),
                })
        status = "EMPTY" if not requested else ("OK" if not failed else "PARTIAL")
        payload = {
            "status": status,
            "generated_at": datetime.now().astimezone().isoformat(),
            "requested_symbols": requested,
            "covered_symbols": covered,
            "failed_symbols": failed,
            "events": sorted(events, key=lambda row: (row["date"], row["symbol"], row["title"])),
            "source": "cninfo+sse+szse_via_datahub_ingestion",
            "coverage_policy": "symbols absent from covered_symbols remain fail-closed",
        }
        EventTruthIngestion._atomic_json(self.output, payload)
        return payload

    @staticmethod
    def _normalize(symbol: str) -> str:
        digits = "".join(character for character in str(symbol) if character.isdigit())[:6]
        return digits if len(digits) == 6 else ""

    @staticmethod
    def _date(value: object) -> str | None:
        try:
            if isinstance(value, (int, float)) and value > 10_000_000_000:
                return datetime.fromtimestamp(float(value) / 1000).astimezone().date().isoformat()
            return datetime.fromisoformat(str(value)[:10]).date().isoformat() if value else None
        except (ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _severity(title: str) -> str:
        if any(term in title for term in BLACKLIST_TERMS):
            return "blacklist"
        if any(term in title for term in WARNING_TERMS):
            return "warning"
        return "notice"

    @staticmethod
    def _default_fetcher() -> Callable[[str], list[dict]]:
        from provider_matrix import AnnouncementProvider

        provider = AnnouncementProvider()

        def fetch(symbol: str) -> list[dict]:
            announcements = provider.get_all(symbol)
            if not announcements:
                raise RuntimeError("announcement sources returned no verifiable response")
            return announcements

        return fetch
