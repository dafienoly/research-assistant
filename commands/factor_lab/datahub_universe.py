"""Read-only, batched DataHub projection for universe construction."""

from __future__ import annotations

import csv
import math
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def _tail_records(path: Path, limit: int) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = handle.readline()
            if not header:
                return []
            rows = deque(handle, maxlen=limit)
        return list(csv.DictReader([header, *rows]))
    except (OSError, UnicodeError, csv.Error):
        return []


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


@dataclass
class UniverseDataHubSnapshot:
    """One-build snapshot that batches per-symbol CSV reads and reuses them."""

    stock_basic_path: Path
    trade_calendar_path: Path
    suspension_path: Path
    market_dir: Path
    max_workers: int = 32
    _valuations: dict[str, dict[str, float | None]] = field(default_factory=dict, init=False)
    _liquidity: dict[str, tuple[float | None, float]] = field(default_factory=dict, init=False)
    _loaded_valuations: set[str] = field(default_factory=set, init=False)
    _loaded_liquidity: set[str] = field(default_factory=set, init=False)

    def stock_reference(self) -> pd.DataFrame:
        if not self.stock_basic_path.exists():
            raise RuntimeError(f"canonical DataHub stock_basic missing: {self.stock_basic_path}")
        try:
            frame = pd.read_csv(self.stock_basic_path, encoding="utf-8-sig", dtype="string")
        except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise RuntimeError(f"canonical DataHub stock_basic unreadable: {exc}") from exc
        required = {"ts_code", "symbol", "name", "market", "list_status"}
        if frame.empty or not required.issubset(frame.columns):
            missing = sorted(required - set(frame.columns))
            raise RuntimeError(f"canonical DataHub stock_basic invalid: missing {missing}")
        frame = frame.dropna(subset=["ts_code"]).copy()
        frame["ts_code"] = frame["ts_code"].str.strip().str.upper()
        frame["list_status"] = frame["list_status"].fillna("").str.strip().str.upper()
        return frame.drop_duplicates("ts_code", keep="last")

    def latest_open_trade_date(self, now: datetime) -> str:
        if not self.trade_calendar_path.exists():
            raise RuntimeError(f"canonical DataHub trade calendar missing: {self.trade_calendar_path}")
        try:
            frame = pd.read_csv(self.trade_calendar_path, encoding="utf-8-sig")
        except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise RuntimeError(f"canonical DataHub trade calendar unreadable: {exc}") from exc
        dates = pd.to_datetime(frame.get("cal_date"), format="%Y%m%d", errors="coerce")
        is_open = pd.to_numeric(frame.get("is_open"), errors="coerce")
        eligible = dates[(is_open == 1) & (dates <= pd.Timestamp(now.date()))].dropna()
        if eligible.empty:
            raise RuntimeError("canonical DataHub trade calendar has no open date")
        return eligible.max().strftime("%Y%m%d")

    def suspended_on(self, trade_date: str) -> set[str]:
        if not self.suspension_path.exists():
            return set()
        try:
            frame = pd.read_csv(self.suspension_path, encoding="utf-8-sig", dtype="string")
        except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
            return set()
        required = {"ts_code", "trade_date"}
        if frame.empty or not required.issubset(frame.columns):
            return set()
        dates = frame["trade_date"].str.replace(r"\.0$", "", regex=True)
        return set(frame.loc[dates == trade_date, "ts_code"].dropna().str.strip().str.upper())

    def load_valuations(self, codes: Iterable[str]) -> None:
        pending = sorted(set(codes) - self._loaded_valuations)
        if not pending:
            return
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(pending))) as pool:
            for code, value in pool.map(self._read_valuation, pending):
                self._valuations[code] = value
        self._loaded_valuations.update(pending)

    def load_liquidity(self, codes: Iterable[str]) -> None:
        pending = sorted(set(codes) - self._loaded_liquidity)
        if not pending:
            return
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(pending))) as pool:
            for code, value in pool.map(self._read_liquidity, pending):
                self._liquidity[code] = value
        self._loaded_liquidity.update(pending)

    def valuation(self, ts_code: str) -> dict[str, float | None]:
        return self._valuations.get(ts_code, {})

    def liquidity(self, ts_code: str) -> tuple[float | None, float]:
        return self._liquidity.get(ts_code, (None, 0.0))

    def daily_volatility(self, ts_code: str) -> float | None:
        rows = _tail_records(self.market_dir / f"{ts_code}.csv", 60)
        if not rows:
            return None
        pct_changes = [_number(row.get("pct_chg")) for row in rows]
        usable = [value for value in pct_changes if value is not None]
        if len(usable) < 2:
            closes = [_number(row.get("close")) for row in rows]
            close_series = pd.Series([value for value in closes if value is not None], dtype="float64")
            usable = (close_series.pct_change().dropna() * 100).tolist()
        if len(usable) < 2:
            return None
        value = pd.Series(usable, dtype="float64").std()
        return float(value) if pd.notna(value) else None

    def _read_valuation(self, ts_code: str) -> tuple[str, dict[str, float | None]]:
        rows = _tail_records(self.market_dir / f"valuation_{ts_code}.csv", 1)
        if not rows:
            return ts_code, {}
        row = rows[-1]
        return ts_code, {
            "total_mv": _number(row.get("total_mv")),
            "float_mv": _number(row.get("circ_mv")),
            "turnover_rate": _number(row.get("turnover_rate")),
            "pe": _number(row.get("pe")),
            "pb": _number(row.get("pb")),
        }

    def _read_liquidity(self, ts_code: str) -> tuple[str, tuple[float | None, float]]:
        rows = _tail_records(self.market_dir / f"{ts_code}.csv", 20)
        amounts = [_number(row.get("amount")) for row in rows]
        usable = [value for value in amounts if value is not None]
        latest = usable[-1] if usable else None
        average = sum(usable) / len(usable) if usable else 0.0
        return ts_code, (latest, average)
