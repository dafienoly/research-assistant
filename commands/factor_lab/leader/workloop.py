"""Hermes-Leader 自动工作循环"""
import os, json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
TASKS_DIR = Path("/home/ly/.hermes/research-assistant/agent_tasks")


# ─── Lock ───────────────────────────────────────────────────────

LOCK_FILE = TASKS_DIR / "current_run.lock"


def acquire_lock(run_id: str) -> bool:
    """获取任务锁，防止重复执行"""
    if LOCK_FILE.exists():
        lock_data = json.loads(LOCK_FILE.read_text())
        if lock_data.get("status") in ("running",):
            print(f"  ⚠️ 已有运行中任务: {lock_data.get('run_id')}")
            return False
    LOCK_FILE.write_text(json.dumps({"run_id": run_id, "status": "running",
                                      "acquired_at": datetime.now(CST).isoformat()}, indent=2))
    return True


def release_lock(status: str = "completed"):
    """释放任务锁"""
    if LOCK_FILE.exists():
        lock_data = json.loads(LOCK_FILE.read_text())
        lock_data["status"] = status
        lock_data["released_at"] = datetime.now(CST).isoformat()
        LOCK_FILE.write_text(json.dumps(lock_data, indent=2))


def is_locked() -> bool:
    return LOCK_FILE.exists() and json.loads(LOCK_FILE.read_text()).get("status") == "running"


# ─── Completion ─────────────────────────────────────────────────

LATEST_COMPLETION = TASKS_DIR / "latest_completion.json"


def write_completion(status: str, version: str, stage: str, report_dir: str = "",
                      summary: dict = None, completed_tasks: list = None,
                      remaining_tasks: list = None, next_question: str = ""):
    """写入完成信号"""
    completion = {
        "source": "hermes",
        "version": version,
        "stage": stage,
        "status": status,  # completed / partial / failed / blocked
        "report_dir": report_dir,
        "summary": summary or {"passed": 0, "failed": 0, "skeleton": 0},
        "completed_tasks": completed_tasks or [],
        "remaining_tasks": remaining_tasks or [],
        "next_question": next_question,
        "generated_at": datetime.now(CST).isoformat(),
    }
    LATEST_COMPLETION.write_text(json.dumps(completion, indent=2, ensure_ascii=False))
    return completion


def read_completion() -> dict:
    """读取完成信号"""
    if LATEST_COMPLETION.exists():
        return json.loads(LATEST_COMPLETION.read_text())
    return {}


# ─── Dispatch from completion ──────────────────────────────────

def dispatch_from_completion():
    """根据 latest_completion.json 自动派发下一轮任务"""
    comp = read_completion()
    if not comp:
        print("  ⚠️ latest_completion.json 不存在")
        return

    status = comp.get("status", "")
    version = comp.get("version", "")
    stage = comp.get("stage", "")
    next_q = comp.get("next_question", "")
    remaining = comp.get("remaining_tasks", [])

    run_id = f"auto_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"
    run_dir = TASKS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    tasks = []

    if status == "completed":
        if remaining:
            tasks = _build_tasks_for_remaining(remaining, version, stage)
        else:
            tasks = _build_next_stage_tasks(version, stage, next_q)
    elif status in ("partial", "failed", "blocked"):
        tasks = _build_tasks_from_remaining(comp, remaining, version)

    if not tasks:
        tasks = [{"id": "T001", "version": "unknown", "title": "待人工确认下一步",
                   "priority": "P0", "owner": "human_leader",
                   "description": "系统无法自动判断下一阶段任务，需要人工确认"}]

    # Write tasks
    task_list = []
    for i, t in enumerate(tasks):
        tid = f"T{i+1:03d}"
        task_list.append(tid)
        t_path = run_dir / f"tasks/{tid}_{t['title'][:50].replace('/', '_')}.md"
        t_path.parent.mkdir(exist_ok=True)
        _write_task_md(t_path, tid, t)

    # tasks.json
    (run_dir / "tasks.json").write_text(json.dumps(task_list, indent=2))

    # latest.json
    (TASKS_DIR / "latest.json").write_text(json.dumps({
        "run_id": run_id,
        "path": str(run_dir),
        "status": "pending",
        "current": version,
        "next": stage,
        "task_count": len(tasks),
        "updated_at": datetime.now(CST).isoformat(),
    }, indent=2))

    print(f"\n  ✅ 自动派发 {len(tasks)} 个任务")
    for i, t in enumerate(tasks):
        tid = t.get("tid") or f"T{i+1:03d}"
        print(f"    {tid}: {t['title']}")
    print(f"  📁 {run_dir}")
    print(f"  latest.json updated")


