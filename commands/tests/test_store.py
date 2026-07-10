from factor_lab.vnext.store import VNextArtifactStore


def test_store_writes_dated_and_latest_artifacts(tmp_path):
    store = VNextArtifactStore(tmp_path)
    path = store.write("regime", "2026-07-10", {"status": "OK"})
    assert path.exists()
    assert store.read("regime")["status"] == "OK"


def test_store_converts_non_finite_numbers_to_json_null(tmp_path):
    store = VNextArtifactStore(tmp_path)
    store.write("style", "2026-07-10", {"values": [float("nan"), float("inf"), 1.0]})
    assert store.read("style")["values"] == [None, None, 1.0]
