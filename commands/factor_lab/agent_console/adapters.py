"""Agent Console Adapters — Hermes / Claude 引擎"""
import subprocess, json, os, threading, time, pty, select
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from config import VENV_PYTHON
from factor_lab.agent_console.schemas import AgentEvent
from factor_lab.agent_console.sessions import append_event, update_status, SESSIONS_DIR

CST = timezone(timedelta(hours=8))
VENV = VENV_PYTHON
CLI = str(Path(VENV_PYTHON).resolve().parent.parent.parent / "commands" / "hermes_cli.py")
COMMANDS = "/home/ly/.hermes/research-assistant/commands"


# ─── Capabilities ───────────────────────────────────────────────

ADAPTER_INFO = {
    "hermes_demo": {
        "label": "Hermes Agent (演示模式)", "streaming": "buffered",
        "supports_realtime_delta": False,
        "description": "运行 leader:dispatch --dry-run，用于验证链路",
    },
    "hermes_research": {
        "label": "Hermes Agent (研究模式)", "streaming": "buffered",
        "supports_realtime_delta": False,
        "description": "运行投研分析: leader:automation-status + roadmap-status",
    },
    "claude_code": {
        "label": "Claude Code (--print)", "streaming": "buffered",
        "supports_realtime_delta": False,
        "description": "Claude Code --print 模式，回答缓冲后一次性输出。"
        "实验性 PTY 路径在 adapters.py 中预留。",
    },
}


def get_adapters() -> list:
    """返回可用 adapter 列表"""
    return [
        {"id": "hermes_demo", **ADAPTER_INFO["hermes_demo"]},
        {"id": "hermes_research", **ADAPTER_INFO["hermes_research"]},
        {"id": "claude_code", **ADAPTER_INFO["claude_code"]},
    ]


def start_session(sid: str, agent: str, prompt: str):
    update_status(sid, "running")
    if agent == "hermes_demo":
        _run_hermes_demo(sid, prompt)
    elif agent == "hermes_research":
        _run_hermes_research(sid, prompt)
    elif agent == "claude_code":
        _run_claude(sid, prompt)
    else:
        append_event(sid, AgentEvent("error", sid, data=f"Unknown agent: {agent}", status="failed"))
        update_status(sid, "failed")


# ─── Hermes Demo Mode ───────────────────────────────────────────


def _run_hermes_demo(sid: str, prompt: str):
    """演示模式: 包装 leader:dispatch --dry-run"""
    append_event(sid, AgentEvent("answer_delta", sid,
                 data=f"## Hermes Agent (演示模式)\n\n任务: {prompt}\n\n运行 dry-run...\n\n",
                 status="running"))
    try:
        proc = subprocess.run([VENV, CLI, "leader:dispatch", "--dry-run"],
                               capture_output=True, text=True, timeout=120, cwd=COMMANDS)
        output = proc.stdout + proc.stderr
        answer, diagnostic = _split_output(output)
        for chunk in _chunkify(answer):
            append_event(sid, AgentEvent("answer_delta", sid, data=chunk, status="running"))
        for line in diagnostic:
            append_event(sid, AgentEvent("diagnostic", sid, data=line))
        status = "completed" if proc.returncode == 0 else "failed"
        append_event(sid, AgentEvent("done", sid, data="", status=status))
        update_status(sid, status)
    except Exception as e:
        append_event(sid, AgentEvent("error", sid, data=str(e), status="failed"))
        update_status(sid, "failed")


# ─── Hermes Research Mode ───────────────────────────────────────


def _run_hermes_research(sid: str, prompt: str):
    """研究模式: 运行真实投研命令，输出分析正文"""
    append_event(sid, AgentEvent("answer_delta", sid,
                 data=f"## Hermes Agent (研究模式)\n\n## 任务\n\n{prompt}\n\n## 分析\n\n",
                 status="running"))
    try:
        # 运行多个 Hermes 命令获取分析数据
        cmds = [
            ([VENV, CLI, "leader:automation-status"], "系统状态"),
            ([VENV, CLI, "leader:roadmap-status"], "路线图"),
        ]
        full_answer = ""
        failed_commands = []
        for cmd, label in cmds:
            append_event(sid, AgentEvent("diagnostic", sid, data=f"运行: {' '.join(cmd[-2:])}"))
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=COMMANDS)
            output = proc.stdout + proc.stderr
            if proc.returncode != 0:
                failed_commands.append((label, proc.returncode))
                append_event(sid, AgentEvent(
                    "diagnostic", sid,
                    data=f"{label} failed with returncode={proc.returncode}",
                    status="failed",
                ))
            full_answer += f"\n### {label}\n\n"
            # 提取可读内容作为 answer
            for line in output.split("\n"):
                if line.strip() and not line.startswith("<frozen"):
                    full_answer += line.strip() + "\n"
            # stderr 作为 diagnostic
            if proc.stderr:
                for line in proc.stderr.split("\n"):
                    if line.strip():
                        append_event(sid, AgentEvent("diagnostic", sid, data=line))

        # 发送 answer_delta
        for chunk in _chunkify(full_answer):
            append_event(sid, AgentEvent("answer_delta", sid, data=chunk, status="running"))

        status = "failed" if failed_commands else "completed"
        completion_text = "\n---\n*分析完成。诊断信息见折叠面板。*"
        if failed_commands:
            failed_labels = ", ".join(f"{label}(rc={rc})" for label, rc in failed_commands)
            completion_text = f"\n---\n*分析未完全完成：{failed_labels}。诊断信息见折叠面板。*"
        append_event(sid, AgentEvent("answer_delta", sid, data=completion_text, status=status))
        append_event(sid, AgentEvent("done", sid, data="", status=status))
        update_status(sid, status)
    except Exception as e:
        append_event(sid, AgentEvent("error", sid, data=str(e), status="failed"))
        update_status(sid, "failed")


