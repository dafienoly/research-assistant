"""Live-readiness API backed by the real fail-closed gate suite."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Request

from factor_lab.api_server.response import api_success
from factor_lab.api_server.services.audit_service import audit_service
from factor_lab.api_server.services.job_service import job_service
from factor_lab.broker.qmt_client import QMTClient
from factor_lab.decision_loop.service import DecisionLoopService
from factor_lab.decision_loop.storage import DecisionLoopStore


router = APIRouter()
STORE = DecisionLoopStore()


def _enforce_execution_readiness(payload: dict) -> dict:
    """Add P0 execution blockers missing from the legacy 13-gate suite."""
    status = DecisionLoopService(STORE).status()
    qmt_response = QMTClient(timeout=3).health()
    qmt_data = qmt_response.get("data") if qmt_response.get("status") == "ok" else None
    certification = STORE.read_json("certification/latest.json", default={}) or {}
    checks = [
        (
            "QMTAccountGate",
            bool(isinstance(qmt_data, dict) and qmt_data.get("xttrader_connected")),
            (qmt_data or {}).get("trader_error") if isinstance(qmt_data, dict) else qmt_response.get("error"),
        ),
        (
            "ConfirmedPositionsGate",
            bool((status.get("current_position_snapshot") or {}).get("confirmed")),
            "confirmed position snapshot missing",
        ),
        (
            "DailyAuthorizationGate",
            (status.get("daily_authorization") or {}).get("status") == "active",
            "daily authorization inactive",
        ),
        (
            "ExecutionCertificationGate",
            certification.get("live_activation_allowed") is True,
            "Paper/Shadow/small-whitelist certification incomplete",
        ),
    ]
    existing_names = {item.get("gate_name") for item in payload.get("gates", [])}
    blockers = payload.setdefault("blockers", [])
    for gate_name, passed, reason in checks:
        gate = {
            "gate_name": gate_name,
            "passed": passed,
            "severity": "blocker",
            "message": "ready" if passed else str(reason or "not ready"),
            "evidence": "decision_loop_and_qmt_bridge",
            "fix_suggestion": "完成对应 P0 真实环境验收" if not passed else "",
        }
        if gate_name not in existing_names:
            payload.setdefault("gates", []).append(gate)
        if not passed and not any(item.get("gate_name") == gate_name for item in blockers):
            blockers.append({key: gate[key] for key in ("gate_name", "message", "evidence", "fix_suggestion")})
    if blockers:
        payload["overall"] = "NOT_READY"
    payload["live_activation_allowed"] = payload.get("overall") == "READY" and not blockers
    return payload


@router.get("/live-readiness/latest")
async def get_latest_live_readiness(request: Request):
    """Return the most recent persisted real gate report, or explicit NOT_RUN."""
    report = STORE.read_json(
        "readiness/latest.json",
        default={
            "overall": "NOT_RUN",
            "scanned_at": None,
            "gates": [],
            "blockers": [{"gate_name": "ReadinessNotRun", "message": "尚未运行真实实盘门禁"}],
            "warnings": [],
            "live_activation_allowed": False,
        },
    )
    return api_success(data=report, request=request)


async def _execute_real_readiness(run_id: str, strict: bool) -> None:
    from live_readiness import run_live_readiness_check

    try:
        report = await asyncio.to_thread(run_live_readiness_check, strict)
        payload = _enforce_execution_readiness(report.to_dict())
        payload["persisted_at"] = datetime.now().astimezone().isoformat()
        STORE.write_json("readiness/latest.json", payload)
        STORE.append_unique_jsonl(
            "readiness/history.jsonl",
            payload,
            f"readiness:{payload.get('run_id') or payload['persisted_at']}",
        )
        job_service.set_result(run_id, payload)
        job_service.update_status(
            run_id,
            "completed",
            "真实实盘门禁检查完成：" + str(payload["overall"]),
        )
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        job_service.set_error(run_id, f"{type(exc).__name__}: {exc}")


@router.post("/live-readiness/run")
async def run_live_readiness(request: Request, body: dict):
    """Run the real 13-gate readiness suite asynchronously."""
    strict = bool(body.get("strict", True))
    job = job_service.create(
        name="live_readiness_check",
        job_type="live_readiness",
        params={"strict": strict, "source": "real_gate_suite"},
    )
    job_service.update_status(job.run_id, "running", "正在执行真实实盘就绪门禁...")
    asyncio.create_task(_execute_real_readiness(job.run_id, strict))
    audit_service.record(
        event_type="api_call",
        resource="/api/live-readiness/run",
        action="execute_real_gates",
        detail={"run_id": job.run_id, "strict": strict, "fake_result_generated": False},
        run_id=job.run_id,
    )
    return api_success(data={"job": job.to_dict()}, status_code=202, request=request)
