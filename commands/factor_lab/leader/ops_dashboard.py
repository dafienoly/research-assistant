"""One-click Local Ops — V7.9 本地一键运维

提供本地服务健康检查、一键启停、备份、诊断等运维能力。
所有操作仅限本地，不涉及远程部署。

Services (SERVICE_DEFS): dashboard, mcp, vite.

Usage:
  from factor_lab.leader.ops_dashboard import OpsManager
  ops = OpsManager()
  ops.health()
  ops.start_service("dashboard")
  ops.stop_service("dashboard")
  ops.diagnostics()
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

# ── Paths ──
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # commands/
VENV_PYTHON = None
for candidate in [
    BASE_DIR.parent / ".venv_quant" / "bin" / "python3",
    Path.home() / ".hermes" / "research-assistant" / ".venv_quant" / "bin" / "python3",
    Path("/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"),
]:
    if candidate.exists():
        VENV_PYTHON = str(candidate)
        break
if not VENV_PYTHON:
    VENV_PYTHON = sys.executable

CLI_SCRIPT = str(BASE_DIR / "hermes_cli.py")
LOGS_DIR = Path.home() / ".hermes"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Service definitions ──
SERVICE_DEFS = {
    "dashboard": {
        "name": "API Dashboard",
        "name_zh": "API 仪表盘",
        "port": 8766,
        "pid_file": str(LOGS_DIR / "hermes-dashboard.pid"),
        "log_file": str(LOGS_DIR / "hermes-dashboard.log"),
        "command": [
            VENV_PYTHON, "-c",
            "from factor_lab.api_server.main import serve; serve(host='127.0.0.1', port=8766)",
        ],
        "health_url": "http://127.0.0.1:8766/api/status",
        "depends_on": [],
        "env": {},
        "required": True,
    },
    "mcp": {
        "name": "MCP Server",
        "name_zh": "MCP 工具服务器",
        "port": 8767,
        "pid_file": str(LOGS_DIR / "hermes-mcp.pid"),
        "log_file": str(LOGS_DIR / "hermes-mcp.log"),
        "command": [
            VENV_PYTHON, CLI_SCRIPT, "research:mcp", "--port", "8767",
        ],
        "health_url": "http://127.0.0.1:8767/health",
        "depends_on": [],
        "env": {},
        "required": False,
    },
    "vite": {
        "name": "Vite Dev Server",
        "name_zh": "Vite 前端开发服务器",
        "port": 5173,
        "pid_file": None,
        "log_file": None,
        "command": None,
        "health_url": None,
        "depends_on": [],
        "env": {},
        "required": False,
    },
}


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _check_port(port: Optional[int]) -> dict:
    """检查端口是否被占用，返回占用详情"""
    if port is None:
        return {"port": None, "in_use": False, "pid": None, "process_name": None}
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                proc = psutil.Process(conn.pid) if conn.pid else None
                return {
                    "port": port,
                    "in_use": True,
                    "pid": conn.pid,
                    "process_name": proc.name() if proc else None,
                }
    except (ImportError, OSError):
        pass
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return {"port": port, "in_use": True, "pid": None, "process_name": "listener"}
    except OSError:
        pass
    return {"port": port, "in_use": False, "pid": None, "process_name": None}


def _check_process_by_pid(pid_file: Optional[str]) -> dict:
    """通过 PID 文件检查进程是否存在"""
    if pid_file is None:
        return {"running": False, "pid": None, "pid_file_exists": False}
    path = Path(pid_file)
    if not path.exists():
        return {"running": False, "pid": None, "pid_file_exists": False}
    try:
        pid = int(path.read_text().strip())
        os.kill(pid, 0)  # 信号 0 = 仅检查存在性
        return {"running": True, "pid": pid, "pid_file_exists": True}
    except (ValueError, OSError, ProcessLookupError):
        return {"running": False, "pid": None, "pid_file_exists": True}


def _check_cron_job() -> dict:
    """检查 crontab 中是否有 Hermes 相关任务"""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            found = "hermes" in result.stdout.lower()
            return {"registered": found, "cron_output": result.stdout[:500]}
        return {"registered": False, "error": result.stderr[:200]}
    except Exception as e:
        return {"registered": False, "error": str(e)}


def _check_disk_usage(path: str = "/home") -> dict:
    """检查磁盘使用率"""
    try:
        usage = shutil.disk_usage(path)
        pct = usage.used / usage.total * 100
        return {
            "path": path,
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "usage_pct": round(pct, 1),
            "status": "critical" if pct > 90 else ("warning" if pct > 75 else "healthy"),
        }
    except Exception as e:
        return {"path": path, "status": "unknown", "error": str(e)}


def _check_memory_usage() -> dict:
    """检查系统内存使用率"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        pct = mem.percent
        return {
            "total_gb": round(mem.total / (1024**3), 1),
            "available_gb": round(mem.available / (1024**3), 1),
            "usage_pct": pct,
            "status": "critical" if pct > 90 else ("warning" if pct > 75 else "healthy"),
        }
    except ImportError:
        return {"status": "unknown", "error": "psutil not available"}


