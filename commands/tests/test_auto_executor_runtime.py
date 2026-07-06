"""测试: Auto Executor Runtime — 逻辑测试，不污染真实运行状态。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from factor_lab.leader.roadmap import ALPHA_FACTORY_ROADMAP, get_version
from factor_lab.leader import roadmap_cursor, workloop


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(workloop, "TASKS_DIR", tmp_path)
    monkeypatch.setattr(workloop, "LOCK_FILE", tmp_path / "current_run.lock")
    monkeypatch.setattr(workloop, "LATEST_COMPLETION", tmp_path / "latest_completion.json")
    monkeypatch.setattr(roadmap_cursor, "CURSOR_FILE", tmp_path / "roadmap_cursor.json")
    return tmp_path


def test_auto_loop_once_and_watch_entrypoints(monkeypatch, isolated_runtime):
    from factor_lab.leader import auto_loop, auto_executor

    monkeypatch.setattr(auto_loop, "STATE_FILE", isolated_runtime / "auto_loop_state.json")
    monkeypatch.setattr(auto_loop, "read_completion", workloop.read_completion)
    monkeypatch.setattr(auto_loop, "is_locked", workloop.is_locked)
    monkeypatch.setattr(auto_executor, "auto_run_once", lambda: {"status": "completed", "version": "TEST"})
    once = auto_loop.loop_once()
    assert once["result"]["status"] == "completed"

    watched = auto_loop.loop_watch(interval_seconds=0, max_ticks=1)
    assert watched["result"]["version"] == "TEST"


def test_auto_executor_does_not_clear_running_lock(monkeypatch):
    from factor_lab.leader import auto_executor

    monkeypatch.setattr(auto_executor, "is_locked", lambda: True)
    result = auto_executor.auto_run_once()
    assert result == {"status": "running", "reason": "another_agent_run_in_progress"}


def test_ensure_latest_clean_replaces_non_auto_run(monkeypatch, tmp_path):
    from factor_lab.leader import auto_executor

    monkeypatch.setattr(auto_executor, "TASKS_DIR", tmp_path)
    (tmp_path / "latest.json").write_text(json.dumps({
        "run_id": "roadmap_old",
        "current": "V3.0.1",
        "status": "pending",
        "task_count": 1,
    }))
    auto_executor._ensure_latest_clean("V3.0.1")
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["run_id"].startswith("auto_")
    assert latest["current"] == "V3.0.1"


def test_ensure_latest_clean_replaces_polluted_auto_run(monkeypatch, tmp_path):
    from factor_lab.leader import auto_executor

    monkeypatch.setattr(auto_executor, "TASKS_DIR", tmp_path)
    polluted = tmp_path / "auto_old" / "tasks"
    polluted.mkdir(parents=True)
    (polluted / "T001_some_task.md").write_text("some_task V2.15")
    (tmp_path / "latest.json").write_text(json.dumps({
        "run_id": "auto_old",
        "path": str(tmp_path / "auto_old"),
        "current": "V3.0.1",
        "status": "pending",
        "task_count": 1,
    }))
    auto_executor._ensure_latest_clean("V3.0.1")
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["run_id"].startswith("auto_")
    assert latest["run_id"] != "auto_old"


def test_get_version_returns_roadmap_item():
    v = get_version("V3.0.1")
    assert v is not None
    assert v.version == "V3.0.1"
    assert v.name == "Existing Factor Catalog Migration"
    assert hasattr(v, "trading_mode")
    assert hasattr(v, "manual_required")


def test_stale_latest_archived_logic(isolated_runtime):
    """cursor 不应回退到危险旧阶段。"""
    c = roadmap_cursor.get_cursor()
    current = c["current_version"]
    assert current != "V2.15", "cursor 不应为 V2.15"
    assert current != "live_execution", "cursor 不应为 live_execution"
    assert current.startswith("V3") or current.startswith("V4"), f"cursor 应指向 V3/V4, 当前为 {current}"


def test_no_some_task_in_roadmap():
    """路线图不得包含 some_task。"""
    for item in ALPHA_FACTORY_ROADMAP[:60]:
        assert "some_task" not in item.name.lower()
        assert "some_task" not in item.objective.lower()


def test_no_dry_run_completion_in_roadmap():
    """路线图不得固定 dry_run_completion。"""
    for item in ALPHA_FACTORY_ROADMAP[:60]:
        assert "dry_run_completion" not in item.name.lower()


def test_v49_manual_required():
    v = get_version("V4.9")
    assert v is not None
    assert v.manual_required is True


def test_v36_is_paper():
    v = get_version("V3.6")
    assert v is not None
    assert v.trading_mode == "paper"


def test_no_roadmap_item_get_in_executor():
    """auto_executor.py 不得使用 .get() 或 [] 访问 RoadmapItem。"""
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/leader/auto_executor.py").read()
    for line in src.split("\n"):
        l = line.strip()
        if l.startswith("#") or l.startswith('"') or l.startswith("'"):
            continue
        if "cv." in l and ".get(" in l and "cv.get(" in l:
            assert False, f"仍使用 cv.get(): {l}"
        if "cv[" in l:
            assert False, f"仍使用 cv[ ]: {l}"
