"""Read-only access to canonical DataHub datasets for downstream modules."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATAHUB_ROOT = Path(os.environ.get("HERMES_DATAHUB_ROOT", PROJECT_ROOT / "data" / "normalized"))
TRADE_CALENDAR_PATH = DATAHUB_ROOT / "calendar" / "trade_calendar.csv"
STOCK_BASIC_PATH = DATAHUB_ROOT / "reference" / "stock_basic.csv"
ETF_HOLDINGS_PATH = DATAHUB_ROOT / "etf_holdings" / "holdings.csv"
NORTH_FLOW_PATH = PROJECT_ROOT / "data" / "north_flow_timeseries.csv"
SHARED_DATAHUB_ROOT = Path(
    os.environ.get("HERMES_SHARED_DATAHUB_ROOT", "/mnt/c/Users/ly/.codex/data/a-share-data-hub")
)
LIVE_SNAPSHOT_PATH = SHARED_DATAHUB_ROOT / "market" / "live_snapshot.csv"
MARKET_TURNOVER_PATH = DATAHUB_ROOT / "derived" / "market_turnover" / "daily.csv"


def _optional_number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _daily_kline_candidates() -> tuple[Path, ...]:
    equity_root = Path(
        os.environ.get("HERMES_CANONICAL_DAILY_ROOT", DATAHUB_ROOT / "market")
    )
    return (
        equity_root,
        DATAHUB_ROOT / "market_series" / "fund",
        DATAHUB_ROOT / "market_series" / "index",
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
    default_kline = _daily_kline_candidates()[0]
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
    frame = pd.read_csv(
        source, encoding="utf-8-sig", dtype={"symbol": "string", "ts_code": "string"}
    )
    if "symbol" not in frame and "ts_code" in frame:
        frame["symbol"] = frame["ts_code"]
    required = {"symbol", "industry"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical stock reference missing columns: {sorted(required - set(frame.columns))}")
    usable = frame.loc[:, ["symbol", "industry"]].dropna()
    usable["symbol"] = usable["symbol"].str.strip().str.split(".").str[0].str.zfill(6)
    usable["industry"] = usable["industry"].astype("string").str.strip()
    usable = usable[(usable["symbol"] != "") & (usable["industry"] != "")]
    return dict(zip(usable["symbol"], usable["industry"], strict=False))


def read_stock_name_map(path: Path | None = None) -> dict[str, str]:
    """Read symbol-to-name mapping from canonical DataHub reference data."""
    source = path or STOCK_BASIC_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub stock reference missing: {source}")
    frame = pd.read_csv(
        source,
        encoding="utf-8-sig",
        dtype={"symbol": "string", "ts_code": "string", "name": "string"},
    )
    if "symbol" not in frame and "ts_code" in frame:
        frame["symbol"] = frame["ts_code"]
    required = {"symbol", "name"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical stock reference missing columns: {sorted(required - set(frame.columns))}")
    usable = frame.loc[:, ["symbol", "name"]].dropna()
    usable["symbol"] = usable["symbol"].str.strip().str.split(".").str[0].str.zfill(6)
    usable["name"] = usable["name"].str.strip()
    usable = usable[(usable["symbol"] != "") & (usable["name"] != "")]
    return dict(zip(usable["symbol"], usable["name"], strict=False))


def read_fund_flow_partitions(symbols: list[str], root: Path | None = None) -> pd.DataFrame:
    """Read only requested canonical fund-flow partitions."""
    source_root = root or DATAHUB_ROOT / "fund_flow"
    frames: list[pd.DataFrame] = []
    for raw_symbol in sorted({str(symbol) for symbol in symbols}):
        digits = "".join(character for character in raw_symbol if character.isdigit())[:6]
        if len(digits) != 6:
            continue
        suffix = "SH" if digits.startswith(("6", "9")) else "BJ" if digits.startswith(("8", "4")) else "SZ"
        path = source_root / f"{digits}.{suffix}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"ts_code": "string"}, low_memory=False)
        required = {"trade_date", "net_mf_amount"}
        if frame.empty or not required.issubset(frame.columns):
            continue
        projected = pd.DataFrame({
            "symbol": digits,
            "date": frame["trade_date"],
            "net_main_force": frame["net_mf_amount"],
        })
        for prefix, output in (
            ("elg", "net_super_large"), ("lg", "net_large"),
            ("md", "net_medium"), ("sm", "net_small"),
        ):
            buy, sell = f"buy_{prefix}_amount", f"sell_{prefix}_amount"
            if buy in frame and sell in frame:
                projected[output] = pd.to_numeric(frame[buy], errors="coerce") - pd.to_numeric(frame[sell], errors="coerce")
        frames.append(projected)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"], kind="stable")


def read_etf_holdings(etf_code: str, path: Path | None = None) -> pd.DataFrame:
    """Read the latest holdings disclosure for one ETF from canonical DataHub."""
    source = path or ETF_HOLDINGS_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub ETF holdings missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype={"etf_code": "string", "symbol": "string"})
    required = {"etf_code", "symbol", "stk_mkv_ratio"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"canonical ETF holdings missing columns: {sorted(required - set(frame.columns))}")
    target = etf_code.upper()
    selected = frame[frame["etf_code"].str.upper() == target].copy()
    if selected.empty:
        return selected
    if "end_date" in selected.columns:
        dates = selected["end_date"].astype("string").str.replace(r"\.0$", "", regex=True)
        selected = selected[dates == dates.max()].copy()
    selected["stk_mkv_ratio"] = pd.to_numeric(selected["stk_mkv_ratio"], errors="coerce")
    return selected.dropna(subset=["symbol", "stk_mkv_ratio"]).sort_values("stk_mkv_ratio", ascending=False)


def read_latest_north_flow(path: Path | None = None) -> dict:
    """Read the latest canonical northbound-flow observation."""
    source = path or NORTH_FLOW_PATH
    if not source.exists():
        raise FileNotFoundError(f"canonical DataHub north flow missing: {source}")
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype={"trade_date": "string"})
    required = {"trade_date", "north_money"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"canonical north flow missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.copy()
    frame["trade_date"] = frame["trade_date"].str.replace(r"\.0$", "", regex=True)
    return frame.sort_values("trade_date", kind="stable").iloc[-1].to_dict()


def read_market_turnover(
    path: Path | None = None,
    *,
    minimum_days: int = 20,
    max_manifest_age_days: int = 7,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Read the governed all-market daily turnover projection."""
    source = path or MARKET_TURNOVER_PATH
    manifest_path = source.parent / "manifest.json"
    if not source.exists() or not manifest_path.exists():
        raise FileNotFoundError("canonical market turnover dataset or manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "OK":
        raise ValueError(f"canonical market turnover status is {manifest.get('status', 'MISSING')}")
    expected_hash = str(manifest.get("sha256", ""))
    actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("canonical market turnover hash mismatch")
    generated_at = datetime.fromisoformat(str(manifest.get("generated_at")))
    current = now or datetime.now().astimezone()
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=current.tzinfo)
    if current - generated_at > timedelta(days=max_manifest_age_days):
        raise ValueError("canonical market turnover manifest stale")
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype={"trade_date": "string"})
    required = {"trade_date", "market_amount"}
    if not required.issubset(frame.columns):
        raise ValueError(f"canonical market turnover missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.copy()
    frame["market_amount"] = pd.to_numeric(frame["market_amount"], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "market_amount"]).sort_values("trade_date")
    if len(frame) < minimum_days:
        raise ValueError(f"canonical market turnover history too short: {len(frame)} < {minimum_days}")
    return frame


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
    manifest_path = source.with_suffix(".manifest.json")
    if not manifest_path.exists():
        raise FileNotFoundError(f"canonical DataHub live snapshot manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "OK":
        raise ValueError(f"canonical live snapshot status is {manifest.get('status', 'MISSING')}")
    expected_hash = str(manifest.get("sha256", ""))
    actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if not expected_hash or expected_hash != actual_hash:
        raise ValueError("canonical live snapshot hash mismatch")
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
    manifest_observed = pd.to_datetime(manifest.get("observed_at"), errors="coerce", utc=True)
    if pd.isna(manifest_observed):
        raise ValueError("canonical live snapshot manifest has no valid observation time")
    manifest_age = max(0.0, (current.tz_convert("UTC") - manifest_observed).total_seconds())
    age_seconds = max(age_seconds, manifest_age)
    if age_seconds > max_age_seconds:
        raise ValueError(f"canonical DataHub live snapshot stale: {age_seconds:.0f}s > {max_age_seconds}s")

    normalized = frame.copy()
    normalized["bare_code"] = normalized["code"].str.lower().str.replace(r"^(sh|sz|bj)", "", regex=True)
    normalized = normalized.drop_duplicates("bare_code", keep="last").set_index("bare_code")
    requested = codes or normalized.index.astype(str).tolist()
    conflict_codes = {
        str(item.get("code", "")).lower()
        .removeprefix("sh")
        .removeprefix("sz")
        .removeprefix("bj")
        for item in manifest.get("conflicts", [])
        if isinstance(item, dict)
    }
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
            "name": None if pd.isna(row.get("name")) else str(row.get("name")),
            "price": _optional_number(row.get("last_price")),
            "change_pct": _optional_number(row.get("change_pct")),
            "open": _optional_number(row.get("open")),
            "high": _optional_number(row.get("high")),
            "low": _optional_number(row.get("low")),
            "volume": _optional_number(row.get("volume")),
            "amount": _optional_number(row.get("amount")),
            "amplitude": _optional_number(row.get("amplitude")),
            "turnover_rate": _optional_number(row.get("turnover_rate")),
            "delay_seconds": int(age_seconds),
            "source": f"datahub:{provider or 'unknown'}",
            "observed_at": latest.isoformat(),
            "conflict": bare in conflict_codes,
            "manifest_sha256": expected_hash,
        }
    return result


