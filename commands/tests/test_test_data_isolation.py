from __future__ import annotations

from pathlib import Path

import pytest

from commands.tests.conftest import PROJECT_ROOT, assert_safe_destructive_path


@pytest.mark.parametrize(
    "path",
    [
        PROJECT_ROOT / "data" / "normalized" / "market" / "000001.SZ.csv",
        PROJECT_ROOT / "commands" / "data" / "tags" / "stock_names_cache.csv",
        Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline/000001.SZ.csv"),
        Path("/mnt/d/HermesData/alpha_registry"),
        Path("/mnt/d/HermesBackups/research-assistant-data_example"),
        Path("/mnt/d/HermesReports/test-output"),
    ],
)
def test_production_data_roots_are_never_destructive_test_targets(path):
    with pytest.raises(RuntimeError, match="protected data"):
        assert_safe_destructive_path(path)


def test_pytest_temporary_paths_remain_deletable(tmp_path):
    candidate = tmp_path / "safe.csv"
    candidate.write_text("ok", encoding="utf-8")
    candidate.unlink()
    assert not candidate.exists()
