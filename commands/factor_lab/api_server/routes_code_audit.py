"""Code audit run API."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from factor_lab.api_server.response import api_success
from factor_lab.audit.coordinator import AuditCoordinator, AuditRequest
from factor_lab.audit.storage import AuditStore

router = APIRouter(prefix="/code-audits", tags=["code-audit"])
ROOT = Path(__file__).resolve().parents[3]


class TriggerAuditBody(BaseModel):
    profile: Literal["fast", "full", "security"] = "fast"
    scope: Literal["working-tree", "staged", "compare", "paths"] = "working-tree"
    base_ref: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")
    paths: list[str] = Field(default_factory=list, max_length=100)
    major_version: str = Field(default="", pattern=r"^$|^\d+\.\d+(?:\.\d+)?(?:[-+].*)?$")


def _local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


@router.get("/runs")
async def list_code_audits(request: Request, limit: int = 50):
    runs = AuditStore().list_runs(limit=max(1, min(limit, 100)))
    return api_success(data={"runs": runs, "total": len(runs)}, request=request)


@router.get("/runs/{run_id}")
async def get_code_audit(run_id: str, request: Request):
    payload = AuditStore().load(run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Code audit run not found")
    return api_success(data=payload, request=request)


@router.post("/trigger")
async def trigger_code_audit(body: TriggerAuditBody, request: Request):
    if not _local_request(request):
        raise HTTPException(status_code=403, detail="Code audit can only be triggered locally")
    if not body.major_version:
        return api_success(
            data={
                "state": "skipped",
                "passed": True,
                "reason": "仅允许在显式大版本发布前执行源码审计",
                "scan_policy": {
                    "source_only": True,
                    "data_scan": False,
                    "temp_scan": False,
                    "pytest": False,
                    "semgrep": False,
                    "gitnexus": False,
                },
            },
            request=request,
        )
    audit_request = AuditRequest(
        repo_root=ROOT,
        profile=body.profile,
        scope=body.scope,
        base_ref=body.base_ref,
        paths=body.paths,
        trigger="api",
        requested_by=request.client.host if request.client else "local",
        major_version=body.major_version,
    )
    try:
        report = await run_in_threadpool(AuditCoordinator().run, audit_request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return api_success(data=report.to_dict(), request=request)
