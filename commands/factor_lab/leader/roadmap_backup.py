"""Version State Backup & Recovery — 自动备份与灾难恢复"""
import json, shutil, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap_cursor import CURSOR_FILE, get_cursor
from factor_lab.leader.workloop import TASKS_DIR

CST = timezone(timedelta(hours=8))
BACKUP_DIR = Path("/mnt/d/HermesReports/roadmap_backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def auto_backup():
    """自动备份当前 roadmap cursor 和相关状态"""
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"roadmap_backup_{ts}"
    backup.mkdir(parents=True, exist_ok=True)

    files = {
        "roadmap_cursor.json": CURSOR_FILE,
        "latest.json": TASKS_DIR / "latest.json",
        "latest_completion.json": TASKS_DIR / "latest_completion.json",
    }
    for name, src in files.items():
        if src.exists():
            shutil.copy2(src, backup / name)

    # 保留最近 20 份备份
    all_backups = sorted(BACKUP_DIR.iterdir())
    for old in all_backups[:-20]:
        shutil.rmtree(old, ignore_errors=True)

    return {"backup_id": ts, "path": str(backup)}


def list_backups():
    backups = []
    for d in sorted(BACKUP_DIR.iterdir()):
        if d.is_dir():
            cursor_file = d / "roadmap_cursor.json"
            if cursor_file.exists():
                c = json.loads(cursor_file.read_text())
                # 去掉 roadmap_backup_ 前缀，与 recover 函数兼容
                name = d.name
                if name.startswith("roadmap_backup_"):
                    name = name[len("roadmap_backup_"):]
                backups.append({"id": name, "current_version": c.get("current_version", "?"),
                                "completed": len(c.get("completed_versions", [])),
                                "backup_at": name})
    return backups


def recover(backup_id: str) -> dict:
    """从备份恢复 roadmap cursor 和相关状态"""
    backup = BACKUP_DIR / f"roadmap_backup_{backup_id}"
    if not backup.exists():
        return {"error": f"备份 {backup_id} 不存在"}

    results = []
    for name in ["roadmap_cursor.json", "latest.json", "latest_completion.json"]:
        src = backup / name
        if src.exists():
            dst = CURSOR_FILE if name == "roadmap_cursor.json" else TASKS_DIR / name
            shutil.copy2(src, dst)
            results.append(f"restored {name}")

    return {"status": "recovered", "backup_id": backup_id, "actions": results}


def auto_backup_on_advance(version: str, status: str):
    """在版本推进时自动备份"""
    backup = auto_backup()
    # 清理 24 小时内超过 48 份的冗余备份
    recent = sorted(BACKUP_DIR.iterdir(), reverse=True)
    if len(recent) > 48:
        for old in recent[48:]:
            ts_str = old.name.replace("roadmap_backup_", "")
            try:
                age = (datetime.now(CST) - datetime.strptime(ts_str, "%Y%m%d_%H%M%S")).total_seconds()
                if age < 86400:  # 24小时内
                    shutil.rmtree(old, ignore_errors=True)
            except Exception as e:
                import logging
                logging.warning("roadmap_backup: failed to clean old backup at %s: %s", BACKUP_DIR, e)
    return backup