def _write_task_md(path, tid, t):
    desc = t.get("description", "")
    accept = t.get("acceptance", "")
    safety = t.get("safety", "")
    path.write_text(
        f"# {tid} — {t['title']}\n\n"
        f"- Version: {t['version']}\n"
        f"- Priority: {t.get('priority','P1')}\n"
        f"- Owner: {t.get('owner','governance_engineer')}\n"
        f"- Status: pending\n\n"
        f"## 描述\n\n{desc}\n\n"
        f"## 验收标准\n\n{accept}\n\n"
        f"## 安全边界\n\n{safety}\n"
    )


def _build_tasks_from_remaining(comp, remaining, version):
    """从 remaining_tasks 展开为具体任务"""
    tasks = []
    for r in remaining:
        task = _map_remaining_to_task(r, version)
        if task:
            tasks.append(task)
        else:
            tasks.append({
                "tid": "TASK", "title": r, "version": version, "priority": "P1",
                "owner": "governance_engineer",
                "description": f"完成 {r}",
                "acceptance": "功能完整",
                "safety": "auto_apply=False, no_live_trade=True",
            })
    return tasks


def _map_remaining_to_task(name, version):
    """映射 remaining task 名称到具体任务定义"""
    mapping = {
        "rebalance_diff_dry_run": {
            "tid": "rebalance_diff_dry_run", "title": "rebalance_diff real dry-run",
            "version": version, "priority": "P1", "owner": "governance_engineer",
            "description": (
                "实现 rebalance_diff 模块的完整干跑验证。\n\n"
                "模块: portfolio/rebalance_diff.py\n"
                "输入: unified_premarket_report.json + current_positions.csv\n"
                "输出: rebalance_diff_report.html, hold/sell/buy/skip 分类\n\n"
                "需要: 加载持仓 → 对比目标组合 → 生成调仓差异报告"
            ),
            "acceptance": (
                "- 能读取 current_positions.csv\n"
                "- 输出 hold/sell/buy 分类\n"
                "- 不自动下单\n"
                "- 报告可查看"
            ),
            "safety": "auto_apply=False, no_live_trade=True",
        },
        "order_preview_dry_run": {
            "tid": "order_preview_dry_run", "title": "order_preview real dry-run",
            "version": version, "priority": "P1", "owner": "governance_engineer",
            "description": (
                "实现 order_preview 模块的完整干跑验证。\n\n"
                "模块: order/order_preview.py\n"
                "输入: rebalance_diff.json\n"
                "输出: order_preview_report.html, tradable/blocked/review 分类\n\n"
                "需要: 从 rebalance_diff 读取 buy/sell 建议 → 生成委托预览 → 检查交易约束"
            ),
            "acceptance": (
                "- 输出 tradable/blocked 分类\n"
                "- 涨停买入被 blocked\n"
                "- 不自动下单"
            ),
            "safety": "auto_apply=False, no_live_trade=True",
        },
        "approval_dry_run": {
            "tid": "approval_dry_run", "title": "approval real dry-run",
            "version": version, "priority": "P1", "owner": "governance_engineer",
            "description": (
                "实现 approval 模块的完整干跑验证。\n\n"
                "模块: approval/risk_approval.py\n"
                "输入: order_preview.json\n"
                "输出: approval_report.html, approved/blocked/2nd_confirmation 分类\n\n"
                "需要: 加载委托预览 → 风控审批 → Kill Switch 检查 → 输出审批结论"
            ),
            "acceptance": (
                "- 输出 approved/blocked/2nd_confirmation 分类\n"
                "- Kill Switch 检查\n"
                "- 不自动下单"
            ),
            "safety": "auto_apply=False, no_live_trade=True",
        },
        "dry_run_completion": {
            "tid": "dry_run_completion", "title": "dry_run_completion",
            "version": version, "priority": "P1", "owner": "governance_engineer",
            "description": (
                "完成 rebalance_diff / order_preview / approval 三个模块的 real dry-run 实现。\n\n"
                "需要依次完成:\n"
                "1. rebalance_diff: 持仓加载 → 目标对比 → 调仓差异\n"
                "2. order_preview: 调仓建议 → 委托预览 → 交易约束\n"
                "3. approval: 委托预览 → 风控审批 → Kill Switch"
            ),
            "acceptance": (
                "- rebalance_diff 完整干跑\n"
                "- order_preview 完整干跑\n"
                "- approval 完整干跑\n"
                "- 不自动下单"
            ),
            "safety": "auto_apply=False, no_live_trade=True",
        },
    }
    return mapping.get(name)


