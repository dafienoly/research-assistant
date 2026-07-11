"""QMT 行情接口 API — 查询实时行情、K线数据。
"""

import asyncio
import logging

from fastapi import APIRouter, Request

from factor_lab.api_server.response import api_success, api_error
from factor_lab.broker.qmt_client import QMTClient

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_client() -> QMTClient | None:
    c = QMTClient()
    return c if c.is_configured() else None


async def _call(client: QMTClient, method: str, *args, **kwargs):
    return await asyncio.to_thread(getattr(client, method), *args, **kwargs)


@router.get("/qmt/health")
async def qmt_health(request: Request):
    client = _get_client()
    if not client:
        return api_error(code="QMT_NOT_CONFIGURED", message="QMT_BRIDGE_BASE_URL 未配置", request=request)
    try:
        resp = await _call(client, "health")
    except Exception as e:
        return api_error(code="QMT_BRIDGE_ERROR", message=f"QMT 网关不可达: {e}", request=request)
    if resp.get("status") != "ok":
        return api_error(code="QMT_UNAVAILABLE", message=resp.get("error", "QMT 异常"), request=request)
    bridge = resp.get("data", {})
    # Bridge returns {connected, xtdata_available, xttrader_available, ...}
    # Frontend QmtData schema expects {status, connected, mode, latency_ms, version, ...}
    return api_success(data={
        "status": "connected" if bridge.get("connected") else "disconnected",
        "connected": bool(bridge.get("connected", False)),
        "mode": "simulation",
        "latency_ms": bridge.get("latency_ms", 0),
        "version": bridge.get("version", "6.3.2"),
        "xtdata_available": bool(bridge.get("xtdata_available", False)),
        "xttrader_available": bool(bridge.get("xttrader_available", False)),
        "xttrader_connected": bool(bridge.get("xttrader_connected", False)),
        "live_trading_enabled": bool(bridge.get("live_trading_enabled", False)),
    }, request=request)


@router.get("/qmt/quotes")
async def qmt_quotes(symbols: str = "", request: Request = None):
    """查询实时行情。symbols: 逗号分隔，如 000001.SZ,600519.SH"""
    client = _get_client()
    if not client:
        return api_error(code="QMT_NOT_CONFIGURED", message="QMT_BRIDGE_BASE_URL 未配置", request=request)
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return api_error(code="QMT_MISSING_PARAM", message="请提供 symbols 参数", request=request)
    try:
        resp = await _call(client, "get_quotes", sym_list)
    except Exception as e:
        return api_error(code="QMT_BRIDGE_ERROR", message=f"获取行情失败: {e}", request=request)
    if resp.get("status") != "ok":
        return api_error(code="QMT_QUOTES_ERROR", message=resp.get("error", "行情查询失败"), request=request)
    return api_success(data=resp.get("data", {}), request=request)


@router.get("/qmt/bars")
async def qmt_bars(symbol: str = "", period: str = "1d", count: int = 120, request: Request = None):
    """查询 K 线数据。"""
    client = _get_client()
    if not client:
        return api_error(code="QMT_NOT_CONFIGURED", message="QMT_BRIDGE_BASE_URL 未配置", request=request)
    if not symbol:
        return api_error(code="QMT_MISSING_PARAM", message="请提供 symbol 参数", request=request)
    try:
        resp = await _call(client, "get_bars", symbol, period, count)
    except Exception as e:
        return api_error(code="QMT_BRIDGE_ERROR", message=f"获取 K 线失败: {e}", request=request)
    if resp.get("status") != "ok":
        return api_error(code="QMT_BARS_ERROR", message=resp.get("error", "K线查询失败"), request=request)
    return api_success(data=resp.get("data", {}), request=request)


# ── 交易接口（需 miniQMT，当前不可用）─────────────────────────────


@router.get("/qmt/account")
async def qmt_account(request: Request):
    client = _get_client()
    if not client:
        return api_success(data={"available": False, "accounts": [], "total_asset": None, "available_cash": None, "error": "QMT bridge not configured"}, request=request)
    try:
        resp = await _call(client, "get_account")
    except Exception as exc:
        return api_success(data={"available": False, "accounts": [], "total_asset": None, "available_cash": None, "error": str(exc)}, request=request)
    if resp.get("status") != "ok":
        return api_success(data={"available": False, "accounts": [], "total_asset": None, "available_cash": None, "error": resp.get("error", "QMT account unavailable")}, request=request)
    raw = resp.get("data", {})
    # Bridge returns a single asset dict or None → wrap in accounts[]
    accounts = [raw] if isinstance(raw, dict) and (raw.get("m_dTotalAsset") is not None or raw.get("total_asset") is not None) else []
    return api_success(data={
        "available": bool(accounts),
        "accounts": accounts,
        "total_asset": raw.get("m_dTotalAsset", raw.get("total_asset")) if accounts else None,
        "available_cash": raw.get("m_dAvailable", raw.get("cash")) if accounts else None,
    }, request=request)


@router.get("/qmt/positions")
async def qmt_positions(request: Request):
    client = _get_client()
    if not client:
        return api_success(data={"available": False, "positions": [], "total_market_value": None, "total_profit_loss": None, "position_count": None, "error": "QMT bridge not configured"}, request=request)
    try:
        resp = await _call(client, "get_positions")
    except Exception as exc:
        return api_success(data={"available": False, "positions": [], "total_market_value": None, "total_profit_loss": None, "position_count": None, "error": str(exc)}, request=request)
    if resp.get("status") != "ok":
        return api_success(data={"available": False, "positions": [], "total_market_value": None, "total_profit_loss": None, "position_count": None, "error": resp.get("error", "QMT positions unavailable")}, request=request)
    raw_list = resp.get("data")
    positions = raw_list if isinstance(raw_list, list) else []
    total_mv = sum(p.get("m_dMarketValue", p.get("market_value", 0)) or 0 for p in positions)
    total_pnl = sum(p.get("m_dProfitLoss", p.get("profit_loss", 0)) or 0 for p in positions)
    return api_success(data={
        "available": True,
        "positions": positions,
        "total_market_value": total_mv,
        "total_profit_loss": total_pnl,
        "position_count": len(positions),
    }, request=request)


@router.get("/qmt/orders")
async def qmt_orders(request: Request):
    client = _get_client()
    if not client:
        return api_success(data=[], request=request)
    try:
        resp = await _call(client, "get_orders")
    except Exception:
        return api_success(data=[], request=request)
    if resp.get("status") != "ok":
        return api_success(data=[], request=request)
    return api_success(data=resp.get("data", []) if isinstance(resp.get("data"), list) else [], request=request)


@router.get("/qmt/trades")
async def qmt_trades(request: Request):
    client = _get_client()
    if not client:
        return api_success(data=[], request=request)
    try:
        resp = await _call(client, "get_trades")
    except Exception:
        return api_success(data=[], request=request)
    if resp.get("status") != "ok":
        return api_success(data=[], request=request)
    return api_success(data=resp.get("data", []) if isinstance(resp.get("data"), list) else [], request=request)
