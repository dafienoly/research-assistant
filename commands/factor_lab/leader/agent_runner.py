"""Agent Runner V2.15.2 — 可插拔后端自动执行器"""
import os, sys, json, subprocess, traceback, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.workloop import (
    acquire_lock, release_lock, is_locked,
    write_completion, read_completion, TASKS_DIR,
)

CST = timezone(timedelta(hours=8))
REPO_ROOT = Path("/home/ly/.hermes/research-assistant")
COMMANDS_DIR = REPO_ROOT / "commands"
BACKEND_PRIORITY = ["claude", "command", "dry-run", "codex"]
DEFAULT_BACKEND = "claude"


class AgentRunner:
    def __init__(self, backend: str = DEFAULT_BACKEND, interval: int = 180):
        self.backend = backend if backend in BACKEND_PRIORITY else DEFAULT_BACKEND
        self.interval = interval
        self.run_id = ""
        self.log_dir = None

    def run_once(self) -> dict:
        """执行一次任务消费"""
        # 检查锁
        if is_locked():
            return {"error": "已有运行中任务", "status": "locked"}

        # 读取 latest.json
        latest = TASKS_DIR / "latest.json"
        if not latest.exists():
            write_completion("blocked", "unknown", "no_tasks",
                             next_question="latest.json 不存在，请先派发任务")
            return {"error": "latest.json 不存在", "status": "blocked"}

        data = json.loads(latest.read_text())
        run_dir = Path(data["path"])
        tasks_json = run_dir / "tasks.json"
        if not tasks_json.exists():
            write_completion("blocked", data.get("current", "?"), data.get("next", "?"),
                             next_question="tasks.json 不存在")
            return {"error": "tasks.json 不存在", "status": "blocked"}

        self.run_id = data["run_id"]
        if not acquire_lock(self.run_id):
            return {"error": "无法获取锁", "status": "locked"}

        task_ids = json.loads(tasks_json.read_text())
        self.log_dir = TASKS_DIR / "agent_logs" / self.run_id
        os.makedirs(self.log_dir, exist_ok=True)

        # 安全检查: 阻止 unsafe 阶段
        current_version = data.get("current", "")
        unsafe_prefixes = ("live", "broker", "real_execution", "capital")
        if any(current_version.lower().startswith(p) for p in unsafe_prefixes):
            write_completion("blocked", current_version, data.get("next", "?"),
                             next_question=f"阶段 {current_version} 需要人工确认",
                             remaining_tasks=task_ids)
            release_lock("blocked")
            return {"error": f"阶段 {current_version} 不安全，已阻塞", "status": "blocked"}

        # 读取任务内容并生成 prompt
        prompts = []
        completed = []
        remaining = []

        for tid in task_ids:
            task_md = _find_task_file(run_dir / "tasks", tid)
            if not task_md:
                remaining.append(tid)
                continue

            prompt = _build_agent_prompt(tid, task_md, current_version)
            prompts.append(prompt)

            # 调用 backend 执行
            result = self._execute(prompt, tid)
            if result.get("success"):
                completed.append(tid)
            else:
                remaining.append(tid)

        # 写完成信号
        status = "completed" if not remaining else "partial"
        write_completion(
            status=status,
            version=current_version,
            stage=data.get("next", ""),
            report_dir=str(self.log_dir),
            summary={"passed": len(completed), "failed": len(remaining)},
            completed_tasks=completed,
            remaining_tasks=remaining,
            next_question="任务执行完成" if status == "completed" else f"剩余 {len(remaining)} 个任务待完成",
        )
        release_lock(status)

        # 完成后触发 loop-once
        _trigger_loop_once()

        return {"status": status, "completed": completed, "remaining": remaining,
                "log_dir": str(self.log_dir)}

    def _execute(self, prompt: str, task_id: str) -> dict:
        """根据 backend 执行任务"""
        log_file = self.log_dir / f"{task_id}.log"

        if self.backend == "dry-run":
            return self._backend_dry_run(prompt, task_id, log_file)
        elif self.backend == "claude":
            return self._backend_claude(prompt, task_id, log_file)
        elif self.backend == "command":
            return self._backend_command(prompt, task_id, log_file)
        elif self.backend == "codex":
            return self._backend_codex(prompt, task_id, log_file)
        return {"success": False, "error": f"未知 backend: {self.backend}"}

    def _backend_dry_run(self, prompt, task_id, log_file):
        """dry-run: 只生成 prompt 和日志"""
        log_file.write_text(f"# Agent Prompt: {task_id}\n\n{prompt}\n\n[DRY-RUN] 未调用模型，未消耗额度\n")
        return {"success": True, "backend": "dry-run", "output": "dry-run 完成"}

    def _backend_claude(self, prompt, task_id, log_file):
        """claude: 调用本地 Claude Code CLI"""
        cmd = ["claude", "--print", "--add-dir", str(COMMANDS_DIR), "--model", "deepseek-v4"]
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
            output = result.stdout + result.stderr
            log_file.write_text(output)
            return {"success": result.returncode == 0, "backend": "claude", "output": output[:200]}
        except subprocess.TimeoutExpired:
            log_file.write_text("TIMEOUT: claude 执行超时")
            return {"success": False, "error": "超时"}
        except FileNotFoundError:
            log_file.write_text("ERROR: claude 命令未找到")
            return {"success": False, "error": "claude 命令未找到"}

    def _backend_command(self, prompt, task_id, log_file):
        """command: 使用环境变量 HERMES_AGENT_COMMAND 模板"""
        cmd_template = os.environ.get("HERMES_AGENT_COMMAND", "")
        if not cmd_template:
            log_file.write_text("ERROR: HERMES_AGENT_COMMAND 未设置")
            return {"success": False, "error": "HERMES_AGENT_COMMAND 未设置"}

        prompt_file = self.log_dir / f"{task_id}_prompt.txt"
        prompt_file.write_text(prompt)

        cmd = cmd_template.format(prompt_file=str(prompt_file), repo_root=str(REPO_ROOT))
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
            output = result.stdout + result.stderr
            log_file.write_text(output)
            return {"success": result.returncode == 0, "backend": "command", "output": output[:200]}
        except subprocess.TimeoutExpired:
            log_file.write_text("TIMEOUT: command 执行超时")
            return {"success": False, "error": "超时"}

    def _backend_codex(self, prompt, task_id, log_file):
        """codex: 备用后端，不默认启用"""
        log_file.write_text(f"WARNING: Codex 后端已调用 - {task_id}\n\n{prompt}\n")
        return {"success": True, "backend": "codex", "output": "codex 备用后端执行"}

    def watch(self):
        """轮询模式"""
        print(f"  👁️  agent-runner watch 模式 (interval={self.interval}s, backend={self.backend})")
        import time
        while True:
            result = self.run_once()
            print(f"  [{datetime.now(CST).strftime('%H:%M:%S')}] {result.get('status', '?')}")
            time.sleep(self.interval)


