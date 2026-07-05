"""Hermes Leader automatic workloop runner."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from factor_lab.leader.workloop import TASKS_DIR, dispatch_from_completion, consume_latest_task, read_completion, is_locked
from factor_lab.leader.github_sync import sync_version

CST = timezone(timedelta(hours=8))
STATE_PATH = TASKS_DIR / "auto_loop_state.json"
LATEST_PATH = TASKS_DIR / "latest.json"
SAFE_AUTO_STAGES = ("research", "dry_run", "acceptance", "dry-run", "dry_run_completion")


def loop_once(auto_consume: bool = True, auto_github: bool = True) -> dict:
    """Run one automatic workloop tick."""
    state = _read_state()
    completion = read_completion()
    latest = _read_json(LATEST_PATH)
    actions: list[str] = []

    if is_locked():
        return _write_state({"status": "locked", "actions": actions, "reason": "another task is running", "updated_at": _now()})

    if not completion:
        return _write_state({"status": "idle", "actions": actions, "reason": "latest_completion.json missing", "updated_at": _now()})

    completion_key = _completion_key(completion)
    status = completion.get("status", "")
    stage = completion.get("stage", "")
    version = completion.get("version", "unknown")
    remaining = completion.get("remaining_tasks", []) or []

    if status in ("partial", "failed") and completion_key != state.get("last_dispatched_completion"):
        dispatch_from_completion()
        actions.append("dispatch_from_completion")
        state["last_dispatched_completion"] = completion_key
        latest = _read_json(LATEST_PATH)

    elif status == "blocked":
        actions.append("blocked_waiting_for_human")

    elif status == "completed":
        if auto_github and completion_key != state.get("last_github_completion"):
            sync_version(version=version, summary=_summary_text(completion), dry_run=False)
            actions.append("github_sync")
            state["last_github_completion"] = completion_key
        if _is_safe_stage(stage) and completion_key != state.get("last_dispatched_completion"):
            dispatch_from_completion()
            actions.append("dispatch_next_stage")
            state["last_dispatched_completion"] = completion_key
            latest = _read_json(LATEST_PATH)
        elif not _is_safe_stage(stage):
            actions.append("unsafe_stage_waiting_for_human")

    if auto_consume:
        latest = _read_json(LATEST_PATH)
        if latest and latest.get("status") == "pending":
            latest_key = f"{latest.get('run_id')}|{latest.get('updated_at')}"
            if latest_key != state.get("last_consumed_latest"):
                consume_latest_task()
                actions.append("consume_latest_task")
                state["last_consumed_latest"] = latest_key

    state.pop("reason", None)
    state.update({
        "status": "ok",
        "actions": actions or ["idle"],
        "completion_status": status,
        "completion_stage": stage,
        "completion_version": version,
        "remaining_tasks": remaining,
        "latest_run_id": latest.get("run_id") if latest else "",
        "updated_at": _now(),
    })
    return _write_state(state)


def loop_watch(interval_seconds: int = 180, max_ticks: int = 0, auto_consume: bool = True, auto_github: bool = True) -> None:
    tick = 0
    while True:
        tick += 1
        print(json.dumps(loop_once(auto_consume=auto_consume, auto_github=auto_github), indent=2, ensure_ascii=False))
        if max_ticks and tick >= max_ticks:
            return
        time.sleep(interval_seconds)


def _is_safe_stage(stage: str) -> bool:
    s = (stage or "").lower()
    return any(prefix in s for prefix in SAFE_AUTO_STAGES)


def _completion_key(completion: dict) -> str:
    return "|".join([str(completion.get(k, "")) for k in ("version", "stage", "status", "generated_at")])


def _summary_text(completion: dict) -> str:
    summary = completion.get("summary", {}) or {}
    completed = ", ".join(completion.get("completed_tasks", []) or [])
    return f"stage={completion.get('stage','')}; status={completion.get('status','')}; passed={summary.get('passed', 0)}; failed={summary.get('failed', 0)}; completed_tasks={completed}"


def _read_state() -> dict:
    return _read_json(STATE_PATH)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict) -> dict:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return state


def _now() -> str:
    return datetime.now(CST).isoformat()
