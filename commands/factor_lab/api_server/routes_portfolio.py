"""Portfolio API backed by persisted VNext optimization evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Request

from factor_lab.api_server.response import api_error, api_success
from factor_lab.api_server.services.audit_service import audit_service
from factor_lab.datahub_access import PROJECT_ROOT
from factor_lab.vnext.snapshot import ASSET_PROXIES


router = APIRouter()
OPTIMIZATION_PATH = PROJECT_ROOT / "artifacts" / "vnext" / "portfolio_optimization.json"


def _latest_optimization(path: Path = OPTIMIZATION_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "OK" or not payload.get("data_snapshot_id") or not payload.get("target_weights_hash"):
        raise ValueError("VNext portfolio optimization artifact is not verified")
    method = payload.get("methods", {}).get("cost_aware")
    if not isinstance(method, dict) or method.get("status") != "OK" or not isinstance(method.get("weights"), dict):
        raise ValueError("VNext cost-aware portfolio output missing")
    role_assets = {role: {"ticker": symbol, "name": name} for role, (symbol, name) in ASSET_PROXIES.items()}
    holdings = []
    for role, weight in method["weights"].items():
        numeric_weight = float(weight)
        if numeric_weight <= 0:
            continue
        asset = role_assets.get(role, {"ticker": role, "name": role})
        holdings.append(
            {
                **asset,
                "role": role,
                "weight": round(numeric_weight * 100, 6),
                "reason": "VNext cost-aware optimization persisted output",
            }
        )
    if float(method.get("cash_weight") or 0) > 0:
        holdings.append(
            {
                "ticker": "CASH",
                "name": "现金",
                "role": "cash",
                "weight": round(float(method["cash_weight"]) * 100, 6),
                "reason": "VNext hard cash-minimum constraint",
            }
        )
    return {
        "generated_at": payload.get("generated_at"),
        "as_of": payload.get("as_of"),
        "strategy": "vnext:cost_aware",
        "holdings": holdings,
        "expected_annual_return": method.get("annualized_return_estimate"),
        "expected_volatility": method.get("annualized_volatility"),
        "expected_sharpe": method.get("sharpe_estimate"),
        "risk_level": "research_only",
        "status": "research_only",
        "data_snapshot_id": payload["data_snapshot_id"],
        "target_weights_hash": payload["target_weights_hash"],
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "hard_constraints": method.get("hard_constraints", {}),
        "real_broker_called": payload.get("real_broker_called") is True,
        "order_output": payload.get("order_output") is True,
    }


@router.get("/portfolio/recommendation/latest")
async def get_latest_recommendation(request: Request):
    """Return the latest real VNext optimization artifact."""
    try:
        recommendation = _latest_optimization()
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        return api_error(
            "PORTFOLIO_OPTIMIZATION_UNAVAILABLE",
            f"VNext portfolio artifact unavailable: {type(exc).__name__}",
            status_code=503,
            request=request,
        )
    return api_success(data=recommendation, request=request)


@router.post("/portfolio/recommendation/run")
async def run_recommendation(request: Request, body: dict):
    """Fail visibly until the governed optimizer is wired to this legacy request."""
    strategy = str(body.get("strategy") or "multi_factor")
    audit_service.record(
        event_type="portfolio",
        resource="/api/portfolio/recommendation/run",
        action="blocked",
        detail={"strategy": strategy, "reason": "governed_optimizer_not_integrated", "fake_result_generated": False},
    )
    return api_error(
        "PORTFOLIO_RUNNER_NOT_INTEGRATED",
        "交互式 legacy 推荐器已退役；latest 仅展示 VNext 已持久化优化结果。",
        status_code=503,
        request=request,
    )
