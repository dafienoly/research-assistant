"""测试: Hermes-Leader 自动工作循环。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from factor_lab.leader import workloop


@pytest.fixture()
def isolated_workloop(tmp_path, monkeypatch):
    """把 workloop 状态文件隔离到 tmp_path，避免污染真实 agent_tasks。"""
    monkeypatch.setattr(workloop, "TASKS_DIR", tmp_path)
    monkeypatch.setattr(workloop, "LOCK_FILE", tmp_path / "current_run.lock")
    monkeypatch.setattr(workloop, "LATEST_COMPLETION", tmp_path / "latest_completion.json")
    monkeypatch.setattr(workloop, "_cursor_current_version", lambda: "V3.0.1")
    return workloop


def test_lock_acquire_release(isolated_workloop):
    isolated_workloop.release_lock("completed")
    assert isolated_workloop.acquire_lock("test_lock_001")
    assert isolated_workloop.is_locked()
    isolated_workloop.release_lock("completed")
    assert not isolated_workloop.is_locked()


def test_lock_prevents_duplicate(isolated_workloop):
    isolated_workloop.release_lock("completed")
    isolated_workloop.acquire_lock("test_dup_001")
    assert not isolated_workloop.acquire_lock("test_dup_002")
    isolated_workloop.release_lock("completed")


def test_write_completion(isolated_workloop):
    c = isolated_workloop.write_completion("completed", "V3.0.1", "test", summary={"passed": 1})
    assert c["status"] == "completed"
    assert isolated_workloop.LATEST_COMPLETION.exists()


def test_read_completion(isolated_workloop):
    isolated_workloop.write_completion("partial", "V3.0.1", "test")
    c = isolated_workloop.read_completion()
    assert c["status"] in ("completed", "partial")


def test_dispatch_from_partial_completion(isolated_workloop):
    isolated_workloop.write_completion(
        "partial", "V3.0.1", "dry_run_test",
        remaining_tasks=["rebalance_diff_dry_run"],
    )
    result = isolated_workloop.dispatch_from_completion()
    latest = isolated_workloop.TASKS_DIR / "latest.json"
    assert result is None
    assert latest.exists()
    assert json.loads(latest.read_text())["current"] == "V3.0.1"


def test_dispatch_ignores_stale_completion(isolated_workloop):
    isolated_workloop.write_completion(
        "partial", "V2.15", "dry_run_test",
        remaining_tasks=["rebalance_diff_dry_run"],
    )
    result = isolated_workloop.dispatch_from_completion()
    latest = isolated_workloop.TASKS_DIR / "latest.json"
    assert result["status"] == "skipped"
    assert result["reason"] == "stale_completion"
    assert not latest.exists()


def test_consume_latest_task(isolated_workloop):
    # Ensure there's a task to consume
    isolated_workloop.write_completion(
        "partial", "V3.0.1", "test",
        remaining_tasks=["some_task"],
    )
    isolated_workloop.dispatch_from_completion()
    isolated_workloop.release_lock("completed")
    isolated_workloop.consume_latest_task()


def test_lock_file_cleanup(isolated_workloop):
    isolated_workloop.release_lock("completed")
    assert (
        not isolated_workloop.LOCK_FILE.exists()
        or json.loads(isolated_workloop.LOCK_FILE.read_text()).get("status") == "completed"
    )
