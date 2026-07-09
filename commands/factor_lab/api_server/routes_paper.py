"""Paper Trading API routes — V7.7 纸面交易仪表盘

提供虚拟账户、持仓、模拟下单和成交历史的 REST API:
  - GET    /api/paper/balance      — 虚拟账户余额/总资产
  - GET    /api/paper/positions    — 当前持仓列表
  - POST   /api/paper/orders       — 下模拟订单
  - GET    /api/paper/orders       — 订单历史
  - DELETE /api/paper/orders/{id}  — 撤销未成交订单
  - GET    /api/paper/fills        — 成交记录
  - POST   /api/paper/reset        — 重置账户

通过模块级 PaperTradingService 单例连接底层交易引擎。
测试时可用 monkeypatch 替换 _get_service()。
"""

from typing import Optional

from fastapi import APIRouter, Query, Path

from factor_lab.api_server.response import api_success, api_error
from factor_lab.paper_trading_service import _get_service, _reset_service

router = APIRouter()


# ===================================================================
# 端点
# ===================================================================


@router.get("/paper/balance")
def paper_balance():
    """GET /api/paper/balance — 虚拟账户余额与资产汇总

    返回现金、总资产、未实现盈亏、已实现盈亏等。
    """
    try:
        service = _get_service()
        return api_success(data=service.get_balance())
    except Exception as e:
        return api_error("PAPER_ERROR", f"获取余额失败: {type(e).__name__}", status_code=500)


@router.get("/paper/positions")
def paper_positions(
    symbol: str = Query("", description="按代码过滤"),
):
    """GET /api/paper/positions — 当前持仓列表"""
    try:
        service = _get_service()
        positions = service.get_positions(symbol=symbol)
        return api_success(data={
            "total": len(positions),
            "positions": positions,
        })
    except Exception as e:
        return api_error("PAPER_ERROR", f"获取持仓失败: {type(e).__name__}", status_code=500)


@router.post("/paper/orders")
def paper_place_order(
    symbol: str = Query(..., description="股票代码"),
    side: str = Query(..., description="buy/sell"),
    quantity: int = Query(..., description="数量"),
    price: float = Query(..., description="价格"),
    order_type: str = Query("limit", description="limit/market"),
):
    """POST /api/paper/orders — 下模拟订单

    同步尝试模拟成交（限价单以指定价格成交，市价单以当前价格成交）。
    返回订单详情包含成交状态。
    """
    try:
        service = _get_service()
        result = service.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
        )
        if "error" in result:
            return api_error("ORDER_FAILED", result["error"], status_code=400)
        return api_success(data=result)
    except Exception as e:
        return api_error("PAPER_ERROR", f"下单失败: {type(e).__name__}", status_code=500)


@router.get("/paper/orders")
def paper_orders(
    status: str = Query("", description="按状态过滤"),
    symbol: str = Query("", description="按代码过滤"),
    limit: int = Query(100, description="最多返回条数"),
):
    """GET /api/paper/orders — 订单历史

    支持按 status / symbol 过滤，按创建时间倒序排列。
    """
    try:
        service = _get_service()
        orders = service.get_orders(status=status, symbol=symbol, limit=limit)
        return api_success(data={
            "total": len(orders),
            "orders": orders,
        })
    except Exception as e:
        return api_error("PAPER_ERROR", f"获取订单失败: {type(e).__name__}", status_code=500)


@router.delete("/paper/orders/{order_id}")
def paper_cancel_order(
    order_id: str = Path(..., description="订单 ID"),
):
    """DELETE /api/paper/orders/{id} — 撤销未成交订单

    仅可撤销 pending/partial 状态的订单。
    """
    try:
        service = _get_service()
        result = service.cancel_order(order_id)
        if "error" in result:
            return api_error("ORDER_CANCEL_FAILED", result["error"], status_code=400)
        return api_success(data=result)
    except Exception as e:
        return api_error("PAPER_ERROR", f"撤单失败: {type(e).__name__}", status_code=500)


@router.get("/paper/fills")
def paper_fills(
    symbol: str = Query("", description="按代码过滤"),
    limit: int = Query(100, description="最多返回条数"),
):
    """GET /api/paper/fills — 成交记录"""
    try:
        service = _get_service()
        fills = service.get_fills(symbol=symbol, limit=limit)
        return api_success(data={
            "total": len(fills),
            "fills": fills,
        })
    except Exception as e:
        return api_error("PAPER_ERROR", f"获取成交失败: {type(e).__name__}", status_code=500)


@router.post("/paper/reset")
def paper_reset(
    initial_cash: float = Query(1_000_000.0, description="初始现金金额"),
):
    """POST /api/paper/reset — 重置虚拟账户到初始状态"""
    try:
        service = _get_service()
        service.reset(initial_cash=initial_cash)
        return api_success(data={
            "status": "ok",
            "message": f"账户已重置，初始现金 {initial_cash:,.0f}",
            "balance": service.get_balance(),
        })
    except Exception as e:
        return api_error("PAPER_ERROR", f"重置失败: {type(e).__name__}", status_code=500)


@router.get("/paper/status")
def paper_status():
    """GET /api/paper/status — Paper trading 运行状态"""
    try:
        service = _get_service()
        bal = service.get_balance()
        return api_success(data={
            "running": True,
            "balance": bal,
            "mode": "paper",
        })
    except Exception as e:
        return api_success(data={
            "running": False,
            "balance": None,
            "mode": "paper",
        })


@router.get("/shadow/status")
def shadow_status():
    """GET /api/shadow/status — Shadow trading 运行状态"""
    try:
        from factor_lab.paper.shadow_trading import ShadowTradingEngine
        engine = ShadowTradingEngine()
        return api_success(data={
            "running": True,
            "mode": "shadow",
        })
    except Exception as e:
        return api_success(data={
            "running": False,
            "mode": "shadow",
        })