# ─── Claude Code Mode ───────────────────────────────────────────


def _run_claude(sid: str, prompt: str):
    """Claude Code --print 模式 (buffered, 非逐 token)"""
    append_event(sid, AgentEvent("answer_delta", sid,
                 data=f"## Claude Code (缓冲模式)\n\n> ⚠️ Claude Code --print 模式在命令完成后才输出完整回答，"
                 f"非逐 token 实时流。\n\n任务: {prompt}\n\n",
                 status="running"))
    claude_bin = os.environ.get("HERMES_CLAUDE_BIN",
                                "/home/ly/.nvm/versions/node/v22.16.0/bin/claude")
    try:
        # 尝试 PTY 模式 (实验性)
        pty_used = False
        returncode = None
        try:
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen([claude_bin, "--print", "--add-dir", COMMANDS],
                                     stdin=subprocess.PIPE, stdout=slave_fd, stderr=slave_fd,
                                     text=True, close_fds=True)
            os.close(slave_fd)
            proc.stdin.write(prompt)
            proc.stdin.close()
            output = ""
            started = time.time()
            while True:
                try:
                    r, _, _ = select.select([master_fd], [], [], 0.5)
                    if r:
                        chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                        if chunk:
                            output += chunk
                            clean = _strip_ansi(chunk)
                            if clean.strip():
                                append_event(sid, AgentEvent("answer_delta", sid, data=clean, status="running"))
                            append_event(sid, AgentEvent("diagnostic", sid, data="[PTY chunk]"))
                    else:
                        if proc.poll() is not None:
                            break
                    if time.time() - started > 300:
                        proc.kill()
                        append_event(sid, AgentEvent("error", sid, data="Claude Code 超时", status="failed"))
                        break
                except (OSError, ValueError):
                    break
            os.close(master_fd)
            returncode = proc.wait(timeout=5)
            pty_used = True
        except Exception:
            # PTY 失败，回退到 buffered --print
            pty_used = False

        if not pty_used:
            append_event(sid, AgentEvent("diagnostic", sid, data="[PTY fallback → buffered --print]"))
            proc = subprocess.run([claude_bin, "--print", "--add-dir", COMMANDS],
                                   input=prompt, capture_output=True, text=True, timeout=300)
            output = proc.stdout if proc.stdout.strip() else proc.stderr
            for chunk in _chunkify(output):
                append_event(sid, AgentEvent("answer_delta", sid, data=chunk, status="running"))
            returncode = proc.returncode

        streaming_mode = "pty" if pty_used else "buffered"
        append_event(sid, AgentEvent("diagnostic", sid,
                     data=f"[Claude streaming mode: {streaming_mode}]"))
        status = "completed" if returncode == 0 else "failed"
        if returncode != 0:
            append_event(sid, AgentEvent("diagnostic", sid,
                         data=f"Claude Code failed with returncode={returncode}",
                         status="failed"))
        append_event(sid, AgentEvent("done", sid, data="", status=status))
        update_status(sid, status)
    except subprocess.TimeoutExpired:
        append_event(sid, AgentEvent("error", sid, data="Claude Code 超时", status="failed"))
        update_status(sid, "failed")
    except FileNotFoundError:
        append_event(sid, AgentEvent("error", sid,
                     data="Claude Code CLI 未安装。请设置 HERMES_CLAUDE_BIN。",
                     status="failed"))
        update_status(sid, "failed")
    except Exception as e:
        append_event(sid, AgentEvent("error", sid, data=str(e), status="failed"))
        update_status(sid, "failed")


# ─── Helpers ────────────────────────────────────────────────────

import re

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _strip_ansi(text: str) -> str:
    """移除 ANSI 转义序列和控制字符，保留可读文本"""
    # 移除 ANSI ESC 序列
    text = _ANSI_RE.sub('', text)
    # 移除低字节控制字符 (0x00-0x1F) 但保留 \n \t \r
    text = ''.join(c for c in text if ord(c) >= 0x20 or c in '\n\r\t')
    return text


def _split_output(output: str):
    """分离回答正文与诊断信息"""
    answer_lines, diagnostic_lines = [], []
    for line in output.split("\n"):
        if any(kw in line for kw in ["✅", "📁", "Version", "Status", "pending", "===", "⚠️"]):
            diagnostic_lines.append(line)
        else:
            answer_lines.append(line)
    return "\n".join(answer_lines), diagnostic_lines


def _chunkify(text: str, size: int = 500):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def cancel_session(sid: str):
    update_status(sid, "cancelled")
    append_event(sid, AgentEvent("done", sid, data="", status="cancelled"))
