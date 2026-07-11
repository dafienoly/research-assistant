"""OpenBB-inspired provider/fetcher/router boundary owned by Hermes.

Primary-provider failures never promote an alternative observation to primary.
Every successful or failed fetch is represented by a MarketDataEnvelope and can
be persisted as an immutable snapshot manifest.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import pandas as pd
from pydantic import Field

from .contracts import (
    ContractModel,
    MarketDataEnvelope,
    QualityStatus,
    aware_now,
    sha256_payload,
)


class ProviderQuery(ContractModel):
    dataset: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    as_of: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    schema_version: str = "1.1"
    requested_at: datetime = Field(default_factory=aware_now)


class DataQualityAssessment(ContractModel):
    status: QualityStatus
    coverage: float = Field(ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    records: int = Field(ge=0)


class ProviderConflictRecord(ContractModel):
    dataset: str
    instrument_id: str
    as_of: str
    primary_provider: str
    alternative_provider: str
    primary_content_hash: str
    alternative_content_hash: str
    reason: str
    resolution: str = "PRIMARY_RETAINED_REVIEW_REQUIRED"


class AlternativeObservation(ContractModel):
    provider: str
    primary_provider: str
    used_as_primary: bool = False
    envelope: MarketDataEnvelope
    reason: str


class ProviderRouteResult(ContractModel):
    status: QualityStatus
    primary: MarketDataEnvelope
    alternatives: list[AlternativeObservation] = Field(default_factory=list)
    conflicts: list[ProviderConflictRecord] = Field(default_factory=list)
    silent_fallback_used: bool = False
    snapshot_manifest_paths: list[str] = Field(default_factory=list)


class DataFetcher(Protocol):
    provider_name: str

    def transform_query(self, query: ProviderQuery) -> Mapping[str, Any]:
        """Translate Hermes query fields to provider-specific parameters."""
        raise TypeError("DataFetcher Protocol cannot transform directly")

    def extract_data(self, query: Mapping[str, Any]) -> pd.DataFrame:
        """Read provider data without changing Hermes contract semantics."""
        raise TypeError("DataFetcher Protocol cannot extract directly")

    def transform_data(self, raw: pd.DataFrame, query: ProviderQuery) -> pd.DataFrame:
        """Normalize provider output into a DataFrame."""
        raise TypeError("DataFetcher Protocol cannot transform data directly")

    def assess_quality(self, data: pd.DataFrame, query: ProviderQuery) -> DataQualityAssessment:
        """Assess fields and coverage without substituting another provider."""
        raise TypeError("DataFetcher Protocol cannot assess directly")

    def fetch(self, query: ProviderQuery) -> MarketDataEnvelope:
        """Return a fail-visible Hermes MarketDataEnvelope."""
        raise TypeError("DataFetcher Protocol cannot fetch directly")


class FrameFetcher(ABC):
    provider_name = "unknown"

    def transform_query(self, query: ProviderQuery) -> Mapping[str, Any]:
        return dict(query.params)

    @abstractmethod
    def extract_data(self, query: Mapping[str, Any]) -> pd.DataFrame:
        """Provider-specific read implementation."""
        raise TypeError("FrameFetcher abstract method cannot extract directly")

    def transform_data(self, raw: pd.DataFrame, query: ProviderQuery) -> pd.DataFrame:
        return raw.copy()

    def assess_quality(self, data: pd.DataFrame, query: ProviderQuery) -> DataQualityAssessment:
        missing = [field for field in query.required_fields if field not in data.columns]
        if data.empty:
            status = QualityStatus.MISSING
            coverage = 0.0
        elif missing:
            status = QualityStatus.PARTIAL
            coverage = max(0.0, 1.0 - len(missing) / max(len(query.required_fields), 1))
        else:
            status = QualityStatus.OK
            coverage = 1.0
        return DataQualityAssessment(
            status=status,
            coverage=coverage,
            missing_fields=missing,
            warnings=[],
            records=len(data),
        )

    def fetch(self, query: ProviderQuery) -> MarketDataEnvelope:
        try:
            raw = self.extract_data(self.transform_query(query))
            frame = self.transform_data(raw, query)
            quality = self.assess_quality(frame, query)
            records = _records(frame)
            observed_at, available_at = _point_in_time(frame, query)
            warnings = quality.warnings
        except Exception as exc:
            records = []
            quality = DataQualityAssessment(
                status=QualityStatus.PROVIDER_ERROR,
                coverage=0.0,
                missing_fields=list(query.required_fields),
                warnings=[f"{type(exc).__name__}: provider fetch failed"],
                records=0,
            )
            observed_at = query.requested_at
            available_at = query.requested_at
            warnings = quality.warnings
        content_hash = sha256_payload(records)
        # requested_at is operational metadata, not query semantics. Excluding
        # it makes retries/resume idempotent for the same provider request.
        query_hash = sha256_payload(query.model_dump(mode="json", exclude={"requested_at"}))
        return MarketDataEnvelope(
            dataset=query.dataset,
            instrument_id=query.instrument_id,
            provider=self.provider_name,
            requested_at=query.requested_at,
            observed_at=observed_at,
            available_at=available_at,
            ingested_at=max(aware_now(), available_at),
            as_of=query.as_of,
            quality_status=quality.status,
            coverage=quality.coverage,
            missing_fields=quality.missing_fields,
            warnings=warnings,
            raw_snapshot_id=f"{self.provider_name}-{query.dataset}-{query_hash[:10]}-{content_hash[:12]}",
            content_hash=content_hash,
            schema_version=query.schema_version,
            lineage={
                "provider": self.provider_name,
                "query_hash": query_hash,
                "records": quality.records,
                "primary_source": True,
            },
            data=records,
        )


class TushareFetcher(FrameFetcher):
    provider_name = "tushare"

    def __init__(self, client: Any) -> None:
        self.client = client

    def transform_query(self, query: ProviderQuery) -> Mapping[str, Any]:
        params = dict(query.params)
        api_name = str(params.pop("api_name", query.dataset))
        return {"api_name": api_name, "params": params}

    def extract_data(self, query: Mapping[str, Any]) -> pd.DataFrame:
        if self.client is None:
            raise RuntimeError("Tushare client unavailable")
        frame = self.client._query(str(query["api_name"]), **dict(query["params"]))
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


class LocalCsvFetcher(FrameFetcher):
    provider_name = "local_csv"

    def __init__(self, allowed_roots: list[str | Path]) -> None:
        self.allowed_roots = [Path(root).resolve() for root in allowed_roots]

    def extract_data(self, query: Mapping[str, Any]) -> pd.DataFrame:
        if "path" not in query:
            raise ValueError("local CSV query requires path")
        path = Path(str(query["path"])).resolve()
        if not any(path == root or root in path.parents for root in self.allowed_roots):
            raise PermissionError("local CSV path is outside allowed roots")
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, encoding=str(query.get("encoding", "utf-8-sig")))

    def transform_data(self, raw: pd.DataFrame, query: ProviderQuery) -> pd.DataFrame:
        frame = raw.copy()
        as_of_field = str(query.params.get("as_of_field", ""))
        if as_of_field and as_of_field in frame:
            parsed = _parse_datetime_series(frame[as_of_field])
            cutoff = pd.Timestamp(query.as_of).date()
            frame = frame.loc[parsed.map(lambda value: pd.notna(value) and value.date() <= cutoff)].copy()
        return frame


class CallableFrameFetcher(FrameFetcher):
    def __init__(self, provider_name: str, reader: Callable[[Mapping[str, Any]], pd.DataFrame] | None) -> None:
        self.provider_name = provider_name
        self.reader = reader

    def extract_data(self, query: Mapping[str, Any]) -> pd.DataFrame:
        if self.reader is None:
            raise RuntimeError(f"{self.provider_name} reader is not configured")
        frame = self.reader(query)
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


class AkShareFetcher(CallableFrameFetcher):
    def __init__(self, reader: Callable[[Mapping[str, Any]], pd.DataFrame] | None = None) -> None:
        super().__init__("akshare", reader)


class TencentQuoteFetcher(CallableFrameFetcher):
    def __init__(self, reader: Callable[[Mapping[str, Any]], pd.DataFrame] | None = None) -> None:
        super().__init__("tencent", reader)


class EastMoneyFetcher(CallableFrameFetcher):
    def __init__(self, reader: Callable[[Mapping[str, Any]], pd.DataFrame] | None = None) -> None:
        super().__init__("eastmoney", reader)


class MiniQMTMarketDataFetcher(CallableFrameFetcher):
    def __init__(self, reader: Callable[[Mapping[str, Any]], pd.DataFrame] | None = None) -> None:
        super().__init__("miniqmt_market_data", reader)


class OpenBBProxyFetcher(CallableFrameFetcher):
    """Optional data-only sidecar adapter; never an A-share primary source."""

    def __init__(self, reader: Callable[[Mapping[str, Any]], pd.DataFrame] | None = None) -> None:
        super().__init__("openbb_proxy", reader)


class ProviderRegistry:
    def __init__(self) -> None:
        self._fetchers: dict[str, DataFetcher] = {}

    def register(self, fetcher: DataFetcher) -> None:
        if fetcher.provider_name in self._fetchers:
            raise ValueError(f"provider already registered: {fetcher.provider_name}")
        self._fetchers[fetcher.provider_name] = fetcher

    def get(self, provider_name: str) -> DataFetcher:
        try:
            return self._fetchers[provider_name]
        except KeyError:
            raise KeyError(f"provider not registered: {provider_name}") from None

    def inventory(self) -> list[str]:
        return sorted(self._fetchers)


class ImmutableSnapshotStore:
    """Persist immutable envelope data and manifest with idempotent hashes."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def persist(self, envelope: MarketDataEnvelope) -> Path:
        directory = self.root / envelope.raw_snapshot_id
        data_path = directory / "data.json"
        manifest_path = directory / "manifest.json"
        if manifest_path.exists() or data_path.exists():
            self._verify_existing(envelope, data_path, manifest_path)
            return manifest_path
        directory.mkdir(parents=True, exist_ok=False)
        data_tmp = data_path.with_suffix(".json.tmp")
        manifest_tmp = manifest_path.with_suffix(".json.tmp")
        data_tmp.write_text(json.dumps(envelope.data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        manifest = {
            "schema_version": envelope.schema_version,
            "raw_snapshot_id": envelope.raw_snapshot_id,
            "dataset": envelope.dataset,
            "instrument_id": envelope.instrument_id,
            "provider": envelope.provider,
            "requested_at": envelope.requested_at.isoformat(),
            "observed_at": envelope.observed_at.isoformat(),
            "available_at": envelope.available_at.isoformat(),
            "ingested_at": envelope.ingested_at.isoformat(),
            "as_of": envelope.as_of,
            "quality_status": envelope.quality_status.value,
            "coverage": envelope.coverage,
            "records": len(envelope.data) if isinstance(envelope.data, list) else 1,
            "content_hash": envelope.content_hash,
            "query_hash": envelope.lineage.get("query_hash"),
            "data_file": str(data_path),
            "immutable": True,
        }
        manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        data_tmp.replace(data_path)
        manifest_tmp.replace(manifest_path)
        return manifest_path

    @staticmethod
    def _verify_existing(envelope: MarketDataEnvelope, data_path: Path, manifest_path: Path) -> None:
        if not data_path.exists() or not manifest_path.exists():
            raise RuntimeError("immutable snapshot is incomplete")
        existing_data = json.loads(data_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256_payload(existing_data) != envelope.content_hash:
            raise RuntimeError("immutable snapshot content hash mismatch")
        if manifest.get("content_hash") != envelope.content_hash:
            raise RuntimeError("immutable manifest hash mismatch")


class ProviderRouter:
    def __init__(self, registry: ProviderRegistry, snapshot_store: ImmutableSnapshotStore) -> None:
        self.registry = registry
        self.snapshot_store = snapshot_store

    def route(
        self,
        query: ProviderQuery,
        *,
        primary_provider: str,
        alternative_providers: list[str] | None = None,
    ) -> ProviderRouteResult:
        primary = self.registry.get(primary_provider).fetch(query)
        manifest_paths = [str(self.snapshot_store.persist(primary))]
        alternatives: list[AlternativeObservation] = []
        conflicts: list[ProviderConflictRecord] = []
        for provider_name in alternative_providers or []:
            envelope = self.registry.get(provider_name).fetch(query)
            manifest_paths.append(str(self.snapshot_store.persist(envelope)))
            reason = (
                "alternative_observation_only_primary_failed"
                if primary.quality_status != QualityStatus.OK
                else "cross_check_only"
            )
            alternatives.append(
                AlternativeObservation(
                    provider=provider_name,
                    primary_provider=primary_provider,
                    used_as_primary=False,
                    envelope=envelope,
                    reason=reason,
                )
            )
            if (
                primary.quality_status == QualityStatus.OK
                and envelope.quality_status == QualityStatus.OK
                and primary.content_hash != envelope.content_hash
            ):
                conflicts.append(
                    ProviderConflictRecord(
                        dataset=query.dataset,
                        instrument_id=query.instrument_id,
                        as_of=query.as_of,
                        primary_provider=primary_provider,
                        alternative_provider=provider_name,
                        primary_content_hash=primary.content_hash,
                        alternative_content_hash=envelope.content_hash,
                        reason="content_hash_mismatch",
                    )
                )
        if primary.quality_status == QualityStatus.OK and not conflicts:
            status = QualityStatus.OK
        elif primary.quality_status in {QualityStatus.MISSING, QualityStatus.PROVIDER_ERROR}:
            status = QualityStatus.MISSING
        else:
            status = QualityStatus.PARTIAL
        return ProviderRouteResult(
            status=status,
            primary=primary,
            alternatives=alternatives,
            conflicts=conflicts,
            silent_fallback_used=False,
            snapshot_manifest_paths=manifest_paths,
        )


def build_snapshot_manifest(
    *,
    data_snapshot_id: str,
    as_of: str,
    manifest_paths: list[str | Path],
    output_path: str | Path | None = None,
    silent_fallback_used: bool = False,
) -> dict[str, Any]:
    """Verify immutable provider artifacts and create one aggregate manifest."""
    unique_paths = sorted({str(Path(path).resolve()) for path in manifest_paths})
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    quality_counts: dict[str, int] = {}
    for value in unique_paths:
        path = Path(value)
        if not path.exists():
            errors.append(f"manifest_missing:{path}")
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            data_file = Path(str(manifest.get("data_file", "")))
            if not data_file.is_absolute():
                data_file = (path.parent / data_file).resolve()
            if not data_file.exists():
                raise FileNotFoundError(f"data_file_missing:{data_file}")
            data = json.loads(data_file.read_text(encoding="utf-8"))
            actual_hash = sha256_payload(data)
            expected_hash = str(manifest.get("content_hash", ""))
            if not expected_hash or actual_hash != expected_hash:
                raise ValueError("content_hash_mismatch")
            quality = str(manifest.get("quality_status", QualityStatus.MISSING.value))
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
            entries.append(
                {
                    "raw_snapshot_id": manifest.get("raw_snapshot_id"),
                    "dataset": manifest.get("dataset"),
                    "instrument_id": manifest.get("instrument_id"),
                    "provider": manifest.get("provider"),
                    "quality_status": quality,
                    "records": manifest.get("records", 0),
                    "observed_at": manifest.get("observed_at"),
                    "available_at": manifest.get("available_at"),
                    "content_hash": expected_hash,
                    "query_hash": manifest.get("query_hash"),
                    "manifest_path": str(path),
                    "data_file": str(data_file),
                    "verified": True,
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            errors.append(f"manifest_invalid:{path}:{type(error).__name__}:{str(error)[:200]}")

    expected_id = f"vnext-{as_of}-{sha256_payload(unique_paths)[:20]}"
    snapshot_id_valid = data_snapshot_id == expected_id
    if not snapshot_id_valid:
        errors.append(f"snapshot_id_mismatch:expected={expected_id}:actual={data_snapshot_id}")
    non_ok = sum(count for quality, count in quality_counts.items() if quality != QualityStatus.OK.value)
    if not unique_paths or not entries:
        status = QualityStatus.MISSING
    elif errors or non_ok or silent_fallback_used:
        status = QualityStatus.PARTIAL
    else:
        status = QualityStatus.OK
    identity = [
        {
            "raw_snapshot_id": entry["raw_snapshot_id"],
            "content_hash": entry["content_hash"],
            "query_hash": entry["query_hash"],
        }
        for entry in entries
    ]
    result = {
        "schema_version": "1.0",
        "status": status.value,
        "as_of": as_of,
        "data_snapshot_id": data_snapshot_id,
        "expected_data_snapshot_id": expected_id,
        "snapshot_id_valid": snapshot_id_valid,
        "generated_at": aware_now().isoformat(),
        "manifest_count": len(unique_paths),
        "verified_count": len(entries),
        "quality_counts": quality_counts,
        "combined_content_hash": sha256_payload(identity),
        "silent_fallback_used": silent_fallback_used,
        "immutable": True,
        "entries": entries,
        "errors": errors,
    }
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(destination)
    return result


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].dt.strftime("%Y-%m-%dT%H:%M:%S")
    clean = clean.where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def _point_in_time(frame: pd.DataFrame, query: ProviderQuery) -> tuple[datetime, datetime]:
    if frame.empty:
        return query.requested_at, query.requested_at
    fallback = pd.Timestamp(query.as_of).to_pydatetime()
    if fallback.tzinfo is None:
        fallback = fallback.replace(tzinfo=aware_now().tzinfo)
    observed = _latest_datetime(frame, ("trade_date", "date", "end_date", "update_time")) or fallback
    available = _latest_datetime(frame, ("available_at", "f_ann_date", "ann_date", "update_time")) or observed
    if available < observed:
        available = observed
    return observed, available


def _latest_datetime(frame: pd.DataFrame, columns: tuple[str, ...]) -> datetime | None:
    for column in columns:
        if column not in frame:
            continue
        parsed = _parse_datetime_series(frame[column])
        if parsed.notna().any():
            value = parsed.max().to_pydatetime()
            if value.tzinfo is None:
                value = value.replace(tzinfo=aware_now().tzinfo)
            return value
    return None


def _parse_datetime_series(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    if text.str.fullmatch(r"\d{8}").all():
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(values, errors="coerce")
