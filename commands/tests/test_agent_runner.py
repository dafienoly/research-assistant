"""测试: V2.15.2 Agent Runner，不污染真实运行状态。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from factor_lab.leader import agent_runner, workloop
from factor_lab.leader.agent_runner import AgentRunner, BACKEND_PRIORITY, DEFAULT_BACKEND, loop_once


@pytest.fixture()
def isolated_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(workloop, "TASKS_DIR", tmp_path)
    monkeypatch.setattr(workloop, "LOCK_FILE", tmp_path / "current_run.lock")
    monkeypatch.setattr(workloop, "LATEST_COMPLETION", tmp_path / "latest_completion.json")
    monkeypatch.setattr(workloop, "_cursor_current_version", lambda: "V3.0.1")
    monkeypatch.setattr(agent_runner, "TASKS_DIR", tmp_path)
    return tmp_path


def _setup_task(tmp_path):
    """创建测试用的任务包。"""
    workloop.release_lock("completed")
    workloop.write_completion("partial", "V3.0.1", "test", remaining_tasks=["dry_run_test"])
    workloop.dispatch_from_completion()
    latest = tmp_path / "latest.json"
    return json.loads(latest.read_text()) if latest.exists() else {}


def test_default_backend_is_claude():
    assert DEFAULT_BACKEND == "claude"
    assert DEFAULT_BACKEND not in ("codex",)


def test_backend_priority():
    assert BACKEND_PRIORITY.index("claude") < BACKEND_PRIORITY.index("codex")


def test_dry_run_backend(isolated_runner):
    _setup_task(isolated_runner)
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    assert result.get("status") in ("completed", "partial", "no_tasks", "blocked")


def test_runner_reads_latest(isolated_runner):
    _setup_task(isolated_runner)
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    assert "status" in result


def test_runner_writes_completed(isolated_runner):
    _setup_task(isolated_runner)
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    if result.get("status") == "completed":
        comp = json.loads(workloop.LATEST_COMPLETION.read_text()) if workloop.LATEST_COMPLETION.exists() else {}
        assert comp.get("status") == "completed"


def test_runner_releases_lock(isolated_runner):
    _setup_task(isolated_runner)
    runner = AgentRunner(backend="dry-run")
    runner.run_once()
    assert not workloop.is_locked()


def test_runner_blocks_unsafe_stage(isolated_runner):
    """不安全阶段应 blocked。"""
    workloop.release_lock("completed")
    run_dir = isolated_runner / "unsafe_run"
    tasks_dir = run_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "T001.md").write_text("dangerous task")
    (run_dir / "tasks.json").write_text(json.dumps(["T001"]))
    (isolated_runner / "latest.json").write_text(json.dumps({
        "run_id": "unsafe_run",
        "path": str(run_dir),
        "status": "pending",
        "current": "live_execution",
        "next": "unsafe",
        "task_count": 1,
    }))
    runner = AgentRunner(backend="dry-run")
    result = runner.run_once()
    assert result.get("status") == "blocked"


def test_loop_once_no_crash(isolated_runner):
    workloop.write_completion("partial", "V3.0.1", "test")
    loop_once()


def test_runner_does_not_require_codex():
    """不指定 --backend codex 时不得调用 codex。"""
    runner = AgentRunner()
    assert runner.backend != "codex"


def test_claude_backend_uses_auto_mode_and_ultra_effort(tmp_path, monkeypatch):
    """验证 _backend_claude 使用 auto 模式 (-a) + ultra 思维强度"""
    monkeypatch.setenv("HERMES_CLAUDE_BIN", "/opt/claude")
    captured = {"cmd": None, "env": None, "timeout": None, "returncode": 0, "stdout": "ok"}

    def fake_stream(cmd, log_file, input_text=None, timeout=0, shell=False, line_transform=None, env=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        captured["line_transform"] = line_transform
        captured["env"] = env
        log_file.write_text("streamed")
        return {"success": True, "returncode": 0, "output": "ok"}

    monkeypatch.setattr(agent_runner, "_run_streaming_process", fake_stream)
    runner = AgentRunner(backend="claude")
    runner.log_dir = tmp_path
    result = runner._backend_claude("prompt", "T001", tmp_path / "T001.log")

    cmd = captured["cmd"]
    assert cmd[0] == "/opt/claude"
    assert "--print" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--add-dir" in cmd
    assert "--model" in cmd and "deepseek-v4" in cmd
    assert captured["timeout"] == 3600
    assert captured["env"].get("CLAUDE_CODE_EFFORT_LEVEL") == "ultra"
    assert result["streaming_mode"] == "print+ultra"
    assert result["permission_mode"] == "bypassPermissions"


def test_find_task_file_prefers_exact_clean_task(tmp_path):
    from factor_lab.leader.agent_runner import _find_task_file

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T001_some_task.md").write_text("some_task V2.15")
    (tasks / "T001.md").write_text("clean task")
    assert _find_task_file(tasks, "T001") == "clean task"


def test_claude_stream_transform_suppresses_noisy_events():
    from factor_lab.leader.agent_runner import _extract_claude_stream_text

    assert _extract_claude_stream_text('{"type":"stream_event"}') == ""
    assert _extract_claude_stream_text('{"type":"system","subtype":"status"}') == ""
    assert _extract_claude_stream_text('{"type":"assistant"}') == ""
    assert _extract_claude_stream_text('{"type":"assistant","message":{"content":[{"text":"hello"}]}}') == "hello"
