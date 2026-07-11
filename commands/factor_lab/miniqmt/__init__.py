"""Deprecated miniQMT API facade routed through governed infrastructure."""

from __future__ import annotations

import pandas as pd

from factor_lab.broker.miniqmt_position_adapter import MiniQMTPositionAdapter
from factor_lab.datahub_access import daily_kline_path, read_live_snapshot


_adapter = MiniQMTPositionAdapter()
_connected = False


def connect(account_id: str = "", password: str = "") -> bool:
    """Check the governed QMT Bridge; credentials are never accepted here."""
    del password
    global _adapter, _connected
    _adapter = MiniQMTPositionAdapter(account_id=account_id)
    _connected = _adapter.is_available()
    return _connected


def disconnect() -> None:
    global _connected
    _connected = False


def is_connected() -> bool:
    return _connected


def query_positions() -> list:
    """Read and normalize positions through QMT Bridge; failure is explicit."""
    if not _connected:
        raise RuntimeError("QMT Bridge is not connected")
    return _adapter.normalize_positions(_adapter.load_positions())


def query_account() -> dict:
    """Read account equity through QMT Bridge; failure is explicit."""
    if not _connected:
        raise RuntimeError("QMT Bridge is not connected")
    account = _adapter.load_account_asset()
    if account.get("status") != "ok":
        raise RuntimeError(account.get("error") or "QMT Bridge account unavailable")
    return account


def get_market_quote(symbols: list[str]) -> dict:
    """Read the freshness-gated canonical DataHub intraday snapshot."""
    return read_live_snapshot(symbols)


def get_kline(symbol: str, period: str = "1d", count: int = 120) -> list[dict]:
    """Read canonical daily bars; unsupported minute periods fail closed."""
    if period != "1d":
        raise ValueError("canonical minute K-line dataset unavailable")
    if count < 1:
        raise ValueError("count must be positive")
    frame = pd.read_csv(daily_kline_path(symbol), encoding="utf-8-sig", low_memory=False)
    date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else "timeString"
    volume_column = "volume" if "volume" in frame.columns else "vol"
    required = {date_column, "open", "high", "low", "close", volume_column}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical K-line missing columns: {sorted(required - set(frame.columns))}")
    selected = frame.tail(count)
    return [
        {
            "date": str(row[date_column]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row[volume_column]),
            "amount": float(row.get("amount", 0) or 0),
        }
        for _, row in selected.iterrows()
    ]


def place_order(symbol: str, amount: int, price: float = 0) -> dict:
    """Keep the legacy entry permanently blocked; governed execution is separate."""
    return {
        "status": "blocked",
        "reason": "legacy miniQMT facade is read-only; use governed approval and execution",
        "symbol": symbol,
        "amount": amount,
        "price": price,
    }
