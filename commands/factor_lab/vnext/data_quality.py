"""Multi-asset universe and fail-visible data quality/freshness gates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .contracts import DataStatus, SourceObservation, Tradability, now_iso


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(slots=True)
class AssetRecord:
    symbol: str
    name: str
    market: str
    asset_class: str
    role: str
    tradability: Tradability
    board: str = ""
    substitute_symbol: str | None = None
    data_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "asset_class": self.asset_class,
            "role": self.role,
            "tradability": self.tradability.value,
            "board": self.board,
            "substitute_symbol": self.substitute_symbol,
            "data_source": self.data_source,
            "metadata": self.metadata,
        }


class MultiAssetUniverseRegistry:
    """Registry that keeps research visibility separate from account tradability."""

    def __init__(self, assets: Iterable[AssetRecord] = ()) -> None:
        self._assets = {asset.symbol: asset for asset in assets}

    @classmethod
    def from_file(cls, path: str | Path) -> "MultiAssetUniverseRegistry":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"universe registry missing: {config_path}")
        raw = config_path.read_text(encoding="utf-8")
        if config_path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError("PyYAML is required to load the VNext universe registry") from exc
            data = yaml.safe_load(raw)
        records: list[AssetRecord] = []
        for item in data.get("assets", []):
            records.append(
                AssetRecord(
                    symbol=str(item["symbol"]),
                    name=str(item.get("name", item["symbol"])),
                    market=str(item.get("market", "UNKNOWN")),
                    asset_class=str(item.get("asset_class", "unknown")),
                    role=str(item.get("role", "watch")),
                    tradability=Tradability(item.get("tradability", Tradability.WATCH_ONLY.value)),
                    board=str(item.get("board", "")),
                    substitute_symbol=item.get("substitute_symbol"),
                    data_source=str(item.get("data_source", "")),
                    metadata=dict(item.get("metadata", {})),
                )
            )
        return cls(records)

    def register(self, asset: AssetRecord) -> None:
        self._assets[asset.symbol] = asset

    def list(self, *, role: str | None = None) -> list[dict[str, Any]]:
        values = self._assets.values()
        if role:
            values = (asset for asset in values if asset.role == role)
        return [asset.to_dict() for asset in values]

    def execution_candidates(self) -> list[dict[str, Any]]:
        allowed = {Tradability.TRADABLE, Tradability.ETF_SUBSTITUTION, Tradability.RISK_HEDGE}
        return [asset.to_dict() for asset in self._assets.values() if asset.tradability in allowed]

    def validate_account_rules(self) -> list[str]:
        violations: list[str] = []
        for asset in self._assets.values():
            restricted_board = asset.board.upper() in {"CHINEXT", "STAR", "BSE"}
            if restricted_board and asset.asset_class == "stock" and asset.tradability in {
                Tradability.TRADABLE,
                Tradability.EXECUTION_CANDIDATE,
            }:
                violations.append(f"{asset.symbol}: restricted board stock marked executable")
            if asset.tradability == Tradability.ETF_SUBSTITUTION and asset.asset_class != "etf":
                violations.append(f"{asset.symbol}: substitution is not an ETF")
        return violations


class DataQualityGate:
    """Evaluate source existence, completeness and freshness without substitution."""

    def __init__(self, max_age_days: int = 2) -> None:
        self.max_age_days = max(0, int(max_age_days))

    def inspect_file(
        self,
        source: str,
        path: str | Path,
        *,
        required_fields: Iterable[str] = (),
        as_of: date | None = None,
        updated_at: str | None = None,
    ) -> SourceObservation:
        file_path = Path(path)
        required = list(required_fields)
        if not file_path.exists():
            return SourceObservation(
                source=source,
                status=DataStatus.MISSING,
                updated_at=None,
                required_fields=required,
                missing_fields=required,
                path=str(file_path),
                records=0,
                message="source file does not exist",
            )

        observed_time = _parse_time(updated_at) or datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=timezone.utc,
        )
        target = as_of or date.today()
        age_days = max(0, (target - observed_time.date()).days)
        status = DataStatus.STALE if age_days > self.max_age_days else DataStatus.OK
        records: int | None = None
        fields: set[str] = set()
        try:
            suffix = file_path.suffix.lower()
            if suffix == ".json":
                payload = json.loads(file_path.read_text(encoding="utf-8"))
                fields = set(payload.keys()) if isinstance(payload, dict) else set()
                records = len(payload) if isinstance(payload, list) else 1
            elif suffix in {".csv", ".tsv"}:
                import csv

                delimiter = "\t" if suffix == ".tsv" else ","
                with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle, delimiter=delimiter)
                    fields = set(reader.fieldnames or [])
                    records = sum(1 for _ in reader)
            else:
                records = 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return SourceObservation(
                source=source,
                status=DataStatus.PARTIAL,
                updated_at=observed_time.isoformat(),
                required_fields=required,
                missing_fields=required,
                path=str(file_path),
                records=records,
                message=f"source cannot be parsed: {type(exc).__name__}",
            )

        missing = sorted(set(required) - fields) if required else []
        if missing:
            status = DataStatus.PARTIAL
        if records == 0:
            status = DataStatus.MISSING
        return SourceObservation(
            source=source,
            status=status,
            updated_at=observed_time.isoformat(),
            required_fields=required,
            missing_fields=missing,
            path=str(file_path),
            records=records,
            message=f"age_days={age_days}",
        )

    def summarize(self, observations: Iterable[SourceObservation]) -> dict[str, Any]:
        items = list(observations)
        statuses = [item.status for item in items]
        if not items or all(status == DataStatus.MISSING for status in statuses):
            overall = DataStatus.MISSING
        elif any(status in {DataStatus.MISSING, DataStatus.PARTIAL} for status in statuses):
            overall = DataStatus.PARTIAL
        elif any(status == DataStatus.STALE for status in statuses):
            overall = DataStatus.STALE
        else:
            overall = DataStatus.OK
        usable = sum(status == DataStatus.OK for status in statuses)
        return {
            "status": overall.value,
            "updated_at": now_iso(),
            "sources_total": len(items),
            "sources_ok": usable,
            "confidence": round(usable / len(items), 4) if items else 0.0,
            "items": [item.to_dict() for item in items],
            "missing_evidence": [
                item.source for item in items if item.status in {DataStatus.MISSING, DataStatus.PARTIAL, DataStatus.STALE}
            ],
        }
