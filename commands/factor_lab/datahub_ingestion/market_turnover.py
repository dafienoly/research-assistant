"""Materialize all-market daily turnover from canonical security partitions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from data_recovery import atomic_write_frame
from factor_lab.datahub_access import MARKET_TURNOVER_PATH, daily_kline_index


def build_market_turnover_projection(
    output_path: Path = MARKET_TURNOVER_PATH,
    *,
    history_days: int = 60,
) -> dict[str, object]:
    totals: dict[str, float] = {}
    files_with_amount = 0
    for path in daily_kline_index().values():
        frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        date_column = next((name for name in ("trade_date", "date", "timeString") if name in frame), None)
        if date_column is None or "amount" not in frame:
            continue
        dates = frame[date_column].astype("string").str.replace(r"\.0$", "", regex=True)
        # Canonical Tushare daily partitions store amount in thousands of CNY;
        # the intraday snapshot uses CNY, so normalize before publishing.
        amounts = pd.to_numeric(frame["amount"], errors="coerce") * 1_000.0
        valid = pd.DataFrame({"trade_date": dates, "market_amount": amounts}).dropna()
        valid = valid[valid["trade_date"].str.fullmatch(r"\d{8}")]
        if valid.empty:
            continue
        files_with_amount += 1
        for trade_date, amount in valid.groupby("trade_date")["market_amount"].sum().items():
            totals[str(trade_date)] = totals.get(str(trade_date), 0.0) + float(amount)
    frame = pd.DataFrame(
        sorted(totals.items()), columns=["trade_date", "market_amount"]
    ).tail(history_days)
    if len(frame) < 20:
        raise RuntimeError(f"market turnover projection has only {len(frame)} trading days")
    content_hash = atomic_write_frame(frame, output_path)
    manifest = {
        "status": "OK",
        "dataset": "derived/market_turnover",
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": "canonical_datahub_daily_partitions",
        "source_unit": "CNY_thousand",
        "unit": "CNY",
        "rows": len(frame),
        "source_files": files_with_amount,
        "path": output_path.name,
        "sha256": content_hash,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".manifest.", suffix=".tmp", dir=output_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output_path.parent / "manifest.json")
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return manifest
