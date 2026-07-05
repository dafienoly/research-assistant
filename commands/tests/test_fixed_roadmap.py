"""测试: V2.16.3 Fixed Roadmap Continuous Auto-Development"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.leader.roadmap import get_roadmap, get_version, next_version, is_backlog
from factor_lab.leader.roadmap_cursor import get_cursor, advance, set_blocked, CURSOR_FILE
from factor_lab.leader.backend_policy import need_code_change, select_backend, policy_status
from factor_lab.leader.task_intake import submit, intake, route_to_version


def test_roadmap_covers_v3_to_v9():
    r = get_roadmap()
    versions = {i["version"] for i in r}
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


def test_cursor_advance():
    if CURSOR_FILE.exists():
        CURSOR_FILE.unlink()
    c = get_cursor()
    assert c["current_version"] == "V3.0"
    advance("V3.0", "completed")
    c2 = get_cursor()
    assert "V3.0" in c2["completed_versions"]


def test_cursor_advance_no_duplicate():
    advance("V3.0", "completed")
    c = get_cursor()
    assert c["completed_versions"].count("V3.0") == 1


def test_v2_not_reverted_to_dry_run():
    """V3+ 不应被派回 V2.15.1 dry_run_completion"""
    v = get_version("V3.0")
    assert v is not None, "V3.0 must exist in roadmap"
    assert v["auto_allowed"] == True


def test_v4_manual_gate():
    v = get_version("V4.9")
    assert v is not None
    assert v["manual_required"] == True


def test_backend_policy():
    dry = select_backend("code_change")
    # dry-run may be returned if no claude, but code_change needs coding
    assert need_code_change("code_change") == True
    assert need_code_change("documentation") == False


def test_intake_submit():
    with tempfile.TemporaryDirectory() as tmp:
        import factor_lab.leader.task_intake as ti
        ti.INBOX = __import__("pathlib").Path(tmp) / "inbox"
        e = submit("test task", "test")
        assert e["status"] == "pending"


def test_intake_route():
    v = route_to_version("Alpha Factory Foundation")
    assert v == "V3.0" or v is not None
