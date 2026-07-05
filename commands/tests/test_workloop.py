"""测试: Hermes-Leader 自动工作循环"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from factor_lab.leader.workloop import (
    acquire_lock, release_lock, is_locked,
    write_completion, read_completion,
    dispatch_from_completion, consume_latest_task,
    LOCK_FILE, LATEST_COMPLETION
)

TASKS_DIR = Path("/home/ly/.hermes/research-assistant/agent_tasks")


def test_lock_acquire_release():
    release_lock("completed")
    assert acquire_lock("test_lock_001")
    assert is_locked()
    release_lock("completed")
    assert not is_locked()


def test_lock_prevents_duplicate():
    release_lock("completed")
    acquire_lock("test_dup_001")
    assert not acquire_lock("test_dup_002")
    release_lock("completed")


def test_write_completion():
    c = write_completion("completed", "V2.15", "test", summary={"passed": 1})
    assert c["status"] == "completed"
    assert LATEST_COMPLETION.exists()


def test_read_completion():
    write_completion("partial", "V2.15", "test")
    c = read_completion()
    assert c["status"] in ("completed", "partial")


def test_dispatch_from_partial_completion():
    write_completion("partial", "V2.15", "dry_run_test",
                     remaining_tasks=["rebalance_diff_dry_run"])
    dispatch_from_completion()
    latest = TASKS_DIR / "latest.json"
    assert latest.exists()


def test_consume_latest_task():
    # Ensure there's a task to consume
    write_completion("partial", "V2.15", "test",
                     remaining_tasks=["some_task"])
    dispatch_from_completion()
    release_lock("completed")
    consume_latest_task()


def test_lock_file_cleanup():
    release_lock("completed")
    assert not LOCK_FILE.exists() or json.loads(LOCK_FILE.read_text()).get("status") == "completed"
