"""Event-alpha features derived only from canonical DataHub corporate events."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
import pandas as pd

from factor_lab.datahub_access import DATAHUB_ROOT


CST = timezone(timedelta(hours=8))
CORPORATE_EVENT_ROOT = DATAHUB_ROOT / "events" / "corporate_events"
LOCKUP_COLUMNS = ["symbol", "date", "lockup_days_to_expiry", "lockup_count_90d"]
BUYBACK_COLUMNS = ["symbol", "date", "buyback_count_30d", "buyback_count_90d", "buyback_active"]
DIVIDEND_COLUMNS = ["symbol", "date", "dividend_yield", "dividend_days_since", "dividend_amount"]
FORECAST_COLUMNS = ["symbol", "date", "forecast_type_code", "forecast_days_since", "forecast_count_90d", "forecast_momentum"]
FORECAST_TYPE_MAP = {
    "预增": 1.0, "略增": 0.5, "预减": -1.0, "略减": -0.5,
    "扭亏": 0.8, "续亏": -0.8, "首亏": -1.0, "预盈": 0.3,
    "减亏": 0.2, "不确定": 0.0,
}


def _normalized_symbols(symbols: list | None) -> set[str] | None:
    if not symbols:
        return None
    return {"".join(character for character in str(symbol) if character.isdigit())[:6] for symbol in symbols}


def _load_canonical(dataset: str, symbols: list | None = None) -> pd.DataFrame:
    """Load one owned event dataset; malformed partitions fail closed individually."""
    if not CORPORATE_EVENT_ROOT.is_dir():
        return pd.DataFrame()
    requested = _normalized_symbols(symbols)
    paths = sorted(CORPORATE_EVENT_ROOT.glob("*.csv"))
    if requested is not None:
        paths = [path for path in paths if path.stem.split(".")[0] in requested]
    frames = []
    for path in paths:
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"ts_code": "string"}, low_memory=False)
        except (OSError, pd.errors.ParserError, UnicodeError):
            continue
        required = {"ts_code", "event_dataset", "event_date", "payload", "source_provider", "observed_at"}
        if frame.empty or not required.issubset(frame.columns):
            continue
        selected = frame[frame["event_dataset"] == dataset].copy()
        if selected.empty:
            continue
        selected["symbol"] = selected["ts_code"].str.split(".").str[0]
        selected["event_date"] = pd.to_datetime(selected["event_date"].astype(str), format="%Y%m%d", errors="coerce")
        selected["payload_data"] = selected["payload"].map(_parse_payload)
        frames.append(selected.dropna(subset=["event_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parse_payload(raw: object) -> dict:
    try:
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def load_lockup_events(symbols: list = None) -> pd.DataFrame:
    events = _load_canonical("share_float", symbols)
    if events.empty:
        return pd.DataFrame(columns=LOCKUP_COLUMNS)
    today = pd.Timestamp.now().normalize()
    events["float_date"] = events["payload_data"].map(lambda item: item.get("float_date"))
    events["effective_date"] = pd.to_datetime(events["float_date"].astype(str), format="%Y%m%d", errors="coerce").fillna(events["event_date"])
    recent = events[events["effective_date"] >= today - pd.Timedelta(days=90)].groupby("symbol").size()
    latest = events.sort_values("effective_date").groupby("symbol").tail(1).copy()
    latest["lockup_days_to_expiry"] = (latest["effective_date"] - today).dt.days
    latest["lockup_count_90d"] = latest["symbol"].map(recent).fillna(0).astype(int)
    latest["date"] = today.strftime("%Y-%m-%d")
    return latest[LOCKUP_COLUMNS].reset_index(drop=True)


def load_buyback_events(symbols: list = None) -> pd.DataFrame:
    events = _load_canonical("repurchase", symbols)
    if events.empty:
        return pd.DataFrame(columns=BUYBACK_COLUMNS)
    today = pd.Timestamp.now().normalize()
    count_30 = events[events["event_date"] >= today - pd.Timedelta(days=30)].groupby("symbol").size()
    count_90 = events[events["event_date"] >= today - pd.Timedelta(days=90)].groupby("symbol").size()
    result = pd.DataFrame({"symbol": sorted(events["symbol"].unique())})
    result["buyback_count_30d"] = result["symbol"].map(count_30).fillna(0).astype(int)
    result["buyback_count_90d"] = result["symbol"].map(count_90).fillna(0).astype(int)
    result["buyback_active"] = (result["buyback_count_30d"] > 0).astype(int)
    result["date"] = today.strftime("%Y-%m-%d")
    return result[BUYBACK_COLUMNS]


def load_dividend_events(symbols: list = None) -> pd.DataFrame:
    events = _load_canonical("dividend", symbols)
    if events.empty:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS)
    today = pd.Timestamp.now().normalize()
    events["dividend_amount"] = pd.to_numeric(events["payload_data"].map(lambda item: item.get("cash_div_tax", item.get("cash_div", 0))), errors="coerce").fillna(0)
    events["ex_date"] = pd.to_datetime(events["payload_data"].map(lambda item: item.get("ex_date")).astype(str), format="%Y%m%d", errors="coerce")
    events["effective_date"] = events["ex_date"].fillna(events["event_date"])
    latest = events.sort_values("effective_date").groupby("symbol").tail(1).copy()
    latest["dividend_days_since"] = (today - latest["effective_date"]).dt.days
    latest["dividend_yield"] = 0.0  # no price denominator is fabricated in the event loader
    latest["date"] = today.strftime("%Y-%m-%d")
    return latest[DIVIDEND_COLUMNS].reset_index(drop=True)


def load_forecast_events(symbols: list = None) -> pd.DataFrame:
    events = _load_canonical("forecast", symbols)
    if events.empty:
        return pd.DataFrame(columns=FORECAST_COLUMNS)
    today = pd.Timestamp.now().normalize()
    events["forecast_type_code"] = events["payload_data"].map(
        lambda item: FORECAST_TYPE_MAP.get(str(item.get("type", item.get("forecast_type", "不确定"))), 0.0)
    )
    count_90 = events[events["event_date"] >= today - pd.Timedelta(days=90)].groupby("symbol").size()
    momentum = events.groupby("symbol")["forecast_type_code"].sum()
    latest = events.sort_values("event_date").groupby("symbol").tail(1).copy()
    latest["forecast_days_since"] = (today - latest["event_date"]).dt.days
    latest["forecast_count_90d"] = latest["symbol"].map(count_90).fillna(0).astype(int)
    latest["forecast_momentum"] = latest["symbol"].map(momentum).fillna(0.0)
    latest["date"] = today.strftime("%Y-%m-%d")
    return latest[FORECAST_COLUMNS].reset_index(drop=True)


def get_event_data(symbols: list = None) -> dict:
    data = {
        "lockup": load_lockup_events(symbols),
        "buyback": load_buyback_events(symbols),
        "dividend": load_dividend_events(symbols),
        "forecast": load_forecast_events(symbols),
    }
    return {**data, **{f"has_{name}": not frame.empty for name, frame in data.items()}}


def merge_event_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "symbol" not in df.columns:
        return df
    result = df.copy()
    result["symbol"] = result["symbol"].astype(str).str.split(".").str[0].str.zfill(6)
    events = get_event_data(result["symbol"].unique().tolist())
    for name, columns in (("lockup", LOCKUP_COLUMNS), ("buyback", BUYBACK_COLUMNS), ("dividend", DIVIDEND_COLUMNS), ("forecast", FORECAST_COLUMNS)):
        if not events[f"has_{name}"]:
            continue
        merge_columns = [column for column in columns if column not in ("symbol", "date")]
        result = result.merge(events[name][["symbol", *merge_columns]], on="symbol", how="left")
        result[merge_columns] = result[merge_columns].fillna(0)
    return result


def event_data_status() -> dict:
    datasets = {}
    for dataset in ("share_float", "repurchase", "dividend", "forecast"):
        frame = _load_canonical(dataset)
        datasets[dataset] = {"status": "OK" if not frame.empty else "MISSING", "rows": len(frame)}
    overall = "OK" if all(item["status"] == "OK" for item in datasets.values()) else "PARTIAL"
    return {
        "status": overall,
        "source": "canonical_datahub_corporate_events",
        "root": str(CORPORATE_EVENT_ROOT),
        "datasets": datasets,
        "checked_at": datetime.now(CST).isoformat(),
    }


if __name__ == "__main__":
    print(json.dumps(event_data_status(), ensure_ascii=False, indent=2))
