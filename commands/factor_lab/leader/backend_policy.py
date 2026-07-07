"""Backend Policy — 策略后端选择 (cron 安全版)"""
import os, subprocess, shutil

BACKENDS = {
    "dry-run": {"supports_code_change": False, "supports_docs": True},
    "claude": {"supports_code_change": True, "supports_docs": True},
    "command": {"supports_code_change": True, "supports_docs": True},
    "codex": {"supports_code_change": True, "supports_docs": True},
}


def _resolve_binary(name):
    """解析二进制路径，优先环境变量，再搜索常见路径及 nvm"""
    env_var = {"claude": "HERMES_CLAUDE_BIN"}.get(name, "")
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    # 搜索 PATH
    which = shutil.which(name)
    if which:
        return which
    # 常见路径
    common = {
        "claude": [
            "/usr/local/bin/claude",
            "/home/ly/.local/bin/claude",
            "/home/ly/.npm-global/bin/claude",
            "/snap/bin/claude",
            "/home/ly/.nvm/versions/node/v22.16.0/bin/claude",
        ],
    }
    # 还扫描 ~/.nvm/versions/node/*/bin/claude
    nvm_root = os.path.expanduser("~/.nvm/versions/node")
    if name == "claude" and os.path.isdir(nvm_root):
        for ver_dir in sorted(os.listdir(nvm_root), reverse=True):
            candidate = os.path.join(nvm_root, ver_dir, "bin", "claude")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    for p in common.get(name, []):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def need_code_change(task_type):
    return task_type in ("code_change", "development", "bugfix", "refactor", "test_implementation")


def available_backend():
    backends = []
    env_cmd = os.environ.get("HERMES_AGENT_COMMAND", "")
    if env_cmd:
        backends.append("command")
    if _resolve_binary("claude"):
        backends.append("claude")
    backends.append("dry-run")
    return backends


def select_backend(task_type):
    avail = available_backend()
    if need_code_change(task_type):
        if "claude" in avail:
            return "claude"
        if "command" in avail:
            return "command"
        return None
    return "dry-run"


def policy_status():
    avail = available_backend()
    claude_path = _resolve_binary("claude")
    return {
        "available_backends": avail,
        "coding_backend_configured": any(b in avail for b in ["claude", "command"]),
        "claude_bin_path": claude_path or "not_found",
        "path": os.environ.get("PATH", ""),
        "hermes_coding_backend": os.environ.get("HERMES_CODING_BACKEND", ""),
        "hermes_agent_command": os.environ.get("HERMES_AGENT_COMMAND", ""),
        "cron_safe": bool(avail and avail[0] != "dry-run" if need_code_change("code_change") else True),
        "default_for_code_change": select_backend("code_change"),
    }
