from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from factor_lab.vnext.contracts import QualityStatus, sha256_payload
from factor_lab.vnext.providers import (
    AkShareFetcher,
    CallableFrameFetcher,
    EastMoneyFetcher,
    ImmutableSnapshotStore,
    LocalCsvFetcher,
    MiniQMTMarketDataFetcher,
    OpenBBProxyFetcher,
    ProviderQuery,
    ProviderRegistry,
    ProviderRouter,
    TencentQuoteFetcher,
    build_snapshot_manifest,
)
from factor_lab.vnext.snapshot import ASSET_PROXIES, HubSnapshotBuilder


def test_local_csv_fetcher_persists_idempotent_immutable_point_in_time_snapshot(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "daily.csv"
    path.write_text("trade_date,close\n20260710,10.5\n", encoding="utf-8")
    query = ProviderQuery(
        dataset="daily",
        instrument_id="600183.SH",
        as_of="2026-07-10",
        params={"path": str(path)},
        required_fields=["trade_date", "close"],
    )
    fetcher = LocalCsvFetcher([source])
    envelope = fetcher.fetch(query)
    assert envelope.quality_status == QualityStatus.OK
    assert envelope.provider == "local_csv"
    assert envelope.observed_at.date().isoformat() == "2026-07-10"
    assert envelope.available_at >= envelope.observed_at
    assert len(envelope.content_hash) == 64

    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    first = store.persist(envelope)
    second = store.persist(envelope)
    assert first == second
    assert first.exists()
    assert (first.parent / "data.json").exists()


def test_router_never_promotes_alternative_when_primary_is_missing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    registry = ProviderRegistry()
    registry.register(LocalCsvFetcher([source]))
    registry.register(AkShareFetcher(lambda _: pd.DataFrame([{"trade_date": "20260710", "close": 10.5}])))
    result = ProviderRouter(registry, ImmutableSnapshotStore(tmp_path / "snapshots")).route(
        ProviderQuery(
            dataset="daily",
            instrument_id="600183.SH",
            as_of="2026-07-10",
            params={"path": str(source / "missing.csv")},
            required_fields=["trade_date", "close"],
        ),
        primary_provider="local_csv",
        alternative_providers=["akshare"],
    )
    assert result.status == QualityStatus.MISSING
    assert result.primary.quality_status == QualityStatus.MISSING
    assert result.alternatives[0].envelope.quality_status == QualityStatus.OK
    assert result.alternatives[0].used_as_primary is False
    assert result.silent_fallback_used is False


def test_router_records_conflict_without_overwriting_primary(tmp_path):
    def primary_reader(_):
        return pd.DataFrame([{"trade_date": "20260710", "close": 10.5}])

    def alternative_reader(_):
        return pd.DataFrame([{"trade_date": "20260710", "close": 10.8}])

    registry = ProviderRegistry()
    registry.register(CallableFrameFetcher("primary", primary_reader))
    registry.register(CallableFrameFetcher("secondary", alternative_reader))
    result = ProviderRouter(registry, ImmutableSnapshotStore(tmp_path / "snapshots")).route(
        ProviderQuery(
            dataset="daily",
            instrument_id="600183.SH",
            as_of="2026-07-10",
            required_fields=["trade_date", "close"],
        ),
        primary_provider="primary",
        alternative_providers=["secondary"],
    )
    assert result.status == QualityStatus.PARTIAL
    assert len(result.conflicts) == 1
    assert result.conflicts[0].resolution == "PRIMARY_RETAINED_REVIEW_REQUIRED"
    assert result.primary.data[0]["close"] == 10.5


def test_local_csv_path_outside_allowlist_is_provider_error(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("trade_date,close\n20260710,10\n", encoding="utf-8")
    envelope = LocalCsvFetcher([allowed]).fetch(
        ProviderQuery(
            dataset="daily",
            instrument_id="600183.SH",
            as_of="2026-07-10",
            params={"path": str(outside)},
            required_fields=["trade_date", "close"],
        )
    )
    assert envelope.quality_status == QualityStatus.PROVIDER_ERROR
    assert envelope.data == []
    assert "PermissionError" in envelope.warnings[0]


def test_named_optional_fetchers_are_data_only_and_fail_visible_when_unconfigured():
    query = ProviderQuery(dataset="quote", instrument_id="600183.SH", as_of="2026-07-10")
    for fetcher in (
        AkShareFetcher(),
        TencentQuoteFetcher(),
        EastMoneyFetcher(),
        MiniQMTMarketDataFetcher(),
        OpenBBProxyFetcher(),
    ):
        envelope = fetcher.fetch(query)
        assert envelope.quality_status == QualityStatus.PROVIDER_ERROR
        assert not hasattr(fetcher, "submit")
        assert not hasattr(fetcher, "send_order")


def test_financial_available_at_uses_announcement_date():
    frame = pd.DataFrame(
        [
            {
                "end_date": "20260331",
                "ann_date": "20260420",
                "roe": 0.12,
            }
        ]
    )
    envelope = CallableFrameFetcher("financial", lambda _: frame).fetch(
        ProviderQuery(
            dataset="fina_indicator",
            instrument_id="600183.SH",
            as_of="2026-04-20",
            required_fields=["end_date", "ann_date", "roe"],
        )
    )
    assert envelope.observed_at.date().isoformat() == "2026-03-31"
    assert envelope.available_at.date().isoformat() == "2026-04-20"


def test_live_snapshot_observed_at_uses_source_update_time(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "live.csv"
    path.write_text(
        "update_time,change_pct\n2026-07-10T08:00:19+08:00,1.2\n",
        encoding="utf-8",
    )
    envelope = LocalCsvFetcher([source]).fetch(
        ProviderQuery(
            dataset="live_snapshot",
            instrument_id="A_SHARE_ALL",
            as_of="2026-07-10",
            params={"path": str(path), "as_of_field": "update_time"},
            required_fields=["change_pct"],
        )
    )
    assert envelope.observed_at.isoformat() == "2026-07-10T08:00:19+08:00"
    assert envelope.available_at == envelope.observed_at


def test_hub_snapshot_uses_provider_router_and_emits_manifest_bound_snapshot_id(tmp_path):
    data_root = tmp_path / "data"
    daily_root = data_root / "normalized" / "market"
    daily_root.mkdir(parents=True)
    live = data_root / "live_snapshot.csv"
    live.write_text(
        "code,last_price,change_pct,update_time,source\n600183,10.0,1.2,2026-07-10T15:00:00+08:00,test\n",
        encoding="utf-8",
    )
    (live.with_suffix(".manifest.json")).write_text(
        json.dumps({
            "status": "OK",
            "observed_at": "2026-07-10T15:00:00+08:00",
            "sha256": hashlib.sha256(live.read_bytes()).hexdigest(),
            "conflicts": [],
        }),
        encoding="utf-8",
    )

    dates = pd.date_range("2026-01-01", "2026-07-10", freq="B")

    market = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "open": range(1, len(dates) + 1),
            "high": [value + 1 for value in range(1, len(dates) + 1)],
            "low": [max(0.5, value - 1) for value in range(1, len(dates) + 1)],
            "close": [value + 0.5 for value in range(1, len(dates) + 1)],
            "vol": [1000 + value for value in range(len(dates))],
        }
    )
    for category, symbols in (
        ("index", ["000001.SH"]),
        ("fund", [symbol for symbol, _ in ASSET_PROXIES.values()]),
    ):
        directory = data_root / "normalized/market_series" / category
        directory.mkdir(parents=True, exist_ok=True)
        for symbol in symbols:
            market.to_csv(directory / f"{symbol}.csv", index=False)

    registry = ProviderRegistry()
    registry.register(LocalCsvFetcher([data_root, daily_root]))
    store = ImmutableSnapshotStore(tmp_path / "immutable")
    builder = HubSnapshotBuilder(
        tmp_path,
        live_snapshot=live,
        provider_router=ProviderRouter(registry, store),
    )
    snapshot = builder.build("2026-07-10")
    assert snapshot["data_snapshot_id"].startswith("vnext-2026-07-10-")
    assert snapshot["snapshot_manifest_paths"]
    assert snapshot["provider_routes"]
    assert snapshot["silent_fallback_used"] is False
    assert all(Path(path).exists() for path in snapshot["snapshot_manifest_paths"])


def test_provider_retry_is_idempotent_even_when_requested_at_changes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "daily.csv"
    path.write_text("trade_date,close\n20260710,10.5\n", encoding="utf-8")
    fetcher = LocalCsvFetcher([source])
    first = fetcher.fetch(
        ProviderQuery(
            dataset="daily",
            instrument_id="600183.SH",
            as_of="2026-07-10",
            params={"path": str(path)},
            required_fields=["trade_date", "close"],
        )
    )
    second = fetcher.fetch(
        ProviderQuery(
            dataset="daily",
            instrument_id="600183.SH",
            as_of="2026-07-10",
            params={"path": str(path)},
            required_fields=["trade_date", "close"],
        )
    )
    assert first.raw_snapshot_id == second.raw_snapshot_id
    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    assert store.persist(first) == store.persist(second)


def test_aggregate_snapshot_manifest_verifies_identity_and_detects_tampering(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "daily.csv"
    path.write_text("trade_date,close\n20260710,10.5\n", encoding="utf-8")
    envelope = LocalCsvFetcher([source]).fetch(
        ProviderQuery(
            dataset="daily",
            instrument_id="600183.SH",
            as_of="2026-07-10",
            params={"path": str(path)},
            required_fields=["trade_date", "close"],
        )
    )
    provider_manifest = ImmutableSnapshotStore(tmp_path / "snapshots").persist(envelope).resolve()
    paths = [str(provider_manifest)]
    snapshot_id = f"vnext-2026-07-10-{sha256_payload(paths)[:20]}"
    output = tmp_path / "aggregate.json"

    verified = build_snapshot_manifest(
        data_snapshot_id=snapshot_id,
        as_of="2026-07-10",
        manifest_paths=paths,
        output_path=output,
    )

    assert verified["status"] == QualityStatus.OK.value
    assert verified["snapshot_id_valid"] is True
    assert verified["verified_count"] == 1
    assert output.exists()

    (provider_manifest.parent / "data.json").write_text("[]", encoding="utf-8")
    tampered = build_snapshot_manifest(
        data_snapshot_id=snapshot_id,
        as_of="2026-07-10",
        manifest_paths=paths,
    )
    assert tampered["status"] == QualityStatus.MISSING.value
    assert any("content_hash_mismatch" in error for error in tampered["errors"])
