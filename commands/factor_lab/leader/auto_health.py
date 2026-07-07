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

    # crontab (legacy) — 仍注册但不再依赖
    crontab_registered = False
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        crontab_registered = "run_hermes_agent_runner.sh" in r.stdout
    except Exception:
        pass

    # Hermes 守护进程检查 (优先于系统 cron)
    daemon_running = False
    gateway_running = False
    cron_running = False

    # 1) 检查 tmux 守护会话 (hermes-daemon)
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", "hermes-daemon"],
            capture_output=True
        )
        daemon_running = r.returncode == 0
    except Exception:
        pass

    # 2) 检查 Hermes gateway 内部 cron ticker
    try:
        r = subprocess.run(
            ["hermes", "cron", "status"],
            capture_output=True, text=True, timeout=5
        )
        gateway_running = r.returncode == 0 and "ticker heartbeat" in r.stdout.lower()
    except Exception:
        pass

    # 3) 检查系统 cron (备用，WSL 下可能不可用)
    try:
        cron_running = subprocess.run(
            ["pgrep", "cron"], capture_output=True
        ).returncode == 0
    except Exception:
        pass

    # 健康判定：Hermes 守护或系统 cron 任一运行即可
    scheduler_healthy = daemon_running or gateway_running or cron_running

    # log
    log_path = Path("/tmp/hermes_agent_runner.log")
    log_size = log_path.stat().st_size if log_path.exists() else 0

    # latest.json pending tasks
    latest = TASKS_DIR / "latest.json"
    pending_consumable = False
    ld = {}
    if latest.exists():
        try:
            ld = json.loads(latest.read_text())
            pending_consumable = ld.get("status") == "pending" and ld.get("task_count", 0) > 0
        except Exception:
            pass

    latest_current = ld.get("current", "") if isinstance(ld, dict) else ""
    comp_version = comp.get("version", "") if comp else ""
    completion_matches_current = not comp_version or not latest_current or comp_version == latest_current
    completion_status = comp.get("status", "none") if comp else "none"
    current_completion_status = completion_status if completion_matches_current else "stale"

    return {
        "crontab_registered": crontab_registered,
        "cron_service_running": scheduler_healthy,
        "daemon_running": daemon_running,
        "gateway_running": gateway_running,
        "system_cron_running": cron_running,
        "windows_task_registered": False,
        "latest_tick_at": last_ts_str or "never",
        "tick_age_seconds": tick_age,
        "tick_count": s.get("tick_count", 0),
        "lock_status": "running" if is_locked() else "free",
        "latest_completion_status": completion_status,
        "current_completion_status": current_completion_status,
        "latest_completion_version": comp_version or "none",
        "latest_pending_consumable": pending_consumable,
        "agent_log_size": log_size,
        "checked_at": datetime.now(CST).isoformat(),
    }
