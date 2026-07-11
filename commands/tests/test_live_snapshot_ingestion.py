from __future__ import annotations

import json

import pandas as pd
import pytest

from factor_lab.datahub_ingestion.live_snapshot import LiveSnapshotIngestion


def test_live_snapshot_ingestion_atomically_publishes_manifest(tmp_path):
    output = tmp_path / "market/live_snapshot.csv"
    ingestion = LiveSnapshotIngestion(
        output,
        full_market_fetcher=lambda: [{
            "code": "600000", "name": "浦发银行", "last_price": 10,
            "change_pct": 1.0, "source": "akshare",
        }],
        priority_fetcher=lambda _codes: [{
            "code": "600000", "name": "浦发银行", "last_price": 10.1,
            "change_pct": 1.1, "source": "rsscast",
        }],
    )

    manifest = ingestion.fetch(["600000"])

    frame = pd.read_csv(output, encoding="utf-8-sig", dtype={"code": "string"})
    durable_manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert frame.loc[0, "last_price"] == 10.1
    assert manifest == durable_manifest
    assert manifest["rows"] == 1
    assert manifest["path"] == "live_snapshot.csv"


def test_empty_provider_response_never_overwrites_canonical_snapshot(tmp_path):
    output = tmp_path / "live_snapshot.csv"
    output.write_text("code,last_price\n600000,10\n", encoding="utf-8")
    original = output.read_bytes()
    ingestion = LiveSnapshotIngestion(output, full_market_fetcher=lambda: [])

    with pytest.raises(RuntimeError, match="preserved"):
        ingestion.fetch()

    assert output.read_bytes() == original
    assert not output.with_suffix(".manifest.json").exists()