def _find_task_file(tasks_dir: Path, tid: str) -> str:
    if not tasks_dir.exists():
        return ""
    for f in tasks_dir.iterdir():
        if f.name.startswith(tid + "_") or f.name.startswith(tid + "."):
            return f.read_text()
    return ""


def _build_agent_prompt(tid: str, task_md: str, version: str) -> str:
    return (
        f"你是 Hermes Agent，当前执行任务 {tid} (版本 {version})。\n"
        f"工作目录: {COMMANDS_DIR}\n\n"
        f"## 任务内容\n\n{task_md}\n\n"
        f"## 要求\n"
        f"1. 读取并理解任务描述和验收标准\n"
        f"2. 在 {COMMANDS_DIR} 内实现必要的代码修改\n"
        f"3. 运行测试确保通过\n"
        f"4. 最终输出修改了哪些文件、测试结果、完成状态\n"
    )


def _trigger_loop_once():
    """完成后触发 leader:loop-once"""
    try:
        subprocess.run(
            [sys.executable, str(COMMANDS_DIR / "hermes_cli.py"), "leader:loop-once"],
            capture_output=True, timeout=30,
            cwd=str(COMMANDS_DIR),
        )
    except Exception:
        pass


def loop_once():
    """读取 completion 并 dispatch/github-sync"""
    comp = read_completion()
    if not comp:
        print("  ⚠️ 无 completion")
        return
    status = comp.get("status", "")
    if status == "completed":
        from factor_lab.leader.workloop import dispatch_from_completion
        dispatch_from_completion()
    else:
        print(f"  ⏳ completion.status={status}，跳过 dispatch")


def safe_stages() -> list:
    return ["research", "dry-run", "dry_run", "acceptance", "test", "V2", "V3", "auto"]
