"""测试: V3 Alpha Factory Leader 自动检查与任务派发"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from factor_lab.leader.planner import dispatch_tasks, inspect_system
from factor_lab.leader.roadmap import ALPHA_FACTORY_ROADMAP, roadmap_as_dicts


def test_roadmap_uses_alpha_factory_lifecycle_versions():
    versions = [item.version for item in ALPHA_FACTORY_ROADMAP]
    assert versions == ["V3.0", "V3.0.1", "V3.1", "V3.2", "V3.3", "V3.4", "V3.5", "V3.6", "V3.7", "V4.0"]
    assert ALPHA_FACTORY_ROADMAP[0].name == "Alpha Factory Foundation"
    assert ALPHA_FACTORY_ROADMAP[1].name == "Existing Factor Catalog Migration"


def test_roadmap_keeps_pre_live_versions_non_live():
    road = roadmap_as_dicts()
    for item in road:
        if item["version"] in {"V3.0", "V3.0.1", "V3.1", "V3.2", "V3.3", "V3.4", "V3.5", "V3.7"}:
            assert item["trading_mode"] == "none"
    assert next(item for item in road if item["version"] == "V3.6")["trading_mode"] == "paper"
    assert next(item for item in road if item["version"] == "V4.0")["trading_mode"] == "human_controlled_live"


def test_inspect_system_returns_stage_and_safety():
    report = inspect_system()
    assert "stage" in report
    assert "next_version" in report["stage"]
    assert report["safety"]["no_live_trade"] is True
    assert report["safety"]["task_generation_only"] is True
    assert report["factor_catalog"].get("count", 0) >= 0


def test_cli_alpha_router_detected_after_hardening():
    report = inspect_system()
    assert report["cli"]["has_alpha_router"] is True
    assert report["cli"]["has_leader_inspect"] is True
    assert report["cli"]["has_leader_dispatch"] is True


def test_dispatch_dry_run_generates_v3_tasks_without_writing():
    dispatch = dispatch_tasks(dry_run=True, max_tasks=4)
    assert dispatch["dry_run"] is True
    assert dispatch["task_count"] > 0
    assert all(task["safety"]["no_live_trade"] is True for task in dispatch["tasks"])
    assert all(task["safety"]["task_generation_only"] is True for task in dispatch["tasks"])
    assert any(task["version"].startswith("V3") for task in dispatch["tasks"])


def test_leader_tasks_are_actionable():
    dispatch = dispatch_tasks(dry_run=True, max_tasks=6)
    for task in dispatch["tasks"]:
        assert task["target_files"]
        assert task["instructions"]
        assert task["acceptance"]
        assert task["test_commands"]
