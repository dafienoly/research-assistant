"""任务管理服务 — 内存存储的任务状态管理。"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


class Job:
    """单个任务对象。"""

    def __init__(
        self,
        name: str,
        job_type: str,
        params: Optional[dict] = None,
        run_id: Optional[str] = None,
    ):
        self.run_id = run_id or f"job_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.name = name
        self.job_type = job_type
        self.params = params or {}
        self.status = "pending"  # pending / running / completed / failed / cancelled
        self.progress: float = 0.0
        self.message: str = ""
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now(CST).isoformat()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.log: list[str] = []

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
            "name": self.name,
            "job_type": self.job_type,
            "params": self.params,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "log_length": len(self.log),
        }

    def append_log(self, entry: str):
        self.log.append(f"[{datetime.now(CST).isoformat()}] {entry}")


class JobService:
    """内存任务管理，提供 CRUD + 状态跟踪。"""

    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def create(self, name: str, job_type: str, params: Optional[dict] = None) -> Job:
        job = Job(name=name, job_type=job_type, params=params)
        self._jobs[job.run_id] = job
        return job

    def get(self, run_id: str) -> Optional[Job]:
        return self._jobs.get(run_id)

    def list(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[Job]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[offset : offset + limit]

    def count(self, status: Optional[str] = None) -> int:
        if status:
            return sum(1 for j in self._jobs.values() if j.status == status)
        return len(self._jobs)

    def update_status(self, run_id: str, status: str, message: str = "") -> Optional[Job]:
        job = self._jobs.get(run_id)
        if not job:
            return None
        job.status = status
        if message:
            job.message = message
            job.append_log(message)
        if status == "running" and not job.started_at:
            job.started_at = datetime.now(CST).isoformat()
        if status in ("completed", "failed", "cancelled"):
            job.finished_at = datetime.now(CST).isoformat()
            job.progress = 1.0 if status == "completed" else job.progress
        return job

    def update_progress(self, run_id: str, progress: float, message: str = "") -> Optional[Job]:
        job = self._jobs.get(run_id)
        if not job:
            return None
        job.progress = min(max(progress, 0.0), 1.0)
        if message:
            job.message = message
            job.append_log(message)
        return job

    def set_result(self, run_id: str, result: dict) -> Optional[Job]:
        job = self._jobs.get(run_id)
        if not job:
            return None
        job.result = result
        return job

    def set_error(self, run_id: str, error: str) -> Optional[Job]:
        job = self._jobs.get(run_id)
        if not job:
            return None
        job.error = error
        job.status = "failed"
        job.finished_at = datetime.now(CST).isoformat()
        job.append_log(f"ERROR: {error}")
        return job

    def delete(self, run_id: str) -> bool:
        if run_id in self._jobs:
            del self._jobs[run_id]
            return True
        return False

    def append_log(self, run_id: str, entry: str) -> Optional[Job]:
        job = self._jobs.get(run_id)
        if not job:
            return None
        job.append_log(entry)
        return job


# 全局单例
job_service = JobService()
