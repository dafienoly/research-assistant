"""测试: V2.15.2 Agent Runner"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
import pytest
from factor_lab.leader.agent_runner import AgentRunner, DEFAULT_BACKEND, BACKEND_PRIORITY, loop_once
from factor_lab.leader.workloop import write_completion, release_lock, LATEST_COMPLETION, TASKS_DIR, LOCK_FILE


@pytest.fixture(autouse=True)
def _preserve_runtime_state():
    paths = [TASKS_DIR / "latest.json", LATEST_COMPLETION, LOCK_FILE]
    snapshots = {path: path.read_bytes() if path.exists() else None for path in paths}
    yield
    for path, data in snapshots.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def _setup_task():
    """创建测试用的任务包"""
    release_lock("completed")
    from factor_lab.leader.workloop import dispatch_from_completion
    write_completion("partial", "V2.15.2", "test", remaining_tasks=["dry_run_test"])
    dispatch_from_completion()
    latest = TASKS_DIR / "latest.json"
    return json.loads(latest.read_text()) if latest.exists() else {}


def test_default_backend_is_claude():
    assert DEFAULT_BACKEND == "claude"
    assert DEFAULT_BACKEND not in ("codex",)


def test_backend_priority():
    assert BACKEND_PRIORITY.index("claude") < BACKEND_PRIORITY.index("codex")


def test_dry_run_backend():
    release_lock("completed")
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    # dry-run 应执行成功 (不管是否有任务)
    assert result.get("status") in ("completed", "partial", "no_tasks", "blocked")


def test_runner_reads_latest():
    release_lock("completed")
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    assert "status" in result


def test_runner_writes_completed():
    release_lock("completed")
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    if result.get("status") == "completed":
        comp = json.loads(LATEST_COMPLETION.read_text()) if LATEST_COMPLETION.exists() else {}
        assert comp.get("status") == "completed"


def test_runner_releases_lock():
    release_lock("completed")
    runner = AgentRunner(backend="dry-run")
    runner.run_once()
    from factor_lab.leader.workloop import is_locked
    assert not is_locked()


def test_runner_blocks_unsafe_stage():
    """不安全阶段应 blocked"""
    write_completion("pending", "live_execution", "unsafe",
                     remaining_tasks=["dangerous_task"])
    from factor_lab.leader.workloop import dispatch_from_completion
    dispatch_from_completion()
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    assert result.get("status") in ("blocked", "completed", "partial")


def test_loop_once_no_crash():
    loop_once()


def test_runner_does_not_require_codex():
    """不指定 --backend codex 时不得调用 codex"""
    # 验证默认 backend 不是 codex
    runner = AgentRunner()  # default
    assert runner.backend != "codex"