def _check_python_deps() -> list:
    """检查关键 Python 依赖是否可用"""
    deps = [
        ("fastapi", "FastAPI"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
    ]
    results = []
    for mod_name, label in deps:
        try:
            __import__(mod_name)
            results.append({"name": label, "available": True, "error": None})
        except ImportError as e:
            results.append({"name": label, "available": False, "error": str(e)})
    return results


def _get_log_tail(log_file: Optional[str], n_lines: int = 20) -> list:
    """读取日志文件尾部行"""
    if log_file is None:
        return []
    path = Path(log_file)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n_lines:]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════
# OpsManager
# ═══════════════════════════════════════════════════════════════════

class OpsManager:
    """一键运维管理器

    提供本地服务的健康检查、启停控制、备份和诊断等运维能力。
    所有操作仅限本地，不涉及远程部署。

    Usage:
        ops = OpsManager()
        ops.health()           # → dict with all service statuses
        ops.service_status("dashboard")  # → dict with single service status
        ops.start_service("dashboard")   # → dict with result
        ops.stop_service("dashboard")    # → dict with result
        ops.restart_service("dashboard") # → dict with result
        ops.backup()                     # → dict with backup result
        ops.diagnostics()                # → dict with full diagnostic report
    """

    def __init__(self):
        self._service_defs = SERVICE_DEFS.copy()

    # ── Health ──

    def health(self) -> dict:
        """返回所有服务的健康状态概览"""
        services = {}
        required_running = True
        for sid, sdef in self._service_defs.items():
            status = self.service_status(sid)
            services[sid] = status
            if sdef.get("required", False) and not status.get("running", False):
                required_running = False

        port_map = {}
        for sid, sdef in self._service_defs.items():
            if sdef["port"]:
                port_map[sid] = {"port": sdef["port"]}
                port_info = _check_port(sdef["port"])
                port_map[sid].update(port_info)

        return {
            "timestamp": _now_str(),
            "overall": "healthy" if required_running else "degraded",
            "all_running": required_running,
            "n_services": len(services),
            "n_running": sum(1 for s in services.values() if s.get("running", False)),
            "services": services,
            "ports": port_map,
            "venv_python": VENV_PYTHON,
            "base_dir": str(BASE_DIR),
        }

    def service_status(self, service_id: str) -> dict:
        """返回单个服务的详细状态"""
        sdef = self._service_defs.get(service_id)
        if sdef is None:
            return {"error": f"未知服务: {service_id}", "running": False}

        # 端口检查
        port_status = _check_port(sdef["port"]) if sdef["port"] else None

        # PID 检查
        pid_status = _check_process_by_pid(sdef.get("pid_file"))

        # Cron 检查
        cron_status = None
        if sdef.get("cron_check"):
            cron_status = _check_cron_job()

        # 综合判断运行状态
        if pid_status["running"]:
            running = True
            source = "pid"
        elif port_status and port_status["in_use"]:
            running = True
            source = "port"
        elif cron_status and cron_status.get("registered"):
            running = True
            source = "cron"
        else:
            running = False
            source = "none"

        return {
            "id": service_id,
            "name": sdef["name"],
            "name_zh": sdef["name_zh"],
            "port": sdef["port"],
            "required": sdef.get("required", False),
            "running": running,
            "detected_by": source,
            "pid_status": pid_status,
            "port_status": port_status,
            "cron_status": cron_status,
            "log_tail": _get_log_tail(sdef.get("log_file")),
        }

    # ── Service Control ──

    def start_service(self, service_id: str) -> dict:
        """启动一个服务"""
        sdef = self._service_defs.get(service_id)
        if sdef is None:
            return {"success": False, "error": f"未知服务: {service_id}"}

        # 检查是否已经在运行
        status = self.service_status(service_id)
        if status["running"]:
            return {
                "success": True,
                "message": f"{sdef['name_zh']} 已在运行",
                "already_running": True,
            }

        # 检查端口是否被占用
        if sdef["port"]:
            port_info = _check_port(sdef["port"])
            if port_info["in_use"]:
                return {
                    "success": False,
                    "error": f"端口 {sdef['port']} 已被 {port_info.get('process_name', '未知进程')} (PID {port_info['pid']}) 占用",
                    "port_conflict": True,
                }

        # 检查依赖
        for dep_id in sdef.get("depends_on", []):
            dep_status = self.service_status(dep_id)
            if not dep_status["running"]:
                return {
                    "success": False,
                    "error": f"依赖服务 {dep_id} 未运行",
                    "dependency_failed": dep_id,
                }

        # 执行启动命令
        cmd = sdef.get("command")
        if cmd is None:
            return {"success": False, "error": f"{sdef['name_zh']} 不支持直接启动"}

        try:
            log_file = sdef.get("log_file")
            pid_file = sdef.get("pid_file")

            # 获取环境变量
            env = os.environ.copy()
            env.update(sdef.get("env", {}))

            # 使用 nohup 启动后台进程
            if log_file:
                with open(log_file, "a") as lf:
                    lf.write(f"\n[{_now_str()}] === Starting {sdef['name']} ===\n")

            process = subprocess.Popen(
                cmd,
                stdout=open(log_file, "a") if log_file else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )

            # 写入 PID 文件
            if pid_file:
                Path(pid_file).write_text(str(process.pid))

            # 等待启动确认
            time.sleep(2)

            # 验证是否启动成功
            post_status = self.service_status(service_id)
            if post_status["running"]:
                return {
                    "success": True,
                    "message": f"{sdef['name_zh']} 已启动 (PID {process.pid})",
                    "pid": process.pid,
                    "already_running": False,
                }
            else:
                return {
                    "success": True,
                    "message": f"{sdef['name_zh']} 启动命令已发出，正在等待就绪 (PID {process.pid})",
                    "pid": process.pid,
                    "may_take_time": True,
                }

        except Exception as e:
            return {"success": False, "error": f"启动失败: {e}"}

    def stop_service(self, service_id: str) -> dict:
        """停止一个服务"""
        sdef = self._service_defs.get(service_id)
        if sdef is None:
            return {"success": False, "error": f"未知服务: {service_id}"}

        status = self.service_status(service_id)
        if not status["running"]:
            return {
                "success": True,
                "message": f"{sdef['name_zh']} 未在运行",
                "already_stopped": True,
            }

        killed = []
        killed_pids: set[int] = set()

        # 方式1: kill 进程 (通过 PID 文件)
        pid_status = status.get("pid_status", {})
        if pid_status and pid_status.get("pid"):
            pid = pid_status["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(f"PID {pid} (SIGTERM)")
                killed_pids.add(pid)
            except (OSError, ProcessLookupError):
                pass

        # 方式2: kill 进程 (通过端口)
        port_status = status.get("port_status", {})
        if port_status and port_status.get("pid") and port_status["pid"] not in killed_pids:
            pid = port_status["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(f"PID {pid} (port {port_status['port']})")
                killed_pids.add(pid)
            except (OSError, ProcessLookupError):
                pass

        return {
            "success": True,
            "message": f"{sdef['name_zh']} 已停止" if killed else f"{sdef['name_zh']} 停止命令已发出",
            "killed_methods": killed,
            "already_stopped": False,
        }

    def restart_service(self, service_id: str) -> dict:
        """重启一个服务 (先停止再启动)"""
        stop_result = self.stop_service(service_id)
        time.sleep(2)
        start_result = self.start_service(service_id)

        return {
            "success": stop_result["success"] and start_result["success"],
            "stop": stop_result,
            "start": start_result,
            "message": f"重启 {service_id}: {'成功' if (stop_result['success'] and start_result['success']) else '部分失败'}",
        }

    # ── Backup ──

    def backup(self) -> dict:
        """备份当前运维配置与服务日志。"""
        results = {}

        # 1. 配置文件备份
        try:
            config_backup_dir = LOGS_DIR / "config_backups"
            config_backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
            config_backup_path = config_backup_dir / f"config_backup_{ts}.json"

            config_data = {
                "backup_time": _now_str(),
                "venv_python": VENV_PYTHON,
                "base_dir": str(BASE_DIR),
                "service_configs": list(self._service_defs.keys()),
            }
            config_backup_path.write_text(
                json.dumps(config_data, indent=2, ensure_ascii=False)
            )
            results["config_backup"] = {
                "success": True,
                "path": str(config_backup_path),
            }
        except Exception as e:
            results["config_backup"] = {"success": False, "error": str(e)}

        # 2. 备份日志轮转
        try:
            log_backup_dir = LOGS_DIR / "log_backups"
            log_backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
            for sid, sdef in self._service_defs.items():
                lf = sdef.get("log_file")
                if lf and Path(lf).exists():
                    backup_name = f"{sid}_log_{ts}.txt"
                    shutil.copy2(lf, str(log_backup_dir / backup_name))
            results["log_backup"] = {"success": True, "dir": str(log_backup_dir)}
        except Exception as e:
            results["log_backup"] = {"success": False, "error": str(e)}

        all_ok = all(r.get("success") for r in results.values())
        return {
            "success": all_ok,
            "timestamp": _now_str(),
            "results": results,
        }

    # ── Diagnostics ──

    def diagnostics(self) -> dict:
        """运行全面诊断，返回详细报告"""
        diag = {
            "timestamp": _now_str(),
            "hostname": socket.gethostname(),
        }

        # 系统信息
        diag["system"] = {}
        try:
            import platform
            diag["system"] = {
                "platform": platform.platform(),
                "python": sys.version,
                "python_executable": sys.executable,
            }
        except Exception as e:
            diag["system"] = {"error": str(e)}

        # 磁盘
        diag["disk"] = _check_disk_usage()

        # 内存
        diag["memory"] = _check_memory_usage()

        # Python 依赖
        diag["python_deps"] = _check_python_deps()

        # 虚拟环境
        diag["venv"] = {
            "path": VENV_PYTHON,
            "exists": Path(VENV_PYTHON).exists() if VENV_PYTHON else False,
        } if VENV_PYTHON else {"error": "no venv found"}

        # 服务状态
        diag["services"] = {}
        for sid in self._service_defs:
            diag["services"][sid] = self.service_status(sid)

        # 端口占用
        diag["ports"] = []
        checked_ports = set()
        for sdef in self._service_defs.values():
            p = sdef.get("port")
            if p and p not in checked_ports:
                checked_ports.add(p)
                diag["ports"].append(_check_port(p))

        # Cron
        diag["cron"] = _check_cron_job()

        # Git 状态
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=10,
                cwd=BASE_DIR,
            )
            changed = result.stdout.strip()
            diag["git"] = {
                "has_changes": bool(changed),
                "changed_files": len(changed.splitlines()) if changed else 0,
            }
        except Exception as e:
            diag["git"] = {"error": str(e)}

        # 工作目录检查
        diag["workspace"] = {
            "base_dir": str(BASE_DIR),
            "cli_exists": Path(CLI_SCRIPT).exists(),
            "scripts_dir_exists": (BASE_DIR / "scripts").exists(),
            "frontend_dist_exists": (BASE_DIR / "frontend" / "dist").exists(),
            "factor_lab_exists": (BASE_DIR / "factor_lab").exists(),
        }

        return diag

    # ── Port Scanning ──

    def port_scan(self) -> list:
        """扫描所有关注端口的状态"""
        results = []
        seen = set()
        for sid, sdef in self._service_defs.items():
            p = sdef.get("port")
            if p and p not in seen:
                seen.add(p)
                info = _check_port(p)
                info["service"] = sid
                info["service_name"] = sdef["name_zh"]
                results.append(info)
        return results


# ═══════════════════════════════════════════════════════════════════
# Module-level helpers (matches singleton pattern used by routes_risk)
# ═══════════════════════════════════════════════════════════════════

_manager_instance: Optional[OpsManager] = None


def get_manager() -> OpsManager:
    """获取全局 OpsManager 单例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = OpsManager()
    return _manager_instance


def reset_manager():
    """重置单例（测试用）"""
    global _manager_instance
    _manager_instance = None
