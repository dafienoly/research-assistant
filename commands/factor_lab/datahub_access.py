"""Read-only access to canonical DataHub datasets for downstream modules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATAHUB_ROOT = Path(os.environ.get("HERMES_DATAHUB_ROOT", PROJECT_ROOT / "data" / "normalized"))
TRADE_CALENDAR_PATH = DATAHUB_ROOT / "calendar" / "trade_calendar.csv"
STOCK_BASIC_PATH = DATAHUB_ROOT / "reference" / "stock_basic.csv"
SHARED_DATAHUB_ROOT = Path(
    os.environ.get("HERMES_SHARED_DATAHUB_ROOT", "/mnt/c/Users/ly/.codex/data/a-share-data-hub")
)
LIVE_SNAPSHOT_PATH = SHARED_DATAHUB_ROOT / "market" / "live_snapshot.csv"


def _optional_number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _daily_kline_candidates() -> tuple[Path, ...]:
    return (
        SHARED_DATAHUB_ROOT / "market" / "daily_kline",
        PROJECT_ROOT / "data" / "market" / "daily_kline",
        DATAHUB_ROOT / "market",
    )


def _contains_daily_kline(root: Path) -> bool:
    if not root.is_dir():
        return False
    return any(path.is_file() and path.suffix.lower() == ".csv" and not path.name.startswith("valuation_") for path in root.iterdir())


@dataclass(frozen=True)
class FactorInputLocations:
    """Canonical locations consumed by factor research and validation."""

    daily_kline: Path
    fundamentals: Path
    fund_flow: Path
    north_flow: Path
    margin: Path
    events: Path
    sentiment: Path


def factor_input_locations() -> FactorInputLocations:
    """Resolve factor inputs once, with environment overrides owned by DataHub."""

    project_data = Path(os.environ.get("HERMES_FACTOR_DATA_ROOT", PROJECT_ROOT / "data"))
    candidates = _daily_kline_candidates()
    default_kline = next(
        (candidate for candidate in candidates if _contains_daily_kline(candidate)),
        candidates[0],
    )
    return FactorInputLocations(
        daily_kline=Path(os.environ.get("HERMES_FACTOR_KLINE_ROOT", default_kline)),
        fundamentals=project_data / "fundamentals" / "fundamentals_timeseries.csv",
        fund_flow=project_data / "fundamentals" / "fund_flow_timeseries.csv",
        north_flow=project_data / "north_flow_timeseries.csv",
        margin=project_data / "margin_timeseries.csv",
        events=project_data / "event_timeseries.csv",
        sentiment=project_data / "news_sentiment_timeseries.csv",
    )


def read_stock_industry_map(path: Path | None = None) -> dict[str, str]:
    """Read symbol-to-industry mapping from canonical DataHub reference data."""

    source = path or STOCK_BASIC_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub stock reference missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype={"symbol": "string"})
    required = {"symbol", "industry"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical stock reference missing columns: {sorted(required - set(frame.columns))}")
    usable = frame.loc[:, ["symbol", "industry"]].dropna()
    usable["symbol"] = usable["symbol"].str.strip().str.zfill(6)
    usable["industry"] = usable["industry"].astype("string").str.strip()
    usable = usable[(usable["symbol"] != "") & (usable["industry"] != "")]
    return dict(zip(usable["symbol"], usable["industry"], strict=False))


def read_stock_name_map(path: Path | None = None) -> dict[str, str]:
    """Read symbol-to-name mapping from canonical DataHub reference data."""
    source = path or STOCK_BASIC_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub stock reference missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype={"symbol": "string", "name": "string"})
    required = {"symbol", "name"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical stock reference missing columns: {sorted(required - set(frame.columns))}")
    usable = frame.loc[:, ["symbol", "name"]].dropna()
    usable["symbol"] = usable["symbol"].str.strip().str.zfill(6)
    usable["name"] = usable["name"].str.strip()
    usable = usable[(usable["symbol"] != "") & (usable["name"] != "")]
    return dict(zip(usable["symbol"], usable["name"], strict=False))


def read_live_snapshot(
    codes: list[str] | None = None,
    *,
    path: Path | None = None,
    max_age_seconds: int = 120,
    now: datetime | None = None,
) -> dict[str, dict]:
    """Read a fresh canonical intraday snapshot without provider access."""
    source = path or LIVE_SNAPSHOT_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub live snapshot missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype={"code": "string"})
    required = {"code", "last_price", "change_pct", "update_time", "source"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"canonical live snapshot missing columns: {sorted(required - set(frame.columns))}")
    observed = pd.to_datetime(frame["update_time"], errors="coerce", utc=True)
    latest = observed.max()
    if pd.isna(latest):
        raise ValueError("canonical live snapshot has no valid observation time")
    current = pd.Timestamp(now or datetime.now().astimezone())
    if current.tzinfo is None:
        current = current.tz_localize(datetime.now().astimezone().tzinfo)
    age_seconds = max(0.0, (current.tz_convert("UTC") - latest).total_seconds())
    if age_seconds > max_age_seconds:
        raise ValueError(f"canonical DataHub live snapshot stale: {age_seconds:.0f}s > {max_age_seconds}s")

    normalized = frame.copy()
    normalized["bare_code"] = normalized["code"].str.lower().str.replace(r"^(sh|sz|bj)", "", regex=True)
    normalized = normalized.drop_duplicates("bare_code", keep="last").set_index("bare_code")
    requested = codes or normalized.index.astype(str).tolist()
    result: dict[str, dict] = {}
    for requested_code in requested:
        key = str(requested_code).strip()
        bare = key.lower()[2:] if key.lower().startswith(("sh", "sz", "bj")) else key.lower()
        if bare not in normalized.index:
            continue
        row = normalized.loc[bare]
        raw_source = row.get("source")
        provider = "unknown" if raw_source is None or pd.isna(raw_source) else str(raw_source).strip()
        result[key] = {
            "code": key,
            "price": _optional_number(row.get("last_price")),
            "change_pct": _optional_number(row.get("change_pct")),
            "volume": _optional_number(row.get("volume")),
            "amount": _optional_number(row.get("amount")),
            "amplitude": _optional_number(row.get("amplitude")),
            "turnover_rate": _optional_number(row.get("turnover_rate")),
            "delay_seconds": int(age_seconds),
            "source": f"datahub:{provider or 'unknown'}",
            "observed_at": latest.isoformat(),
        }
    return result


def daily_kline_root() -> Path:
    for candidate in _daily_kline_candidates():
        if _contains_daily_kline(candidate):
            return candidate
    raise FileNotFoundError("canonical DataHub daily kline dataset missing")


def daily_kline_path(symbol: str, root: Path | None = None) -> Path:
    source_root = root or daily_kline_root()
    normalized = symbol.upper()
    code = normalized.split(".")[0]
    candidates = (
        source_root / f"{normalized}.csv",
        source_root / f"{code}.csv",
        source_root / f"{code}_daily_kline.csv",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    exchange_qualified = sorted(source_root.glob(f"{code}.*.csv"))
    if exchange_qualified:
        return exchange_qualified[0]
    raise FileNotFoundError(f"canonical DataHub daily kline missing for {normalized}")


def daily_kline_index(root: Path | None = None) -> dict[str, Path]:
    """Scan a daily dataset once for batch consumers instead of globbing per symbol."""
    source_root = root or daily_kline_root()
    index: dict[str, Path] = {}
    for path in source_root.iterdir():
        if not path.is_file() or path.suffix.lower() != ".csv" or path.name.startswith("valuation_"):
            continue
        code = path.name.split(".", 1)[0].replace("_daily_kline", "").strip()
        if code and code not in index:
            index[code] = path
    return index


def read_trade_calendar(path: Path | None = None) -> pd.DataFrame:
    source = path or TRADE_CALENDAR_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub trade calendar missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig")
    required = {"cal_date", "is_open"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical trade calendar missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.copy()
    frame["cal_date"] = frame["cal_date"].astype("string").str.replace(r"\.0$", "", regex=True)
    frame["is_open"] = pd.to_numeric(frame["is_open"], errors="coerce")
    return frame.dropna(subset=["cal_date", "is_open"])


def calendar_row(trading_date: date, path: Path | None = None) -> dict:
    target = trading_date.strftime("%Y%m%d")
    frame = read_trade_calendar(path)
    match = frame[frame["cal_date"].str.replace("-", "") == target]
    if match.empty:
        raise ValueError(f"canonical trade calendar has no row for {target}")
    return match.iloc[-1].to_dict()


def latest_open_date(on_or_before: date, *, lookback_days: int = 20, path: Path | None = None) -> date:
    frame = read_trade_calendar(path)
    parsed = pd.to_datetime(frame["cal_date"], format="%Y%m%d", errors="coerce")
    lower = pd.Timestamp(on_or_before - timedelta(days=lookback_days))
    upper = pd.Timestamp(on_or_before)
    eligible = parsed[(frame["is_open"] == 1) & parsed.between(lower, upper)].dropna()
    if eligible.empty:
        raise ValueError("canonical trade calendar has no recent open date")
    return eligible.max().date()