def daily_kline_root() -> Path:
    canonical = _daily_kline_candidates()[0]
    if _contains_daily_kline(canonical):
        return canonical
    raise FileNotFoundError(f"canonical DataHub equity daily dataset missing: {canonical}")


def daily_kline_path(symbol: str, root: Path | None = None) -> Path:
    normalized = symbol.upper()
    code = normalized.split(".")[0]
    roots = (root,) if root is not None else _daily_kline_candidates()
    matches: list[Path] = []
    for source_root in roots:
        candidates = (
            source_root / f"{normalized}.csv",
            source_root / f"{code}.csv",
            source_root / f"{code}_daily_kline.csv",
        )
        for candidate in candidates:
            if candidate.exists():
                matches.append(candidate)
        if source_root.is_dir():
            exchange_qualified = sorted(source_root.glob(f"{code}.*.csv"))
            if exchange_qualified:
                matches.extend(exchange_qualified)
    unique_matches = list(dict.fromkeys(path.resolve() for path in matches))
    if len(unique_matches) > 1:
        hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in unique_matches}
        if len(hashes) > 1:
            raise ValueError(
                f"canonical DataHub daily conflict for {normalized}: "
                + ", ".join(str(path) for path in unique_matches)
            )
    if unique_matches:
        return unique_matches[0]
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
