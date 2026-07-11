from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import factor_lab.alpha.registry as registry
from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.storage import read_json, update_json


def test_atomic_json_update_preserves_all_concurrent_writers(tmp_path) -> None:
    index = tmp_path / "registry_index.json"

    def append(value: int) -> None:
        update_json(index, [], lambda rows: [*rows, {"value": value}])

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(append, range(100)))

    assert sorted(row["value"] for row in read_json(index, [])) == list(range(100))


def test_register_alpha_keeps_every_concurrent_index_entry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(registry, "REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(registry, "REGISTRY_INDEX", tmp_path / "registry_index.json")

    def register(value: int) -> str:
        result = registry.register_alpha(
            AlphaSpec(name=f"factor-{value}", hypothesis="concurrency", enabled=False)
        )
        return result["alpha_id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        alpha_ids = list(pool.map(register, range(24)))

    persisted = read_json(tmp_path / "registry_index.json", [])
    assert len(alpha_ids) == len(set(alpha_ids)) == 24
    assert {row["alpha_id"] for row in persisted} == set(alpha_ids)
    assert all(row.get("enabled") is not True for row in persisted)
