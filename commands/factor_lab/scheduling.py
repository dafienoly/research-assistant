"""Declarative, resumable scheduling for Hermes write pipelines."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    command: tuple[str, ...]
    depends_on: tuple[str, ...]
    owned_datasets: tuple[str, ...]
    writer_id: str
    timeout_seconds: int
    retry_attempts: int
    backoff_seconds: tuple[int, ...]
    environment: tuple[tuple[str, str], ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScheduledJob":
        return cls(
            job_id=str(payload["job_id"]),
            command=tuple(str(item) for item in payload["command"]),
            depends_on=tuple(str(item) for item in payload.get("depends_on", [])),
            owned_datasets=tuple(str(item) for item in payload.get("owned_datasets", [])),
            writer_id=str(payload.get("writer_id") or payload["job_id"]),
            timeout_seconds=int(payload.get("timeout_seconds", 1800)),
            retry_attempts=int(payload.get("retry_attempts", 1)),
            backoff_seconds=tuple(int(item) for item in payload.get("backoff_seconds", [])),
            environment=tuple(
                sorted((str(key), str(value)) for key, value in payload.get("environment", {}).items())
            ),
        )

    def rendered_command(self, root: Path, python: str) -> list[str]:
        values = {"root": str(root), "python": python}
        return [item.format_map(values) for item in self.command]

    def rendered_environment(self, root: Path, python: str) -> dict[str, str]:
        values = {"root": str(root), "python": python}
        return {key: value.format_map(values) for key, value in self.environment}

    def fingerprint(self) -> str:
        payload = {
            "command": self.command,
            "depends_on": self.depends_on,
            "owned_datasets": self.owned_datasets,
            "writer_id": self.writer_id,
            "timeout_seconds": self.timeout_seconds,
            "retry_attempts": self.retry_attempts,
            "backoff_seconds": self.backoff_seconds,
            "environment": self.environment,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ScheduleRegistry:
    def __init__(self, jobs: dict[str, ScheduledJob], dags: dict[str, tuple[str, ...]]):
        self.jobs = jobs
        self.dags = dags
        self.validate()

    @classmethod
    def load(cls, path: Path) -> "ScheduleRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported schedule registry schema_version")
        parsed = [ScheduledJob.from_dict(item) for item in payload.get("jobs", [])]
        jobs = {item.job_id: item for item in parsed}
        if len(jobs) != len(parsed):
            raise ValueError("duplicate job_id in schedule registry")
        dags = {str(key): tuple(str(item) for item in value) for key, value in payload.get("dags", {}).items()}
        return cls(jobs, dags)

    def validate(self) -> None:
        if not self.jobs or not self.dags:
            raise ValueError("schedule registry must contain jobs and dags")
        dataset_writers: dict[str, str] = {}
        for job in self.jobs.values():
            if not job.command or not job.job_id:
                raise ValueError("scheduled jobs require job_id and command")
            if job.timeout_seconds <= 0 or job.retry_attempts <= 0:
                raise ValueError(f"invalid timeout/retry policy for {job.job_id}")
            if any(delay < 0 for delay in job.backoff_seconds):
                raise ValueError(f"invalid retry backoff for {job.job_id}")
            for dependency in job.depends_on:
                if dependency not in self.jobs:
                    raise ValueError(f"unknown dependency {dependency} for {job.job_id}")
            for dataset in job.owned_datasets:
                existing = dataset_writers.setdefault(dataset, job.writer_id)
                if existing != job.writer_id:
                    raise ValueError(f"dataset {dataset} has multiple writers: {existing}, {job.writer_id}")
        for dag_id, ordered_jobs in self.dags.items():
            if not ordered_jobs:
                raise ValueError(f"DAG {dag_id} is empty")
            if len(set(ordered_jobs)) != len(ordered_jobs):
                raise ValueError(f"DAG {dag_id} contains duplicate jobs")
            positions = {job_id: index for index, job_id in enumerate(ordered_jobs)}
            for job_id in ordered_jobs:
                if job_id not in self.jobs:
                    raise ValueError(f"unknown job {job_id} in DAG {dag_id}")
                for dependency in self.jobs[job_id].depends_on:
                    if dependency not in positions:
                        raise ValueError(f"dependency {dependency} is missing from DAG {dag_id}")
                    if positions[dependency] >= positions[job_id]:
                        raise ValueError(f"dependency {dependency} must precede {job_id} in DAG {dag_id}")


CommandRunner = Callable[[list[str], Path, dict[str, str], int], int]


def _run_command(command: list[str], root: Path, environment: dict[str, str], timeout: int) -> int:
    completed = subprocess.run(
        command,
        cwd=root,
        env={**os.environ, **environment},
        timeout=timeout,
        check=False,
    )
    return int(completed.returncode)


class ScheduledDagRunner:
    def __init__(
        self,
        root: Path,
        registry: ScheduleRegistry,
        state_root: Path | None = None,
        command_runner: CommandRunner = _run_command,
        sleeper: Callable[[float], None] = time.sleep,
        python: str | None = None,
    ):
        self.root = root.resolve()
        self.registry = registry
        self.state_root = (state_root or Path.home() / ".hermes" / "scheduler").resolve()
        self.command_runner = command_runner
        self.sleeper = sleeper
        self.python = python or os.environ.get("HERMES_SCHEDULER_PYTHON") or os.sys.executable

    def describe(self, dag_id: str, trading_date: str) -> dict[str, Any]:
        jobs = self._ordered_jobs(dag_id)
        return {
            "dag_id": dag_id,
            "trading_date": trading_date,
            "jobs": [
                {
                    "job_id": job.job_id,
                    "command": job.rendered_command(self.root, self.python),
                    "depends_on": list(job.depends_on),
                    "owned_datasets": list(job.owned_datasets),
                    "timeout_seconds": job.timeout_seconds,
                    "retry_attempts": job.retry_attempts,
                    "idempotency_key": self._idempotency_key(dag_id, trading_date, job),
                }
                for job in jobs
            ],
        }

    def run(self, dag_id: str, trading_date: str | None = None) -> dict[str, Any]:
        day = trading_date or datetime.now().astimezone().date().isoformat()
        jobs = self._ordered_jobs(dag_id)
        with self._exclusive_lock(self.state_root / "locks" / f"{dag_id}.lock"):
            state_path = self.state_root / "runs" / dag_id / f"{day}.json"
            state = self._load_state(state_path, dag_id, day)
            for job in jobs:
                self._run_job(dag_id, day, job, state, state_path)
            state["finished_at"] = datetime.now().astimezone().isoformat()
            statuses = {item.get("status") for item in state["jobs"].values()}
            state["status"] = "SUCCESS" if statuses <= {"SUCCESS", "SKIPPED"} else "FAILED"
            self._atomic_json(state_path, state)
            return state

    def _run_job(
        self,
        dag_id: str,
        day: str,
        job: ScheduledJob,
        state: dict[str, Any],
        state_path: Path,
    ) -> None:
        expected_key = self._idempotency_key(dag_id, day, job)
        previous = state["jobs"].get(job.job_id, {})
        if previous.get("status") in {"SUCCESS", "SKIPPED"} and previous.get("idempotency_key") == expected_key:
            previous["status"] = "SKIPPED"
            previous["skip_reason"] = "checkpoint_success"
            return
        missing = [
            dependency
            for dependency in job.depends_on
            if state["jobs"].get(dependency, {}).get("status") not in {"SUCCESS", "SKIPPED"}
        ]
        if missing:
            state["jobs"][job.job_id] = {
                "status": "BLOCKED",
                "blocked_by": missing,
                "idempotency_key": expected_key,
                "updated_at": datetime.now().astimezone().isoformat(),
            }
            self._atomic_json(state_path, state)
            return

        command = job.rendered_command(self.root, self.python)
        environment = job.rendered_environment(self.root, self.python)
        record: dict[str, Any] = {
            "status": "RUNNING",
            "idempotency_key": expected_key,
            "command": command,
            "owned_datasets": list(job.owned_datasets),
            "attempts": [],
            "started_at": datetime.now().astimezone().isoformat(),
        }
        state["jobs"][job.job_id] = record
        self._atomic_json(state_path, state)
        for attempt in range(1, job.retry_attempts + 1):
            started = datetime.now().astimezone().isoformat()
            try:
                with self._dataset_locks(job.owned_datasets):
                    exit_code = self.command_runner(command, self.root, environment, job.timeout_seconds)
                error = None if exit_code == 0 else f"exit_code={exit_code}"
            except TimeoutError as exc:
                exit_code, error = 75, str(exc)
            except subprocess.TimeoutExpired as exc:
                exit_code, error = 124, f"timeout after {exc.timeout}s"
            except OSError as exc:
                exit_code, error = 127, str(exc)
            record["attempts"].append(
                {
                    "attempt": attempt,
                    "started_at": started,
                    "finished_at": datetime.now().astimezone().isoformat(),
                    "exit_code": exit_code,
                    "error": error,
                }
            )
            if exit_code == 0:
                record["status"] = "SUCCESS"
                record["finished_at"] = datetime.now().astimezone().isoformat()
                self._atomic_json(state_path, state)
                return
            record["status"] = "RETRYING" if attempt < job.retry_attempts else "FAILED"
            record["finished_at"] = datetime.now().astimezone().isoformat()
            self._atomic_json(state_path, state)
            if attempt < job.retry_attempts:
                delay_index = min(attempt - 1, len(job.backoff_seconds) - 1)
                delay = job.backoff_seconds[delay_index] if job.backoff_seconds else 0
                if delay:
                    self.sleeper(delay)

    def _ordered_jobs(self, dag_id: str) -> list[ScheduledJob]:
        try:
            return [self.registry.jobs[job_id] for job_id in self.registry.dags[dag_id]]
        except KeyError as exc:
            raise ValueError(f"unknown DAG: {dag_id}") from exc

    def _load_state(self, path: Path, dag_id: str, day: str) -> dict[str, Any]:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("dag_id") == dag_id and payload.get("trading_date") == day:
                    payload.setdefault("jobs", {})
                    return payload
            except (OSError, json.JSONDecodeError):
                pass
            recovery = path.with_suffix(f".corrupt-{datetime.now().astimezone():%Y%m%dT%H%M%S%z}.json")
            path.replace(recovery)
        return {
            "schema_version": 1,
            "dag_id": dag_id,
            "trading_date": day,
            "status": "RUNNING",
            "started_at": datetime.now().astimezone().isoformat(),
            "jobs": {},
        }

    def _idempotency_key(self, dag_id: str, day: str, job: ScheduledJob) -> str:
        value = f"{dag_id}:{day}:{job.job_id}:{job.fingerprint()}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @contextmanager
    def _dataset_locks(self, datasets: tuple[str, ...]) -> Iterator[None]:
        handles = []
        try:
            for dataset in sorted(datasets):
                digest = hashlib.sha256(dataset.encode("utf-8")).hexdigest()[:20]
                lock_path = self.state_root / "locks" / "datasets" / f"{digest}.lock"
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                handle = lock_path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    handle.close()
                    raise TimeoutError(f"dataset writer lock busy: {dataset}") from exc
                handles.append(handle)
            yield
        finally:
            for handle in reversed(handles):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    @contextmanager
    def _exclusive_lock(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TimeoutError(f"scheduled DAG already running: {path.stem}") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
