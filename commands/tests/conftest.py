"""Global test safety rails: tests may never delete production data roots."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTECTED_DATA_ROOTS = (
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "commands" / "data",
    Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub"),
    Path("/mnt/d/HermesData"),
    Path("/mnt/d/HermesBackups"),
    Path("/mnt/d/HermesReports"),
)


def assert_safe_destructive_path(value: str | os.PathLike[str]) -> Path:
    candidate = Path(value).expanduser().resolve(strict=False)
    for protected in PROTECTED_DATA_ROOTS:
        root = protected.resolve(strict=False)
        if candidate == root or candidate.is_relative_to(root):
            raise RuntimeError(f"test attempted destructive access to protected data: {candidate}")
    return candidate


@pytest.fixture(autouse=True)
def prevent_production_data_deletion(monkeypatch):
    original_path_unlink = Path.unlink
    original_rmtree = shutil.rmtree
    original_unlink = os.unlink
    original_remove = os.remove

    def guarded_path_unlink(path: Path, *args, **kwargs):
        assert_safe_destructive_path(path)
        return original_path_unlink(path, *args, **kwargs)

    def guarded_rmtree(path, *args, **kwargs):
        assert_safe_destructive_path(path)
        return original_rmtree(path, *args, **kwargs)

    def guarded_unlink(path, *args, **kwargs):
        assert_safe_destructive_path(path)
        return original_unlink(path, *args, **kwargs)

    def guarded_remove(path, *args, **kwargs):
        assert_safe_destructive_path(path)
        return original_remove(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded_path_unlink)
    monkeypatch.setattr(shutil, "rmtree", guarded_rmtree)
    monkeypatch.setattr(os, "unlink", guarded_unlink)
    monkeypatch.setattr(os, "remove", guarded_remove)
