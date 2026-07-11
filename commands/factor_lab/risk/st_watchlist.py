"""Read-only ST risk truth backed by canonical DataHub reference data."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from factor_lab.datahub_access import STOCK_BASIC_PATH


class STWatchlist:
    """Expose ST status without network access or consumer-side cache writes."""

    CACHE_PATH: Path = STOCK_BASIC_PATH

    def __init__(self, cache_path: Optional[str | Path] = None):
        self.CACHE_PATH = Path(cache_path) if cache_path is not None else STOCK_BASIC_PATH
        self._st_map: dict[str, dict] = {}
        self._loaded = False
        self._source_as_of: str | None = None
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self._loaded

    @property
    def error(self) -> str | None:
        return self._error

    def refresh(self) -> int:
        """Reload the canonical snapshot; external refresh belongs to DataHub ingestion."""
        if not self.load_cache():
            raise RuntimeError(self._error or "canonical DataHub ST truth unavailable")
        return len({record["symbol"] for record in self._st_map.values()})

    @staticmethod
    def _classify_st(name: str) -> str:
        normalized = name.upper().strip()
        if normalized.startswith("*ST"):
            return "star_st"
        if normalized.startswith("ST") or "ST" in normalized:
            return "st"
        return "unknown"

    def _build_index(self, records: list[dict]) -> None:
        self._st_map = {}
        for record in records:
            symbol = str(record.get("symbol", "")).strip()
            code = "".join(character for character in symbol if character.isdigit())[:6]
            if len(code) != 6:
                continue
            normalized = {**record, "symbol": code}
            self._st_map[code] = normalized

    def _load_json_snapshot(self) -> bool:
        try:
            payload = json.loads(self.CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        records = payload.get("stocks")
        if not isinstance(records, list):
            return False
        self._build_index(records)
        self._source_as_of = str(payload.get("updated_at") or "") or None
        return True

    def _load_stock_reference(self) -> bool:
        try:
            frame = pd.read_csv(self.CACHE_PATH, encoding="utf-8-sig", dtype="string")
        except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            self._error = f"canonical stock reference unreadable: {exc}"
            return False
        required = {"ts_code", "name", "list_status"}
        if frame.empty or not required.issubset(frame.columns):
            self._error = "canonical stock reference missing ts_code/name/list_status"
            return False
        active = frame[frame["list_status"].fillna("").str.strip().str.upper() == "L"]
        records = []
        for row in active.to_dict(orient="records"):
            raw_name = row.get("name")
            name = "" if raw_name is None or pd.isna(raw_name) else str(raw_name).strip()
            if not name.upper().startswith(("ST", "*ST")):
                continue
            raw_symbol = row.get("ts_code")
            symbol = "" if raw_symbol is None or pd.isna(raw_symbol) else str(raw_symbol).split(".")[0]
            records.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "st_type": self._classify_st(name),
                    "source": "DataHub reference/stock_basic.csv",
                }
            )
        self._build_index(records)
        self._source_as_of = datetime.fromtimestamp(self.CACHE_PATH.stat().st_mtime).astimezone().isoformat()
        return True

    def load_cache(self) -> bool:
        """Load a canonical CSV or an explicitly supplied versioned JSON snapshot."""
        if not self.CACHE_PATH.exists():
            self._error = f"canonical ST truth missing: {self.CACHE_PATH}"
            return False
        loaded = self._load_json_snapshot() if self.CACHE_PATH.suffix.lower() == ".json" else self._load_stock_reference()
        self._loaded = loaded
        if loaded:
            self._error = None
        return loaded

    def ensure_fresh(self) -> int:
        return self.refresh()

    def is_st(self, symbol: str) -> bool:
        if not self._loaded and not self.load_cache():
            return False
        code = "".join(character for character in symbol if character.isdigit())[:6]
        return len(code) == 6 and code in self._st_map

    def get_st_list(self) -> list[dict]:
        if not self._loaded and not self.load_cache():
            return []
        return [self._st_map[code] for code in sorted(self._st_map)]

    def get_st_status(self, symbol: str) -> str:
        if not self._loaded and not self.load_cache():
            return "unknown"
        code = "".join(character for character in symbol if character.isdigit())[:6]
        if len(code) != 6:
            return "unknown"
        record = self._st_map.get(code)
        return str(record.get("st_type", "st")) if record else "normal"


def is_st(symbol: str) -> bool:
    """Convenience query backed by the process-local canonical snapshot."""
    if not hasattr(is_st, "_watchlist"):
        is_st._watchlist = STWatchlist()
        is_st._watchlist.load_cache()
    return is_st._watchlist.is_st(symbol)
