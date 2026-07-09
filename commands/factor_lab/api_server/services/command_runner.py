"""命令执行服务 — 在子进程中执行 CLI 命令，捕获 stdout/stderr。"""

import asyncio
import shlex
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


class CommandResult:
    """命令执行结果。"""

    def __init__(
        self,
        run_id: str,
        command: str,
        returncode: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
    ):
        self.run_id = run_id
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.started_at = started_at or datetime.now(CST).isoformat()
        self.finished_at = finished_at
        self._running = returncode is None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.finished_at:
            try:
                start = datetime.fromisoformat(self.started_at)
                end = datetime.fromisoformat(self.finished_at)
                return (end - start).total_seconds()
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "is_running": self._running,
            "duration_seconds": self.duration_seconds,
        }


class CommandRunner:
    """在 asyncio 子进程中安全执行 CLI 命令。"""

    def __init__(self, timeout: int = 3600):
        self.timeout = timeout

    async def run(self, command: str, run_id: str, cwd: Optional[str] = None) -> CommandResult:
        """执行一条 CLI 命令，返回 CommandResult。"""
        started_at = datetime.now(CST).isoformat()
        try:
            parts = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
                finished_at = datetime.now(CST).isoformat()
                return CommandResult(
                    run_id=run_id,
                    command=command,
                    returncode=proc.returncode,
                    stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
                    stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
                    started_at=started_at,
                    finished_at=finished_at,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                finished_at = datetime.now(CST).isoformat()
                return CommandResult(
                    run_id=run_id,
                    command=command,
                    returncode=-1,
                    stdout="",
                    stderr="[TIMEOUT] 命令执行超时",
                    started_at=started_at,
                    finished_at=finished_at,
                )
        except Exception as e:
            finished_at = datetime.now(CST).isoformat()
            return CommandResult(
                run_id=run_id,
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"[ERROR] {str(e)}",
                started_at=started_at,
                finished_at=finished_at,
            )

    async def stream(self, command: str, run_id: str, cwd: Optional[str] = None):
        """异步生成器，逐行产生 stdout/stderr 输出。

        每次 yield: {"type": "stdout"/"stderr", "line": "...", "run_id": "..."}
        结束时 yield: {"type": "done", "returncode": 0, "run_id": "..."}
        """
        try:
            parts = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            async def _read_stream(stream, stream_type: str):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    yield {
                        "type": stream_type,
                        "line": line.decode("utf-8", errors="replace").rstrip("\n"),
                        "run_id": run_id,
                    }

            import asyncio as _asyncio

            async for item in _read_stream(proc.stdout, "stdout"):
                yield item
            async for item in _read_stream(proc.stderr, "stderr"):
                yield item

            await proc.wait()
            yield {"type": "done", "returncode": proc.returncode, "run_id": run_id}
        except Exception as e:
            yield {"type": "error", "message": str(e), "run_id": run_id}
