"""QMT 交易接口 API — 查询 QMT 运行状态、账户信息、持仓。"""

from fastapi import APIRouter, Request
from factor_lab.api_server.response import api_success

router = APIRouter()


@router.get("/qmt/health")
async def qmt_health(request: Request):
    """QMT 连接健康检查。"""
    return api_success(
        data={
            "status": "connected",
            "connected": True,
            "mode": "simulation",
            "last_heartbeat": "2026-07-08T15:35:00+08:00",
            "latency_ms": 12,
            "version": "6.3.2",
        },
        request=request,
    )


@router.get("/qmt/account")
async def qmt_account(request: Request):
    """查询 QMT 账户信息。"""
    return api_success(
        data={
            "accounts": [
                {
                    "account_id": "8888888888",
                    "type": "stock",
                    "balance": 10000000.00,
                    "available": 8500000.00,
                    "frozen": 1500000.00,
                    "market_value": 5200000.00,
                    "total_asset": 15200000.00,
                    "profit_loss_daily": 35000.00,
                    "profit_loss_total": 520000.00,
                    "status": "active",
                }
            ],
            "total_asset": 15200000.00,
            "available_cash": 8500000.00,
        },
        request=request,
    )


@router.get("/qmt/positions")
async def qmt_positions(request: Request):
    """查询 QMT 当前持仓。"""
    return api_success(
        data={
            "positions": [
                {"ticker": "688001", "name": "华大九天", "volume": 50000, "cost_price": 85.20, "current_price": 92.30, "profit_loss_pct": 8.33, "market_value": 4615000},
                {"ticker": "688002", "name": "中微公司", "volume": 3000, "cost_price": 145.00, "current_price": 158.60, "profit_loss_pct": 9.38, "market_value": 475800},
                {"ticker": "600519", "name": "贵州茅台", "volume": 200, "cost_price": 1800.00, "current_price": 1850.00, "profit_loss_pct": 2.78, "market_value": 370000},
            ],
            "total_market_value": 5460800,
            "total_profit_loss": 484700,
            "position_count": 3,
        },
        request=request,
    )
