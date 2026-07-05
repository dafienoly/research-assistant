"""Agent Runner V2.15.2 — 可插拔后端自动执行器"""
import os, sys, json, subprocess, traceback, shutil, threading, queue, time
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


def _extract_claude_stream_text(line: str) -> str:
    """把 Claude Code stream-json 事件压成可读文本。"""
    try:
        event = json.loads(line)
    except Exception:
        return line

    def _texts(value):
        found: list[str] = []
        if isinstance(value, str):
            return found
        if isinstance(value, list):
            for item in value:
                found.extend(_texts(item))
            return found
        if not isinstance(value, dict):
            return found
        text = value.get("text")
        if isinstance(text, str):
            found.append(text)
        for key in ("delta", "message", "content", "result"):
            if key in value:
                found.extend(_texts(value[key]))
        return found

    text = "".join(_texts(event))
    if text:
        return text

    event_type = event.get("type") or event.get("event") or "event"
    subtype = event.get("subtype") or event.get("name") or ""
    label = f"[claude:{event_type}{':' + subtype if subtype else ''}]"
    return label + "\n"


def _run_streaming_process(cmd, log_file: Path, input_text: str | None = None,
                           timeout: int = 600, shell: bool = False,
                           line_transform=None) -> dict:
    """运行子进程，并把 stdout/stderr 合并实时写入 log_file。

    Dashboard 的 /api/stream 会 tail agent_logs/*.log；这里必须边运行边 flush，
    否则前端只能在 Claude/command 完成后看到整段输出，仍然是黑盒。
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    output_parts: list[str] = []
    q: queue.Queue[str | None] = queue.Queue()

    def _reader(stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                q.put(line)
        finally:
            try:
                stream.close()
            except Exception:
                pass
            q.put(None)

    printable_cmd = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
    with log_file.open("w", encoding="utf-8", errors="replace") as lf:
        lf.write(f"$ {printable_cmd}\n")
        lf.write(f"# started_at={datetime.now(CST).isoformat()}\n\n")
        lf.flush()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(COMMANDS_DIR),
                stdin=subprocess.PIPE if input_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=shell,
                env=os.environ.copy(),
            )
        except FileNotFoundError:
            lf.write("ERROR: command not found\n")
            lf.flush()
            return {"success": False, "error": "command_not_found", "output": ""}

        if input_text is not None and proc.stdin is not None:
            try:
                proc.stdin.write(input_text)
                if not input_text.endswith("\n"):
                    proc.stdin.write("\n")
                proc.stdin.close()
            except BrokenPipeError:
                pass

        reader = threading.Thread(target=_reader, args=(proc.stdout,), daemon=True)
        reader.start()
        stream_closed = False
        timed_out = False
        while True:
            try:
                item = q.get(timeout=0.2)
                if item is None:
                    stream_closed = True
                else:
                    rendered = line_transform(item) if line_transform else item
                    output_parts.append(rendered)
                    lf.write(rendered)
                    lf.flush()
            except queue.Empty:
                pass

            if not timed_out and time.time() - started > timeout:
                timed_out = True
                lf.write(f"\nTIMEOUT: process exceeded {timeout}s, killed.\n")
                lf.flush()
                try:
                    proc.kill()
                except Exception:
                    pass

            if stream_closed and proc.poll() is not None:
                break

        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            returncode = -9

        finished_at = datetime.now(CST).isoformat()
        lf.write(f"\n# finished_at={finished_at} returncode={returncode}\n")
        lf.flush()

    output = "".join(output_parts)
    if timed_out:
        return {"success": False, "error": "超时", "returncode": returncode, "output": output[:200]}
    return {"success": returncode == 0, "returncode": returncode, "output": output[:200]}


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
        # loop-once disabled — auto_executor manages its own advancement
        # _trigger_loop_once()

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
        """claude: stream-json 模式，实时写入可读回答供 Dashboard SSE tail。"""
        claude_bin = os.environ.get("HERMES_CLAUDE_BIN") or shutil.which("claude") or "claude"
        cmd = [
            claude_bin, "--print",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--input-format", "text",
            "--permission-mode", "bypassPermissions",
            "--dangerously-skip-permissions",
            "--add-dir", str(COMMANDS_DIR),
            "--model", "deepseek-v4",
        ]
        result = _run_streaming_process(
            cmd, log_file, input_text=prompt, timeout=3600,
            line_transform=_extract_claude_stream_text,
        )
        result["backend"] = "claude"
        result["streaming_mode"] = "stream-json"
        result["permission_mode"] = "bypassPermissions"
        if result.get("error") == "command_not_found":
            result["error"] = "claude 命令未找到"
        return result

    def _backend_command(self, prompt, task_id, log_file):
        """command: 使用环境变量 HERMES_AGENT_COMMAND 模板"""
        cmd_template = os.environ.get("HERMES_AGENT_COMMAND", "")
        if not cmd_template:
            log_file.write_text("ERROR: HERMES_AGENT_COMMAND 未设置")
            return {"success": False, "error": "HERMES_AGENT_COMMAND 未设置"}

        prompt_file = self.log_dir / f"{task_id}_prompt.txt"
        prompt_file.write_text(prompt)

        cmd = cmd_template.format(prompt_file=str(prompt_file), repo_root=str(REPO_ROOT))
        result = _run_streaming_process(cmd, log_file, timeout=600, shell=True)
        result["backend"] = "command"
        return result

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
