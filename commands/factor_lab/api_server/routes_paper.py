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


@router.get("/paper/dashboard")
def paper_dashboard():
    """GET /api/paper/dashboard — Paper 交易仪表盘聚合数据"""
    try:
        service = _get_service()
        dashboard = service.get_dashboard()
        return api_success(data=dashboard)
    except Exception as e:
        return api_error("PAPER_ERROR", f"获取 dashboard 失败: {type(e).__name__}: {e}", status_code=500)


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


@router.get("/shadow/dashboard")
def shadow_dashboard(
    date: str = Query("", description="交易日 YYYY-MM-DD，默认最近交易日"),
):
    """GET /api/shadow/dashboard — Shadow 交易仪表盘聚合数据"""
    try:
        from factor_lab.paper.shadow_trading import ShadowTradingEngine

        target_date = date
        if not target_date:
            from datetime import datetime, timezone, timedelta
            from factor_lab.data.tushare_client import get_ts_client
            CST = timezone(timedelta(hours=8))
            tc = get_ts_client()
            today = datetime.now(CST).strftime("%Y%m%d")
            cal = tc.trade_cal(start_date=(datetime.now(CST) - timedelta(days=10)).strftime("%Y%m%d"),
                               end_date=today)
            import pandas as pd
            if isinstance(cal, pd.DataFrame) and not cal.empty:
                dates = cal["cal_date"].tolist() if "cal_date" in cal.columns else []
                if dates:
                    latest = dates[-1]
                    if hasattr(latest, "strftime"):
                        target_date = latest.strftime("%Y-%m-%d")
                    else:
                        s = str(latest).replace("-", "").replace(" ", "").replace(":", "")[:8]
                        target_date = datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
                else:
                    target_date = datetime.now(CST).strftime("%Y-%m-%d")
            else:
                target_date = datetime.now(CST).strftime("%Y-%m-%d")

        engine = ShadowTradingEngine(capital=50000)
        result = engine.run_shadow(target_date)
        # 映射为前端 ShadowDashboardData 结构
        mapped = _map_shadow_dashboard(result)
        return api_success(data=mapped)
    except Exception as e:
        return api_error("SHADOW_ERROR", f"获取 shadow dashboard 失败: {type(e).__name__}: {e}", status_code=500)


def _map_shadow_dashboard(raw: dict) -> dict:
    """将 ShadowTradingEngine.run_shadow() 输出映射为前端 ShadowDashboardData"""
    plan_stocks = raw.get("plan", {}).get("stocks", [])
    plan_stocks_mapped = []
    for s in plan_stocks:
        is_blocked = not s.get("is_tradable", True)
        reasons = s.get("block_reasons", [])
        est_amount = s.get("estimated_amount", 0)
        shares = s.get("shares", 0)
        plan_stocks_mapped.append({
            "symbol": s.get("symbol", ""),
            "name": s.get("name", ""),
            "direction": "buy",
            "price": round(est_amount / shares, 2) if shares > 0 and est_amount > 0 else 0,
            "shares": shares,
            "weight_pct": round(s.get("weight", 0) * 100, 1),
            "status": "blocked" if is_blocked else "planned",
            "block_reason": reasons[0] if reasons else None,
            "estimated_amount": est_amount,
        })

    execution = raw.get("execution", {})
    fills = execution.get("fills", [])
    trades_mapped = []
    for f in fills:
        trades_mapped.append({
            "trade_id": f.get("trade_id", "") or f.get("fill_id", ""),
            "symbol": f.get("symbol", ""),
            "name": f.get("name", ""),
            "direction": f.get("direction", "buy"),
            "fill_price": f.get("fill_price", f.get("price", 0)),
            "fill_shares": f.get("fill_shares", f.get("shares", 0)),
            "fill_amount": f.get("fill_amount", f.get("amount", 0)),
            "fee": f.get("fee", 0),
            "created_at": f.get("created_at", f.get("timestamp", "")),
        })

    pnl_raw = raw.get("pnl", {})
    total_return = pnl_raw.get("total_return_pct", 0)
    pnl = {
        "daily_return_pct": total_return,
        "total_return_pct": total_return,
        "total_value": pnl_raw.get("total_value", 0),
    }

    risk = raw.get("risk_interceptions", {})
    risk_details = risk.get("details", [])
    risk_mapped = []
    for r in risk_details:
        risk_mapped.append({
            "symbol": r.get("symbol", ""),
            "name": r.get("name", ""),
            "reason": r.get("reason", ""),
            "stage": r.get("stage", ""),
            "timestamp": r.get("timestamp", ""),
        })

    plan = raw.get("plan", {})
    tradability = raw.get("tradability", {})
    performance = raw.get("performance", {})

    return {
        "date": raw.get("date", ""),
        "plan": {
            "signal_date": plan.get("signal_date", ""),
            "n_stocks": len(plan_stocks_mapped),
            "n_tradable": tradability.get("n_tradable_planned", 0),
            "n_blocked": tradability.get("n_check_blocked", 0),
            "stocks": plan_stocks_mapped,
        },
        "execution": {
            "n_filled": execution.get("n_filled", 0),
            "n_partial": execution.get("n_partial", 0),
            "n_blocked": 0,
            "trades": trades_mapped,
        },
        "pnl": pnl,
        "tradability": {
            "n_total": tradability.get("n_total", 0),
            "n_tradable_planned": tradability.get("n_tradable_planned", 0),
            "n_non_tradable_planned": tradability.get("n_non_tradable_planned", 0),
            "n_check_plannable": tradability.get("n_check_plannable", 0),
            "n_check_blocked": tradability.get("n_check_blocked", 0),
            "blocked_by_reason": tradability.get("blocked_by_reason", {}),
            "details": tradability.get("details", []),
        },
        "risk_interceptions": {
            "total_interceptions": risk.get("total_interceptions", len(risk_mapped)),
            "distinct_symbols_blocked": risk.get("distinct_symbols_blocked", 0),
            "by_reason": risk.get("by_reason", {}),
            "by_stage": risk.get("by_stage", {}),
            "details": risk_mapped,
        },
        "market_context": raw.get("market_context", {}),
        "performance": {
            "date": performance.get("date", raw.get("date", "")),
            "strategy_return_pct": performance.get("strategy_return_pct", 0),
            "benchmark_name": performance.get("benchmark_name", "semiconductor_ew"),
            "benchmark_label": performance.get("benchmark_label", "半导体同池等权"),
            "benchmark_return_pct": performance.get("benchmark_return_pct", 0),
            "excess_return_pct": performance.get("excess_return_pct", 0),
            "vs_benchmark": performance.get("vs_benchmark", "跑输"),
        },
        "not_ready": raw.get("not_ready", True),
        "summary": raw.get("summary", ""),
    }
