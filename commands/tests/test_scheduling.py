from __future__ import annotations

import json
from pathlib import Path

import pytest

from factor_lab.scheduling import ScheduleRegistry, ScheduledDagRunner, ScheduledJob


def job(job_id: str, *, depends_on: tuple[str, ...] = (), dataset: str | None = None, attempts: int = 1) -> ScheduledJob:
    return ScheduledJob(
        job_id=job_id,
        command=("run", job_id),
        depends_on=depends_on,
        owned_datasets=(dataset,) if dataset else (),
        writer_id=job_id,
        timeout_seconds=10,
        retry_attempts=attempts,
        backoff_seconds=(1,),
        environment=(),
    )


def test_registry_rejects_multiple_dataset_writers() -> None:
    with pytest.raises(ValueError, match="multiple writers"):
        ScheduleRegistry({"a": job("a", dataset="daily"), "b": job("b", dataset="daily")}, {"dag": ("a", "b")})


def test_registry_rejects_dependency_after_consumer() -> None:
    jobs = {"source": job("source"), "consumer": job("consumer", depends_on=("source",))}
    with pytest.raises(ValueError, match="must precede"):
        ScheduleRegistry(jobs, {"dag": ("consumer", "source")})


def test_runner_retries_resumes_and_keeps_independent_jobs_moving(tmp_path: Path) -> None:
    jobs = {
        "source": job("source", dataset="daily", attempts=2),
        "consumer": job("consumer", depends_on=("source",)),
        "backup": job("backup", dataset="backup"),
    }
    registry = ScheduleRegistry(jobs, {"dag": ("source", "consumer", "backup")})
    calls: list[str] = []
    outcomes = {"source": [1, 0], "consumer": [9], "backup": [0]}

    def execute(command: list[str], _root: Path, _env: dict[str, str], _timeout: int) -> int:
        job_id = command[-1]
        calls.append(job_id)
        return outcomes[job_id].pop(0)

    delays: list[float] = []
    runner = ScheduledDagRunner(tmp_path, registry, tmp_path / "state", execute, delays.append, python="python")
    first = runner.run("dag", "2026-07-11")

    assert first["status"] == "FAILED"
    assert first["jobs"]["source"]["status"] == "SUCCESS"
    assert first["jobs"]["consumer"]["status"] == "FAILED"
    assert first["jobs"]["backup"]["status"] == "SUCCESS"
    assert calls == ["source", "source", "consumer", "backup"]
    assert delays == [1]

    outcomes["consumer"] = [0]
    second = runner.run("dag", "2026-07-11")
    assert second["status"] == "SUCCESS"
    assert second["jobs"]["source"]["status"] == "SKIPPED"
    assert second["jobs"]["consumer"]["status"] == "SUCCESS"
    assert second["jobs"]["backup"]["status"] == "SKIPPED"
    assert calls[-1] == "consumer"


def test_runner_blocks_only_dependent_jobs(tmp_path: Path) -> None:
    jobs = {
        "source": job("source"),
        "consumer": job("consumer", depends_on=("source",)),
        "status": job("status"),
    }
    registry = ScheduleRegistry(jobs, {"dag": ("source", "consumer", "status")})

    def execute(command: list[str], _root: Path, _env: dict[str, str], _timeout: int) -> int:
        return 2 if command[-1] == "source" else 0

    result = ScheduledDagRunner(tmp_path, registry, tmp_path / "state", execute).run("dag", "2026-07-11")
    assert result["jobs"]["consumer"]["status"] == "BLOCKED"
    assert result["jobs"]["consumer"]["blocked_by"] == ["source"]
    assert result["jobs"]["status"]["status"] == "SUCCESS"


def test_corrupt_checkpoint_is_preserved_before_recovery(tmp_path: Path) -> None:
    registry = ScheduleRegistry({"safe": job("safe")}, {"dag": ("safe",)})
    state_root = tmp_path / "state"
    state_file = state_root / "runs/dag/2026-07-11.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("not-json", encoding="utf-8")
    runner = ScheduledDagRunner(tmp_path, registry, state_root, lambda *_: 0)

    result = runner.run("dag", "2026-07-11")

    assert result["status"] == "SUCCESS"
    assert json.loads(state_file.read_text(encoding="utf-8"))["status"] == "SUCCESS"
    recovered = list(state_file.parent.glob("2026-07-11.corrupt-*.json"))
    assert len(recovered) == 1
    assert recovered[0].read_text(encoding="utf-8") == "not-json"


def test_production_registry_is_valid_and_dry_run_is_side_effect_free(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    registry = ScheduleRegistry.load(root / "commands/config/scheduled_jobs.json")
    runner = ScheduledDagRunner(root, registry, tmp_path / "state", lambda *_: 0, python="python3")

    description = runner.describe("postmarket", "2026-07-11")

    assert description["jobs"][0]["job_id"] == "datahub_daily"
    assert description["jobs"][-1]["job_id"] == "data_backup"
    assert not (tmp_path / "state").exists()


def test_crontab_routes_write_pipelines_through_scheduler() -> None:
    root = Path(__file__).resolve().parents[2]
    crontab = (root / "commands/scripts/crontab/hermes-crontab").read_text(encoding="utf-8")
    legacy = (root / "commands/scripts/closing_pipeline.sh").read_text(encoding="utf-8")

    assert "run_scheduled_dag.py postmarket" in crontab
    assert "run_scheduled_dag.py weekly_datahub" in crontab
    assert "datahub_cron.sh daily-incremental" not in crontab
    assert "hermes_cli.py" not in legacy
    assert "run_scheduled_dag.py" in legacy
