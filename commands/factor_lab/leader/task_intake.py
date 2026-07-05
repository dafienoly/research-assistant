"""Task Intake — 任务入口与自动路由"""
import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap import get_roadmap, get_version, is_backlog

CST = timezone(timedelta(hours=8))
INBOX = Path("/home/ly/.hermes/research-assistant/agent_tasks/inbox")
TASKS = Path("/home/ly/.hermes/research-assistant/agent_tasks")

def submit(task_text: str, title: str = "", source: str = "inbox") -> dict:
    INBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    tid = f"TASK_{ts}"
    entry = {"id": tid, "title": title or tid, "text": task_text, "source": source, "status": "pending", "created_at": datetime.now(CST).isoformat()}
    (INBOX / f"{tid}.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False))
    return entry

def intake() -> dict:
    """扫描 inbox，自动路由到对应路线图版本"""
    INBOX.mkdir(parents=True, exist_ok=True)
    tasks = []
    for f in sorted(INBOX.glob("*.json")):
        tasks.append(json.loads(f.read_text()))
    for f in sorted(INBOX.glob("*.md")):
        content = f.read_text()
        tasks.append({"id": f.stem, "title": f.stem, "text": content, "source": "inbox_md", "status": "pending"})
    return {"inbox_count": len(tasks), "tasks": tasks}

def route_to_version(task_text: str) -> str:
    """简单路由：根据关键词判断版本"""
    roadmap = get_roadmap()
    for r in roadmap[:60]:
        if r.get("name","").lower() in task_text.lower():
            return r["version"]
        if any(kw in task_text for kw in [r["version"], r["name"]]):
            return r["version"]
    return None

def build_task_package(version: str, tasks: list) -> str:
    """为路线图版本生成 task package"""
    import subprocess as sp
    run_id = f"auto_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"
    run_dir = TASKS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tasks").mkdir(exist_ok=True)
    for i, t in enumerate(tasks):
        tid = f"T{i+1:03d}"
        (run_dir / "tasks" / f"{tid}.md").write_text(t.get("text", t.get("title","")))
    (run_dir / "tasks.json").write_text(json.dumps([f"T{i+1:03d}" for i in range(len(tasks))], indent=2))
    # Write latest.json
    (TASKS / "latest.json").write_text(json.dumps({
        "run_id": run_id, "path": str(run_dir), "status": "pending",
        "current": version, "next": version, "task_count": len(tasks),
        "updated_at": datetime.now(CST).isoformat(),
    }, indent=2))
    return run_id
