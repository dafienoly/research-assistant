"""Cross-process lock shared by every DataHub writer, backup and recovery."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DataHubLockBusy(RuntimeError):
    """Raised when another DataHub writer, backup or recovery owns the lock."""


@contextmanager
def datahub_write_lock(lock_path: Path | None = None) -> Iterator[None]:
    path = lock_path or Path(os.environ.get("HERMES_LOCK_DIR", Path.home() / ".hermes/locks")) / "datahub-global.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DataHubLockBusy("DataHub writer, backup, or recovery is active") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
