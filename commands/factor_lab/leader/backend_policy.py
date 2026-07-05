"""Backend Policy — 策略后端选择"""
import os

BACKENDS = {
    "dry-run": {"supports_code_change": False, "supports_docs": True, "supports_test": False, "supports_report": True},
    "claude": {"supports_code_change": True, "supports_docs": True, "supports_test": True, "supports_report": True},
    "command": {"supports_code_change": True, "supports_docs": True, "supports_test": True, "supports_report": True},
    "codex": {"supports_code_change": True, "supports_docs": True, "supports_test": True, "supports_report": True},
}

def need_code_change(task_type):
    """判断任务是否需要真实 coding backend"""
    return task_type in ("code_change", "development", "bugfix", "refactor", "test_implementation")

def available_backend():
    """检测可用后端"""
    import subprocess
    backends = []
    # claude
    if subprocess.run(["which", "claude"], capture_output=True).returncode == 0:
        backends.append("claude")
    # codex - skip unless explicitly set
    env_backend = os.environ.get("HERMES_AGENT_COMMAND", "")
    if env_backend:
        backends.append("command")
    backends.append("dry-run")  # always available
    return backends

def select_backend(task_type):
    """选择合适后端"""
    avail = available_backend()
    if need_code_change(task_type):
        for b in ["claude", "command", "codex"]:
            if b in avail:
                return b
        return None  # blocked
    return "dry-run"

def policy_status():
    avail = available_backend()
    return {
        "available_backends": avail,
        "coding_backend_configured": any(b in avail for b in ["claude", "command", "codex"]),
        "default_for_code_change": select_backend("code_change"),
        "default_for_docs": "dry-run",
    }
