"""Core Pipeline V2.14.2 — 统一 RunContext"""
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

CST = timezone(timedelta(hours=8))


@dataclass
class RunContext:
    """运行上下文"""
    run_id: str
    module: str
    source_run_id: str = ""
    candidate_name: str = ""
    dry_run: bool = True
    confirm: bool = False
    strict: bool = False
    start_date: str = ""
    end_date: str = ""
    last_n: int = 0
    created_at: str = ""


@dataclass
class PipelineStage:
    name: str
    status: str = "pending"  # pending/running/completed/failed/skipped
    result: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


@dataclass
class PipelineResult:
    status: str = "completed"
    stages: list = field(default_factory=list)
    output_dir: str = ""
    summary: dict = field(default_factory=dict)
