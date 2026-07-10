"""Stable API surface for the Hermes VNext control console."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from factor_lab.api_server.response import api_success
from factor_lab.vnext.service import VNextService


def _require_vnext_enabled() -> None:
    if os.environ.get("HERMES_VNEXT_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        raise HTTPException(status_code=503, detail="Hermes VNext is disabled by HERMES_VNEXT_ENABLED")


router = APIRouter(prefix="/vnext", tags=["vnext"], dependencies=[Depends(_require_vnext_enabled)])


def _service() -> VNextService:
    return VNextService()


def _component(request: Request, name: str, as_of: str | None):
    return api_success(_service().component(name, as_of), request=request)


@router.get("/status")
async def vnext_status(request: Request, date: str | None = Query(default=None)):
    return _component(request, "status", date)


@router.get("/data-health")
async def vnext_data_health(request: Request, date: str | None = Query(default=None)):
    return _component(request, "data-health", date)


@router.get("/regime")
async def vnext_regime(request: Request, date: str | None = Query(default=None)):
    return _component(request, "regime", date)


@router.get("/policy-put")
async def vnext_policy_put(request: Request, date: str | None = Query(default=None)):
    return _component(request, "policy-put", date)


@router.get("/semi-mainline")
async def vnext_semi_mainline(request: Request, date: str | None = Query(default=None)):
    return _component(request, "semi-mainline", date)


@router.get("/candidates")
async def vnext_candidates(request: Request, date: str | None = Query(default=None)):
    return _component(request, "candidates", date)


@router.get("/portfolio-risk")
async def vnext_portfolio_risk(request: Request, date: str | None = Query(default=None)):
    return _component(request, "portfolio-risk", date)


@router.get("/ml-ranker")
async def vnext_ml_ranker(request: Request, date: str | None = Query(default=None)):
    return _component(request, "ml-ranker", date)


@router.get("/backtests")
async def vnext_backtests(request: Request):
    service = _service()
    latest = service.component("backtests")
    return api_success(
        {
            "status": latest.get("status", "MISSING"),
            "as_of": latest.get("as_of"),
            "confidence": latest.get("confidence", 0.0),
            "evidence": latest.get("evidence", []),
            "missing_evidence": latest.get("missing_evidence", []),
            "payload": {"latest": latest, "runs": service.store.list("backtests")},
        },
        request=request,
    )


@router.get("/backtests/{run_id}")
async def vnext_backtest_detail(run_id: str, request: Request):
    return api_success(_service().store.read("backtests", run_id), request=request)


@router.get("/paper")
async def vnext_paper(request: Request, date: str | None = Query(default=None)):
    return _component(request, "paper", date)


@router.get("/shadow")
async def vnext_shadow(request: Request, date: str | None = Query(default=None)):
    return _component(request, "shadow", date)


@router.get("/approvals")
async def vnext_approvals(request: Request):
    records = _service().approvals.list()
    return api_success({"items": records, "total": len(records)}, request=request)


@router.get("/approvals/{approval_id}")
async def vnext_approval_detail(approval_id: str, request: Request):
    try:
        record = _service().approvals.get(approval_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="approval not found") from exc
    return api_success(record, request=request)


async def _approval_decision(approval_id: str, action: str, request: Request, body: dict[str, Any]):
    try:
        record = _service().approvals.decide(
            approval_id,
            action,
            approver=str(body.get("approver", "ui-user")),
            reason=str(body.get("reason", "")),
            modifications=body.get("modifications"),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="approval not found") from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return api_success(
        {
            "approval": record,
            "execution_triggered": False,
            "message": "approval state updated; no broker action is performed by this API",
        },
        request=request,
    )


@router.post("/approvals/{approval_id}/approve")
async def vnext_approve(approval_id: str, request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _approval_decision(approval_id, "APPROVE", request, body)


@router.post("/approvals/{approval_id}/reject")
async def vnext_reject(approval_id: str, request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _approval_decision(approval_id, "REJECT", request, body)


@router.post("/approvals/{approval_id}/delay")
async def vnext_delay(approval_id: str, request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _approval_decision(approval_id, "DELAY", request, body)


@router.post("/approvals/{approval_id}/modify")
async def vnext_modify(approval_id: str, request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _approval_decision(approval_id, "MODIFY", request, body)


@router.get("/execution-status")
async def vnext_execution_status(request: Request, date: str | None = Query(default=None)):
    return _component(request, "execution-status", date)


@router.get("/antifragile-review")
async def vnext_antifragile(request: Request, date: str | None = Query(default=None)):
    return _component(request, "antifragile-review", date)


@router.get("/reports")
async def vnext_reports(request: Request, date: str | None = Query(default=None)):
    service = _service()
    return api_success(
        {
            "latest": service.component("reports", date),
            "history": service.store.list("reports"),
        },
        request=request,
    )


@router.get("/reports/download")
async def vnext_report_download(date: str = Query(...), format: str = Query(default="md")):
    if format not in {"md", "json", "csv"}:
        raise HTTPException(status_code=400, detail="format must be md, json or csv")
    service = _service()
    path = service.store.report_path(date, format)
    media_type = {"md": "text/markdown", "json": "application/json", "csv": "text/csv"}[format]
    if not path.exists():
        raise HTTPException(status_code=404, detail="report artifact not found")
    return FileResponse(path, filename=path.name, media_type=media_type)
