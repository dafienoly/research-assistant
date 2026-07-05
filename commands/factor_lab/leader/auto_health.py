"""Automation Health — 后台自动工作流健康状态"""
import os, json, time, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.auto_loop import STATE_FILE, status
from factor_lab.leader.workloop import is_locked, read_completion, TASKS_DIR

CST = timezone(timedelta(hours=8))


def health() -> dict:
    """返回自动循环健康状态"""
    s = status()
    last_tick = s.get("last_tick", {})
    last_ts_str = last_tick.get("updated_at", "")

    tick_age = 999999
    if last_ts_str:
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            tick_age = (datetime.now(CST) - last_ts).total_seconds()
        except Exception:
            pass

    comp = read_completion()

    # crontab
    crontab_registered = False
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        crontab_registered = "run_hermes_agent_runner.sh" in r.stdout
    except Exception:
        pass

    # cron service
    cron_running = False
    try:
        cron_running = subprocess.run(["pgrep", "cron"], capture_output=True).returncode == 0
    except Exception:
        pass

    # log
    log_path = Path("/tmp/hermes_agent_runner.log")
    log_size = log_path.stat().st_size if log_path.exists() else 0

    # latest.json pending tasks
    latest = TASKS_DIR / "latest.json"
    pending_consumable = False
    if latest.exists():
        try:
            ld = json.loads(latest.read_text())
            pending_consumable = ld.get("status") == "pending" and ld.get("task_count", 0) > 0
        except Exception:
            pass

    return {
        "crontab_registered": crontab_registered,
        "cron_service_running": cron_running,
        "windows_task_registered": False,
        "latest_tick_at": last_ts_str or "never",
        "tick_age_seconds": tick_age,
        "tick_count": s.get("tick_count", 0),
        "lock_status": "running" if is_locked() else "free",
        "latest_completion_status": comp.get("status", "none") if comp else "none",
        "latest_pending_consumable": pending_consumable,
        "agent_log_size": log_size,
        "checked_at": datetime.now(CST).isoformat(),
    }