def _build_tasks_for_remaining(remaining, version, stage):
    return [{"id": r, "version": version, "title": r, "priority": "P1",
             "owner": "governance_engineer", "description": f"完成 {r} (剩余任务)"} for r in remaining]


def _build_next_stage_tasks(version, stage, next_q):
    # 安全限制: 不自动派发 live/paper config 修改
    safe_prefixes = ("V2", "V3", "research", "dry-run", "dry_run", "acceptance", "test", "auto")
    if any(version.startswith(p) for p in safe_prefixes):
        return [{"title": "dry_run_completion", "version": "V2.15.1", "priority": "P1",
                 "owner": "governance_engineer",
                 "description": "完成 rebalance_diff/order_preview/approval 的 real dry-run 实现"}]
    # 不安全路径 -> 停在人工确认
    return [{"title": "next_stage_needs_human_confirmation", "version": version, "priority": "P0",
             "owner": "human_leader",
             "description": f"下一阶段 {next_q} 需要人工确认后才能继续"}]


def _build_remediation_tasks(comp):
    return [{"title": f"remediation_{comp.get('status','failed')}", "version": comp.get("version", "?"),
             "priority": "P0", "owner": "governance_engineer",
             "description": f"修复 {comp.get('version','')} 中的 {len(comp.get('remaining_tasks',[]))} 个失败/阻塞任务"}]


# ─── Consume latest task ──────────────────────────────────────

def consume_latest_task():
    """Hermes 消费 latest.json 中的任务"""
    latest = TASKS_DIR / "latest.json"
    if not latest.exists():
        print("  ⚠️ latest.json 不存在")
        return

    data = json.loads(latest.read_text())
    run_dir = Path(data["path"])
    tasks_json = run_dir / "tasks.json"
    if not tasks_json.exists():
        print("  ⚠️ tasks.json 不存在")
        return

    task_ids = json.loads(tasks_json.read_text())
    if not task_ids:
        print("  ✅ 无待处理任务")
        return

    run_id = data["run_id"]
    if not acquire_lock(run_id):
        return

    print(f"\n  📋 消费任务包: {run_id} ({len(task_ids)} 个任务)")
    for tid in task_ids:
        t_path = run_dir / f"tasks/{tid}_*.md"
        print(f"    {tid}: pending")

    # 写完成信号 (默认 partial, 等待实际执行完成)
    write_completion("partial", data.get("current", "?"), data.get("next", "?"),
                      completed_tasks=[], remaining_tasks=task_ids,
                      next_question="请在任务完成后更新 completion")
    release_lock("completed")


def main():
    """CLI 入口"""
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "dispatch" and "--from-latest-completion" in sys.argv:
        dispatch_from_completion()
    elif cmd == "consume-latest-task":
        consume_latest_task()
    else:
        print("Usage: python workloop.py dispatch --from-latest-completion")
        print("       python workloop.py consume-latest-task")
