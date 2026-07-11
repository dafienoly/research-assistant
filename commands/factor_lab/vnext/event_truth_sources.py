"""Read-only VNext access to canonical DataHub event truth."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


# Compatibility alias for callers while provider ownership moves to DataHub.
EventTruthSourceBuilder = EventTruthIngestion


def load_event_truth(project_root: Path, symbol: str) -> pd.DataFrame:
    path = project_root / "data/normalized/events/event_truth" / f"{symbol}.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, dtype={"trade_date": str})
    if frame.empty or "trade_date" not in frame:
        return pd.DataFrame()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    return frame.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last").set_index("trade_date")
