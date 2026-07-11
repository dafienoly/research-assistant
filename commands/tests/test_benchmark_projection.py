from pathlib import Path

import pandas as pd

from factor_lab.datahub_ingestion import benchmark_projection


def test_projection_manifest_uses_portable_relative_paths(tmp_path: Path, monkeypatch) -> None:
    returns = pd.Series([0.01], index=pd.to_datetime(["2026-07-10"]))
    monkeypatch.setattr(benchmark_projection, "VALID_BENCHMARK_NAMES", {"ew_a_share"})
    monkeypatch.setattr(benchmark_projection, "compute_benchmark_projection", lambda _name: returns)

    manifest = benchmark_projection.build_benchmark_projections(tmp_path)

    dataset = manifest["datasets"]["ew_a_share"]
    assert dataset["path"] == "ew_a_share.csv"
    assert not Path(dataset["path"]).is_absolute()
    assert (tmp_path / dataset["path"]).exists()
