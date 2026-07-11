from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

from factor_lab.datahub_ingestion.locking import DataHubLockBusy, datahub_write_lock


def test_datahub_write_lock_rejects_concurrent_writer(tmp_path: Path) -> None:
    lock_path = tmp_path / "datahub-global.lock"
    with lock_path.open("a+") as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DataHubLockBusy):
            with datahub_write_lock(lock_path):
                raise AssertionError("contended writer must not enter")


def test_datahub_write_lock_releases_after_success(tmp_path: Path) -> None:
    lock_path = tmp_path / "datahub-global.lock"
    with datahub_write_lock(lock_path):
        pass
    with datahub_write_lock(lock_path):
        pass
