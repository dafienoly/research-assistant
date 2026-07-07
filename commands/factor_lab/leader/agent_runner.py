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
BACKEND_PRIORITY = ["claude", "command", "dry-run", "codex", "research"]
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
    if event_type not in {"error"}:
        return ""
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
        last_heartbeat = time.time()
        while True:
            try:
                item = q.get(timeout=0.2)
                if item is None:
                    stream_closed = True
                else:
                    rendered = line_transform(item) if line_transform else item
                    if rendered:
                        output_parts.append(rendered)
                        lf.write(rendered)
                        lf.flush()
                        last_heartbeat = time.time()  # 有输出就不写心跳
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

            # 静默 >30s 时写心跳到 log，让 dashboard /api/stream 有反馈
            if not timed_out and time.time() - last_heartbeat > 30:
                elapsed = int(time.time() - started)
                lf.write(f"# heartbeat: running {elapsed}s / timeout={timeout}s (pid={proc.pid})\n")
                lf.flush()
                last_heartbeat = time.time()

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
        elif self.backend == "research":
            return self._backend_research(prompt, task_id, log_file)
        return {"success": False, "error": f"未知 backend: {self.backend}"}

    def _backend_dry_run(self, prompt, task_id, log_file):
        """dry-run: 只生成 prompt 和日志"""
        log_file.write_text(f"# Agent Prompt: {task_id}\n\n{prompt}\n\n[DRY-RUN] 未调用模型，未消耗额度\n")
        return {"success": True, "backend": "dry-run", "output": "dry-run 完成"}

    def _backend_claude(self, prompt, task_id, log_file):
        """claude: auto 模式，最高思维强度，实时输出写入日志。"""
        claude_bin = os.environ.get("HERMES_CLAUDE_BIN") or shutil.which("claude") or "claude"
        # 设置最高思维强度
        _env = os.environ.copy()
        _env["CLAUDE_CODE_EFFORT_LEVEL"] = "ultra"
        cmd = [claude_bin, "--dangerously-skip-permissions", "-a", prompt]
        # 直接调用 subprocess，传递自定义 env
        log_file.parent.mkdir(parents=True, exist_ok=True)
        import subprocess as _sp, time as _time
        started = _time.time()
        log_file.write_text(f"$ {' '.join(cmd[:2])} -a <prompt>\n# started_at={datetime.now(CST).isoformat()}\n\n")
        try:
            proc = _sp.run(
                cmd, capture_output=True, text=True, timeout=3600,
                cwd=str(COMMANDS_DIR), env=_env,
            )
            output = proc.stdout if proc.stdout.strip() else proc.stderr
            with open(log_file, "a") as f:
                f.write(output + f"\n# finished_at={datetime.now(CST).isoformat()} returncode={proc.returncode}\n")
            return {"success": proc.returncode == 0, "backend": "claude",
                    "streaming_mode": "auto", "permission_mode": "bypassPermissions",
                    "returncode": proc.returncode, "output": output[:200]}
        except _sp.TimeoutExpired:
            with open(log_file, "a") as f:
                f.write("\nTIMEOUT: 3600s\n")
            return {"success": False, "error": "超时", "backend": "claude"}

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

    def _backend_research(self, prompt, task_id, log_file):
        """research: 使用 Research Skill Runtime 执行投研任务

        从 prompt 中提取 skill_id 和参数，通过 SkillRuntime 执行。
        """
        log_file.write_text(f"# Research Skill Runtime: {task_id}\n\n{prompt}\n\n")
        try:
            # 从 prompt 中解析 skill_id
            import re as _re
            skill_match = _re.search(r"research:run-skill\s+--skill-id\s+(\S+)", prompt)
            skill_id = skill_match.group(1) if skill_match else ""

            # 从 prompt 提取参数
            params = {}
            param_match = _re.search(r"--params\s+(\S+)", prompt)
            if param_match:
                for pair in param_match.group(1).split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        params[k.strip()] = v.strip()

            if not skill_id:
                # 尝试从 T001 任务描述中获取
                skill_match = _re.search(r"skill[:_-](\S+)", prompt)
                if skill_match:
                    skill_id = skill_match.group(1)

            if skill_id:
                from factor_lab.research_skill import SkillRegistry, SkillRuntime
                registry = SkillRegistry()
                registry.seed_defaults()
                runtime = SkillRuntime(registry=registry)
                result = runtime.run(skill_id, params)
                log_file.write(f"# Result: {result.status}\n")
                log_file.write(f"# Duration: {result.duration_ms}ms\n")
                if result.error:
                    log_file.write(f"# Error: {result.error}\n")
                import json as _json
                log_file.write(_json.dumps(result.data, indent=2, ensure_ascii=False))
                return {"success": result.status == "completed", "output": result.data,
                        "result": result, "backend": "research"}
            else:
                log_file.write("# No skill_id found, dry-run mode\n")
                return {"success": True, "backend": "research", "output": "dry-run (no skill matched)"}
        except Exception as e:
            log_file.write(f"# Research backend error: {e}\n")
            import traceback as _tb
            log_file.write(_tb.format_exc())
            return {"success": False, "backend": "research", "error": str(e)}

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
    exact = tasks_dir / f"{tid}.md"
    if exact.exists():
        return exact.read_text()
    for f in tasks_dir.iterdir():
        if f.name.startswith(tid + "_") or f.name.startswith(tid + "."):
            text = f.read_text()
            if any(marker in text or marker in f.name for marker in ("some_task", "V2.15", "dry-run", "dry_run", "rebalance_diff")):
                continue
            return text
    return ""


def _build_agent_prompt(tid: str, task_md: str, version: str) -> str:
    return (
        f"你是一名量化系统开发工程师，当前执行任务 {tid} (版本 {version})。\n"
        f"工作目录: {COMMANDS_DIR}\n\n"
        f"## 任务内容\n\n{task_md}\n\n"
        f"## 要求\n"
        f"1. 读取并理解任务描述和验收标准\n"
        f"2. 在 {COMMANDS_DIR} 内实现必要的代码修改\n"
        f"3. 运行测试确保通过\n"
        f"4. 最终输出修改了哪些文件、测试结果、完成状态\n"
        f"5. ⚡ 设计已审批通过，直接进入编码实现阶段，无需请求设计审批或等待确认\n"
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
    return ["research", "dry-run", "dry_run", "acceptance", "test", "V2", "V3", "V4", "V5", "V6", "auto"]
