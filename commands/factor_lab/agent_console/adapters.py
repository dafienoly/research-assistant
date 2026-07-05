"""Agent Console Adapters — Hermes / Claude 引擎"""
import subprocess, json, os, threading, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.agent_console.schemas import AgentEvent
from factor_lab.agent_console.sessions import append_event, update_status, SESSIONS_DIR

CST = timezone(timedelta(hours=8))
VENV = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
CLI = "/home/ly/.hermes/research-assistant/commands/hermes_cli.py"
COMMANDS = "/home/ly/.hermes/research-assistant/commands"


def start_session(sid: str, agent: str, prompt: str):
    """后台启动引擎"""
    update_status(sid, "running")
    if agent == "hermes":
        _run_hermes(sid, prompt)
    elif agent == "claude":
        _run_claude(sid, prompt)
    else:
        append_event(sid, AgentEvent("error", sid, data=f"Unknown agent: {agent}", status="failed"))
        update_status(sid, "failed")


def _run_hermes(sid: str, prompt: str):
    """Hermes Agent 适配器"""
    try:
        # 先发送回答框架
        append_event(sid, AgentEvent("answer_delta", sid, data=f"## 任务\n\n{prompt}\n\n## 分析\n\n", status="running"))
        proc = subprocess.run([VENV, CLI, "leader:dispatch", "--dry-run"],
                               capture_output=True, text=True, timeout=120,
                               cwd=COMMANDS)
        output = proc.stdout + proc.stderr
        # 尝试分离回答与诊断
        answer_lines = []
        diagnostic_lines = []
        for line in output.split("\n"):
            if any(kw in line for kw in ["✅", "📁", "Version", "Status", "pending"]):
                diagnostic_lines.append(line)
            else:
                answer_lines.append(line)
        # 发送 answer delta
        if answer_lines:
            for chunk in _chunkify("\n".join(answer_lines)):
                append_event(sid, AgentEvent("answer_delta", sid, data=chunk, status="running"))
        # 发送 diagnostic
        for line in diagnostic_lines:
            append_event(sid, AgentEvent("diagnostic", sid, data=line, status="running"))
        # 最终状态
        status = "completed" if proc.returncode == 0 else "failed"
        append_event(sid, AgentEvent("done", sid, data="", status=status))
        update_status(sid, status)
    except Exception as e:
        append_event(sid, AgentEvent("error", sid, data=str(e), status="failed"))
        update_status(sid, "failed")


def _run_claude(sid: str, prompt: str):
    """Claude Code 适配器 (--print 模式)"""
    append_event(sid, AgentEvent("answer_delta", sid,
                 data=f"## Claude Code 分析\n\n处理中...\n\n", status="running"))
    claude_bin = os.environ.get("HERMES_CLAUDE_BIN",
                                "/home/ly/.nvm/versions/node/v22.16.0/bin/claude")
    try:
        proc = subprocess.run([claude_bin, "--print", "--add-dir", COMMANDS],
                               input=prompt, capture_output=True, text=True, timeout=300)
        output = proc.stdout
        if not output.strip():
            output = proc.stderr
        # Claude --print 输出整体作为回答
        for chunk in _chunkify(output):
            append_event(sid, AgentEvent("answer_delta", sid, data=chunk, status="running"))
        status = "completed" if proc.returncode == 0 else "failed"
        append_event(sid, AgentEvent("done", sid, data="", status=status))
        update_status(sid, status)
    except subprocess.TimeoutExpired:
        append_event(sid, AgentEvent("error", sid, data="Claude Code 超时", status="failed"))
        update_status(sid, "failed")
    except FileNotFoundError:
        append_event(sid, AgentEvent("error", sid,
                     data="Claude Code CLI 未安装或未找到。请安装 claude 或设置 HERMES_CLAUDE_BIN。",
                     status="failed"))
        update_status(sid, "failed")
    except Exception as e:
        append_event(sid, AgentEvent("error", sid, data=str(e), status="failed"))
        update_status(sid, "failed")


def _chunkify(text: str, size: int = 500):
    """将长文本分块发送"""
    for i in range(0, len(text), size):
        yield text[i:i + size]


def cancel_session(sid: str):
    """取消 session (标记 cancelled)"""
    update_status(sid, "cancelled")
    append_event(sid, AgentEvent("done", sid, data="", status="cancelled"))
