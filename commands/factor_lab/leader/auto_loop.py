"""Auto Loop State — 后台自动工作循环状态追踪"""
import os, json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.workloop import TASKS_DIR, read_completion, is_locked

CST = timezone(timedelta(hours=8))
STATE_FILE = TASKS_DIR / "auto_loop_state.json"


def tick():
    """记录一次轮询心跳"""
    comp = read_completion()
    state = {
        "updated_at": datetime.now(CST).isoformat(),
        "lock_status": "running" if is_locked() else "free",
        "completion_status": comp.get("status", "none") if comp else "none",
        "completed_tasks": comp.get("completed_tasks", []) if comp else [],
        "remaining_tasks": comp.get("remaining_tasks", []) if comp else [],
    }
    # 累积历史
    if STATE_FILE.exists():
        history = json.loads(STATE_FILE.read_text())
        ticks = history.get("ticks", [])
        ticks.append(state)
        if len(ticks) > 100:
            ticks = ticks[-100:]
        history["ticks"] = ticks
        history["last_tick"] = state
        history["tick_count"] = len(ticks)
    else:
        history = {"ticks": [state], "last_tick": state, "tick_count": 1}
    STATE_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    return state


def status():
    """读取状态"""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"tick_count": 0, "last_tick": None}
