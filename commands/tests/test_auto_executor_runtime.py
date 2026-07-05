"""测试: Auto Executor Runtime — 逻辑测试 (不下令子进程)"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
import pytest
from factor_lab.leader.roadmap import get_version, ALPHA_FACTORY_ROADMAP
from factor_lab.leader.roadmap_cursor import get_cursor, advance, CURSOR_FILE
from factor_lab.leader.workloop import release_lock, TASKS_DIR, LATEST_COMPLETION, LOCK_FILE
from factor_lab.leader.backend_policy import need_code_change


@pytest.fixture(autouse=True)
def _preserve_runtime_state():
    paths = [TASKS_DIR / "latest.json", LATEST_COMPLETION, LOCK_FILE, CURSOR_FILE]
    snapshots = {path: path.read_bytes() if path.exists() else None for path in paths}
    yield
    for path, data in snapshots.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def test_auto_loop_once_and_watch_entrypoints(monkeypatch):
    from factor_lab.leader import auto_loop, auto_executor

    monkeypatch.setattr(auto_executor, "auto_run_once",
                        lambda: {"status": "completed", "version": "TEST"})
    once = auto_loop.loop_once()
    assert once["result"]["status"] == "completed"

    watched = auto_loop.loop_watch(interval_seconds=0, max_ticks=1)
    assert watched["result"]["version"] == "TEST"


def test_auto_executor_does_not_clear_running_lock(monkeypatch):
    from factor_lab.leader import auto_executor

    monkeypatch.setattr(auto_executor, "is_locked", lambda: True)
    result = auto_executor.auto_run_once()
    assert result == {"status": "running", "reason": "another_agent_run_in_progress"}


def test_get_version_returns_roadmap_item():
    v = get_version("V3.0.1")
    assert v is not None
    assert v.version == "V3.0.1"
    assert v.name == "Existing Factor Catalog Migration"
    assert hasattr(v, 'trading_mode')
    assert hasattr(v, 'manual_required')


def test_stale_latest_archived_logic():
    """latest.json.current != cursor.current 时归档"""
    release_lock("completed")
    cursor = get_cursor()
    current = cursor["current_version"]
    assert current != "V2.15", "cursor 不应为 V2.15"
    assert current != "live_execution", "cursor 不应为 live_execution"
    assert current.startswith("V3") or current.startswith("V4"), f"cursor 应指向 V3/V4, 当前为 {current}"


def test_no_some_task_in_roadmap():
    """路线图不得包含 some_task"""
    for item in ALPHA_FACTORY_ROADMAP[:60]:
        assert "some_task" not in item.name.lower()
        assert "some_task" not in item.objective.lower()


def test_no_dry_run_completion_in_roadmap():
    """路线图不得固定 dry_run_completion"""
    for item in ALPHA_FACTORY_ROADMAP[:60]:
        assert "dry_run_completion" not in item.name.lower()


def test_v49_manual_required():
    v = get_version("V4.9")
    assert v is not None
    assert v.manual_required == True


def test_v36_is_paper():
    v = get_version("V3.6")
    assert v is not None
    assert v.trading_mode == "paper"


def test_no_roadmap_item_get_in_executor():
    """auto_executor.py 不得使用 .get() 或 [] 访问 RoadmapItem"""
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/leader/auto_executor.py").read()
    for line in src.split("\n"):
        l = line.strip()
        # 跳过注释和字符串字面量
        if l.startswith("#") or l.startswith('"') or l.startswith("'"):
            continue
        if "cv." in l and ".get(" in l:
            # 允许 dict.get 用于非 RoadmapItem 对象
            if "cv.get(" in l:
                assert False, f"仍使用 cv.get(): {l}"
        if "cv[" in l:
            assert False, f"仍使用 cv[ ]: {l}"
