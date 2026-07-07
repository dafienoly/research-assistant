"""Roadmap Cursor — 路线图进度追踪"""
import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap import get_roadmap, next_version, is_backlog

CST = timezone(timedelta(hours=8))
CURSOR_FILE = Path("/home/ly/.hermes/research-assistant/agent_tasks/roadmap_cursor.json")

DEFAULT = {
    "status": "running",
    "current_version": "V3.0",
    "completed_versions": ["V2.16.1"],
    "failed_versions": [],
    "blocked_version": "",
    "blocked_reason": "",
    "manual_gate": "",
    "last_run_id": "",
    "last_commit": "",
    "updated_at": "",
    "auto_allowed_until": "V8.9",
    "live_trading_allowed": False,
    "next_version": "V3.0",
}

def _load():
    if CURSOR_FILE.exists():
        data = json.loads(CURSOR_FILE.read_text())
        return {**DEFAULT, **data}
    return dict(DEFAULT)

def _save(data):
    CURSOR_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def get_cursor():
    c = _load()
    # 自动计算 next_version ← 基于 current_version
    from factor_lab.leader.roadmap import next_version, is_backlog
    nv = next_version(c.get("current_version", ""))
    if nv and not is_backlog(nv.version):
        c["next_version"] = nv.version
    else:
        c["next_version"] = ""
    return c

def advance(version, status="completed", commit="", run_id=""):
    c = _load()
    if status == "completed":
        if version not in c["completed_versions"]:
            c["completed_versions"].append(version)
            c["completed_versions"] = list(dict.fromkeys(c["completed_versions"]))
        from factor_lab.leader.roadmap import next_version, is_backlog
        nv = next_version(version)
        if nv and not is_backlog(nv.version):
            c["current_version"] = nv.version
            c["next_version"] = nv.version
        else:
            c["next_version"] = ""
        c["status"] = "running"
    elif status == "failed":
        if version not in c["failed_versions"]:
            c["failed_versions"].append(version)
        c["status"] = "running"
    elif status == "blocked":
        c["blocked_version"] = version
        c["status"] = "blocked"
    c["last_run_id"] = run_id or c.get("last_run_id", "")
    c["last_commit"] = commit or c.get("last_commit", "")
    c["updated_at"] = datetime.now(CST).isoformat()
    _save(c)
    return c

def set_blocked(version, reason):
    c = _load()
    c["blocked_version"] = version
    c["blocked_reason"] = reason
    c["status"] = "blocked"
    c["updated_at"] = datetime.now(CST).isoformat()
    _save(c)

def status_text():
    c = _load()
    return f"  Version: {c['current_version']}\n  Status: {c['status']}\n  Completed: {len(c['completed_versions'])} versions\n  Auto allowed until: {c['auto_allowed_until']}"
