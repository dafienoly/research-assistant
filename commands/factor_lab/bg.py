"""Hermes 持久化后台任务管理器

替代 terminal(background=true) 的不足:
  - 进程与会话解耦, 会话关闭后不丢失
  - 支持 list/status/kill/log 管理
  - 所有数据存在 ~/.hermes/background-jobs/ 内

用法:
    from factor_lab.bg import run_bg, list_jobs, job_status, job_log, kill_job

    # 启动
    job_id = run_bg("python long_backtest.py", name="ret5-walkforward")

    # 管理
    jobs = list_jobs()
    status = job_status(job_id)
    log = job_log(job_id, tail=50)
    kill_job(job_id)
"""
import os, sys, json, signal, subprocess, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))
BG_HOME = Path.home() / ".hermes" / "background-jobs"


def _ensure_dirs():
    BG_HOME.mkdir(parents=True, exist_ok=True)


def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _job_path(job_id: str) -> Path:
    return BG_HOME / job_id


def run_bg(
    command: str,
    name: str = "",
    workdir: Optional[str] = None,
    timeout_minutes: int = 0,
) -> str:
    """启动持久化后台任务

    参数:
        command: shell 命令
        name: 人类可读名称
        workdir: 工作目录 (默认当前)
        timeout_minutes: 超时自动终止 (0=不限)

    返回:
        job_id: 任务 ID, 用于后续管理
    """
    _ensure_dirs()

    job_id = f"bg_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    job_dir = _job_path(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"

    # 写入任务元数据
    meta = {
        "job_id": job_id,
        "name": name or command[:60],
        "command": command,
        "workdir": workdir or os.getcwd(),
        "started_at": _now_str(),
        "timeout_minutes": timeout_minutes,
        "pid": None,
        "exit_code": None,
        "status": "running",
    }
    with open(job_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # 用 nohup 启动, 与会话解耦
    workdir_cmd = f"cd {workdir} && " if workdir else ""
    timeout_cmd = f"timeout {timeout_minutes}m " if timeout_minutes > 0 else ""

    shell_cmd = (
        f"({workdir_cmd}{timeout_cmd}{command}) "
        f"> {stdout_path} 2> {stderr_path}"
    )

    proc = subprocess.Popen(
        ["nohup", "bash", "-c", shell_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setpgrp,  # 独立进程组, 与会话解耦
    )

    # 更新 PID
    meta["pid"] = proc.pid
    with open(job_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # 后台检查线程更新状态
    _spawn_watcher(job_id, proc.pid)

    return job_id


def _spawn_watcher(job_id: str, pid: int):
    """生成监控子进程, 等待任务结束后更新 meta.json"""
    import subprocess
    job_dir = _job_path(job_id)
    watcher_code = f"""
import os, json, time, sys
from datetime import datetime, timezone, timedelta
job_id = {json.dumps(job_id)}
pid = {pid}
job_dir = {json.dumps(str(job_dir))}
_cst = timezone(timedelta(hours=8))

def _now():
    return datetime.now(_cst).strftime("%Y-%m-%d %H:%M:%S")

# 轮询检测进程是否存在 (不用 waitpid, 因为不是直接子进程)
max_wait = 3600  # 最多等 1 小时
for _ in range(max_wait):
    try:
        os.kill(pid, 0)  # 发空信号测试进程是否存在
        time.sleep(2)
    except ProcessLookupError:
        exit_code = 0
        break
    except PermissionError:
        time.sleep(2)
        continue
else:
    exit_code = -99  # 超时

meta_path = os.path.join(job_dir, "meta.json")
if os.path.exists(meta_path):
    with open(meta_path) as f:
        meta = json.load(f)
    meta["exit_code"] = exit_code
    meta["status"] = "completed" if exit_code == 0 else f"failed(code={{exit_code}})"
    meta["finished_at"] = _now()
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
"""
    subprocess.Popen(
        [sys.executable, "-c", watcher_code],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setpgrp,
    )


def list_jobs(limit: int = 20) -> list:
    """列出所有后台任务"""
    _ensure_dirs()
    jobs = []
    for d in sorted(BG_HOME.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            jobs.append(meta)
    return jobs[:limit]


def job_status(job_id: str) -> dict:
    """查询单个任务状态"""
    meta_path = _job_path(job_id) / "meta.json"
    if not meta_path.exists():
        return {"error": f"任务 {job_id} 不存在"}
    with open(meta_path) as f:
        return json.load(f)


def job_log(job_id: str, tail: int = 100, stream: str = "stdout") -> str:
    """查看任务日志"""
    log_path = _job_path(job_id) / f"{stream}.log"
    if not log_path.exists():
        return f"[{stream}.log 不存在]"
    with open(log_path) as f:
        lines = f.readlines()
    tail_lines = lines[-tail:]
    return "".join(tail_lines)


def kill_job(job_id: str, force: bool = False) -> str:
    """终止任务"""
    meta = job_status(job_id)
    if "error" in meta:
        return meta["error"]
    pid = meta.get("pid")
    if not pid:
        return "PID 为空"
    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        # 更新 meta
        meta_path = _job_path(job_id) / "meta.json"
        meta["status"] = f"killed({sig})"
        meta["finished_at"] = _now_str()
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        return f"已发送 {sig.name} 到 PID {pid}"
    except ProcessLookupError:
        return f"进程 {pid} 已不存在"
    except Exception as e:
        return f"终止失败: {e}"


def clean_old_jobs(hours: int = 168):
    """清理超过指定小时数的已完成任务 (默认 7 天)"""
    import shutil
    now = datetime.now(CST).timestamp()
    count = 0
    for d in BG_HOME.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        with open(meta_path) as f:
            meta = json.load(f)
        if meta.get("status", "").startswith("completed") or meta.get("status", "").startswith("failed") or meta.get("status", "").startswith("killed"):
            started = meta.get("started_at", "")
            try:
                t = datetime.strptime(started, "%Y-%m-%d %H:%M:%S").timestamp()
                if (now - t) > hours * 3600:
                    shutil.rmtree(d)
                    count += 1
            except:
                pass
    return count
