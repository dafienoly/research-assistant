"""System status routes."""

from fastapi import APIRouter, Request

from factor_lab.api_server.response import api_success
from factor_lab.leader.ops_dashboard import get_manager

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    """Return operational health without Agent or roadmap state."""
    health = get_manager().health()
    level = "green" if health.get("overall") == "healthy" else "amber"
    return api_success(
        data={"state": {"level": level}, "health": health},
        request=request,
    )
