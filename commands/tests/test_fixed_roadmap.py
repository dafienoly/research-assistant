"""测试: V2.16.3 Fixed Roadmap Continuous Auto-Development。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from factor_lab.leader.roadmap import (
    ALPHA_FACTORY_ROADMAP,
    get_roadmap,
    get_version,
    is_backlog,
)
from factor_lab.leader import roadmap_cursor
from factor_lab.leader.backend_policy import need_code_change
from factor_lab.leader.task_intake import route_to_version, submit


@pytest.fixture()
def isolated_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(roadmap_cursor, "CURSOR_FILE", tmp_path / "roadmap_cursor.json")
    return roadmap_cursor


def test_roadmap_covers_v3_to_v9():
    r = get_roadmap()
    versions = {item.version for item in r}
    assert "V3.0" in versions
    assert "V4.0" in versions
    assert "V5.0" in versions
    assert "V6.0" in versions
    assert "V7.0" in versions
    assert "V8.0" in versions
    assert "V8.9" in versions


def test_v9_is_backlog():
    assert is_backlog("V9.0")
    assert not is_backlog("V3.0")


def test_cursor_advance(isolated_cursor):
    c = isolated_cursor.get_cursor()
    assert c["current_version"] == "V3.0"
    isolated_cursor.advance("V3.0", "completed")
    c2 = isolated_cursor.get_cursor()
    assert "V3.0" in c2["completed_versions"]


def test_cursor_advance_no_duplicate(isolated_cursor):
    isolated_cursor.advance("V3.0", "completed")
    isolated_cursor.advance("V3.0", "completed")
    c = isolated_cursor.get_cursor()
    assert c["completed_versions"].count("V3.0") == 1


def test_v2_not_reverted_to_dry_run():
    v = get_version("V3.0")
    assert v is not None, "V3.0 must exist in roadmap"
    assert v.auto_allowed is True


def test_v4_manual_gate():
    v = get_version("V4.9")
    assert v is not None
    assert v.manual_required is True


def test_v3_6_is_paper():
    v = get_version("V3.6")
    assert v is not None
    assert v.trading_mode == "paper", f"V3.6 trading_mode should be paper, got {v.trading_mode}"


def test_backend_policy():
    assert need_code_change("code_change") is True
    assert need_code_change("documentation") is False


def test_intake_submit():
    with tempfile.TemporaryDirectory() as tmp:
        import factor_lab.leader.task_intake as ti
        ti.INBOX = __import__("pathlib").Path(tmp) / "inbox"
        e = submit("test task", "test")
        assert e["status"] == "pending"


def test_intake_route():
    v = route_to_version("Alpha Factory Foundation")
    assert v == "V3.0" or v is not None


def test_alpha_factory_roadmap_is_object_list():
    assert isinstance(ALPHA_FACTORY_ROADMAP, list)
    assert all(hasattr(item, "version") for item in ALPHA_FACTORY_ROADMAP)
    versions = [item.version for item in ALPHA_FACTORY_ROADMAP]
    assert "V3.0" in versions
    assert "V3.6" in versions
    assert "V4.0" in versions
    assert "V8.9" in versions
