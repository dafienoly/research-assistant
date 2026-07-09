"""系统设置 (Settings) API — 获取系统配置。"""

from fastapi import APIRouter, Request
from factor_lab.api_server.response import api_success

router = APIRouter()


@router.get("/settings")
async def get_settings(request: Request):
    """获取系统设置。"""
    import os
    return api_success(
        data={
            "api_version": "5.0.0",
            "app_name": "Hermes Quant Studio",
            "environment": os.environ.get("HERMES_ENV", "development"),
            "features": {
                "backtest": True,
                "live_trading": False,
                "paper_trading": True,
                "risk_management": True,
                "factor_mining": True,
                "portfolio_optimization": True,
            },
            "limits": {
                "max_concurrent_jobs": 10,
                "max_backtest_days": 3650,
                "max_universe_size": 5000,
                "max_positions": 50,
            },
            "defaults": {
                "universe": "hs300",
                "benchmark": "hs300",
                "risk_free_rate": 0.025,
                "backtest_start": "2024-01-01",
            },
        },
        request=request,
    )
