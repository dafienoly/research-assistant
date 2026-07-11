"""Single-writer ingestion for the canonical DataHub live snapshot."""

from __future__ import annotations

import fcntl
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from config import safe_write_json
from data_recovery import atomic_write_frame
from factor_lab.datahub_access import LIVE_SNAPSHOT_PATH
from rsscast_mcp import fetch_akshare_spot, fetch_stock_prices


SNAPSHOT_FIELDS = [
    "code", "name", "last_price", "change_pct", "change_amount", "volume",
    "amount", "amplitude", "turnover_rate", "pe", "pb", "open", "high",
    "low", "source", "update_time",
]


class LiveSnapshotIngestion:
    """Fetch provider data once and atomically publish canonical market truth."""

    def __init__(
        self,
        output_path: Path = LIVE_SNAPSHOT_PATH,
        *,
        full_market_fetcher: Callable[[], list[dict]] = fetch_akshare_spot,
        priority_fetcher: Callable[[list[str]], list[dict]] = fetch_stock_prices,
    ) -> None:
        self.output_path = output_path
        self.full_market_fetcher = full_market_fetcher
        self.priority_fetcher = priority_fetcher

    def fetch_locked(self, priority_codes: list[str] | None = None) -> dict:
        """Publish under the same lock used by backup, restore, and batch writers."""
        lock_path = Path.home() / ".hermes/locks/datahub-global.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("datahub writer active; live snapshot deferred") from error
            return self.fetch(priority_codes)

    def fetch(self, priority_codes: list[str] | None = None) -> dict:
        observed_at = datetime.now().astimezone().isoformat()
        full_market = self.full_market_fetcher() or []
        if not full_market:
            raise RuntimeError("live snapshot provider returned empty; canonical snapshot preserved")
        priority = self.priority_fetcher(priority_codes) if priority_codes else []
        merged: dict[str, dict] = {}
        conflicts: list[dict] = []
        for provider_rank, row in enumerate([*full_market, *(priority or [])]):
            code = str(row.get("code", "")).strip()
            if not code:
                continue
            normalized = {
                "code": code,
                "name": row.get("name", ""),
                "last_price": row.get("last_price", row.get("最新价")),
                "change_pct": row.get("change_pct", row.get("涨跌幅")),
                "change_amount": row.get("change_amount", row.get("涨跌额")),
                "volume": row.get("volume", row.get("成交量")),
                "amount": row.get("amount", row.get("成交额")),
                "amplitude": row.get("amplitude", row.get("振幅")),
                "turnover_rate": row.get("turnover_rate", row.get("换手率")),
                "pe": row.get("pe", row.get("市盈率-动态")),
                "pb": row.get("pb", row.get("市净率")),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "source": row.get("source", "akshare"),
                "update_time": observed_at,
            }
            previous = merged.get(code)
            if previous:
                differing = {
                    field: {"previous": previous.get(field), "replacement": normalized.get(field)}
                    for field in ("last_price", "change_pct", "volume", "amount")
                    if previous.get(field) is not None
                    and normalized.get(field) is not None
                    and str(previous.get(field)) != str(normalized.get(field))
                }
                if differing:
                    conflicts.append(
                        {
                            "code": code,
                            "previous_source": previous.get("source"),
                            "replacement_source": normalized.get("source"),
                            "fields": differing,
                            "resolution": "later_priority_provider_wins",
                            "provider_rank": provider_rank,
                        }
                    )
            merged[code] = normalized
        if not merged:
            raise RuntimeError("live snapshot normalization returned empty; canonical snapshot preserved")
        frame = pd.DataFrame(merged.values(), columns=SNAPSHOT_FIELDS).sort_values("code", kind="stable")
        content_hash = atomic_write_frame(frame, self.output_path)
        manifest = {
            "status": "OK",
            "dataset": "market/live_snapshot",
            "observed_at": observed_at,
            "rows": len(frame),
            "priority_rows": len(priority or []),
            "path": self.output_path.name,
            "sha256": content_hash,
            "source": "akshare_spot_with_priority_override",
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
        }
        safe_write_json(self.output_path.with_suffix(".manifest.json"), manifest)
        return manifest
