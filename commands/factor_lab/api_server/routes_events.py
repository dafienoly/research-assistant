"""事件 (Events) API — 全局事件流。"""

from fastapi import APIRouter, Request, Query
from factor_lab.api_server.response import api_success

router = APIRouter()


@router.get("/events")
async def list_events(
    request: Request,
    event_type: str = Query("", description="按类型过滤: market/risk/system/data/trade"),
    severity: str = Query("", description="按严重程度过滤: info/warning/critical"),
    limit: int = Query(50, ge=1, le=200),
):
    """获取全局事件流。"""
    import random
    from datetime import datetime, timezone, timedelta

    CST = timezone(timedelta(hours=8))
    now = datetime.now(CST)

    all_events = [
        {"id": "evt_001", "type": "market", "severity": "info", "title": "沪深300 收涨 1.2%", "timestamp": now.isoformat(), "source": "market"},
        {"id": "evt_002", "type": "risk", "severity": "warning", "title": "波动率指数上升至 22.5", "timestamp": now.isoformat(), "source": "risk"},
        {"id": "evt_003", "type": "system", "severity": "info", "title": "数据同步完成", "timestamp": now.isoformat(), "source": "system"},
        {"id": "evt_004", "type": "trade", "severity": "info", "title": "卖出 688001 10000 股 @ 92.30", "timestamp": now.isoformat(), "source": "execution"},
        {"id": "evt_005", "type": "data", "severity": "critical", "title": "数据源 eastmoney 连接超时", "timestamp": now.isoformat(), "source": "data"},
        {"id": "evt_006", "type": "market", "severity": "warning", "title": "半导体板块资金净流出 12 亿", "timestamp": now.isoformat(), "source": "market"},
        {"id": "evt_007", "type": "system", "severity": "info", "title": "因子缓存刷新完成", "timestamp": now.isoformat(), "source": "system"},
    ]

    filtered = all_events
    if event_type:
        filtered = [e for e in filtered if e["type"] == event_type]
    if severity:
        filtered = [e for e in filtered if e["severity"] == severity]

    return api_success(
        data={
            "events": filtered[:limit],
            "total": len(filtered),
            "limit": limit,
        },
        request=request,
    )
