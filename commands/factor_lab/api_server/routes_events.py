"""Hash-verified canonical corporate-event API."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from factor_lab.api_server.response import api_success
from factor_lab.datahub_access import read_corporate_event_records, read_stock_name_map

router = APIRouter()

EVENT_TYPE = {
    "holdertrade": "股东增减持",
    "repurchase": "回购",
    "share_float": "限售解禁",
    "dividend": "分红",
    "forecast": "业绩预告",
}


def _direction(dataset: str, payload: dict[str, Any]) -> str:
    if dataset == "holdertrade":
        marker = str(payload.get("in_de", "")).upper()
        return "positive" if marker in {"IN", "增持"} else "negative" if marker in {"DE", "减持"} else "neutral"
    if dataset in {"repurchase", "dividend"}:
        return "positive"
    if dataset == "share_float":
        return "negative"
    forecast = str(payload.get("type") or payload.get("forecast_type") or "")
    if any(marker in forecast for marker in ("预增", "略增", "扭亏", "预盈", "减亏")):
        return "positive"
    if any(marker in forecast for marker in ("预减", "略减", "续亏", "首亏")):
        return "negative"
    return "neutral"


def _title(dataset: str, payload: dict[str, Any]) -> str:
    label = EVENT_TYPE.get(dataset, dataset or "公司事件")
    if dataset == "holdertrade":
        holder = str(payload.get("holder_name") or "股东")
        action = "增持" if _direction(dataset, payload) == "positive" else "减持" if _direction(dataset, payload) == "negative" else "持股变动"
        return f"{holder}{action}"
    if dataset == "forecast":
        forecast = str(payload.get("type") or payload.get("forecast_type") or "")
        return f"业绩预告：{forecast}" if forecast else label
    return label


def _event_view(record: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    payload = record["payload"]
    dataset = str(record.get("event_dataset") or "")
    ts_code = str(record.get("ts_code") or "")
    compact_date = str(record.get("event_date") or "").replace("-", "")[:8]
    event_date = datetime.strptime(compact_date, "%Y%m%d").date().isoformat()
    identity = json.dumps(
        {"ts_code": ts_code, "dataset": dataset, "event_date": compact_date, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    event_id = "corp_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    direction = _direction(dataset, payload)
    return {
        "id": event_id,
        "event_date": event_date,
        "ts_code": ts_code,
        "name": names.get(ts_code.split(".")[0], ""),
        "event_type": EVENT_TYPE.get(dataset, dataset),
        "event_direction": direction,
        "event_strength": 4 if direction != "neutral" else 2,
        "event_source": f"datahub:{record.get('source_provider', 'unknown')}",
        "title": _title(dataset, payload),
        "detail": json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        "risk_flags": ["canonical_manifest_partial"] if record.get("manifest_status") == "PARTIAL" else [],
        "source_ref": f"{record.get('partition')}#sha256={record.get('partition_sha256')}",
        "observed_at": record.get("observed_at"),
    }


def _canonical_events() -> list[dict[str, Any]]:
    names = read_stock_name_map()
    events = [_event_view(record, names) for record in read_corporate_event_records()]
    return sorted(events, key=lambda item: (item["event_date"], item["id"]), reverse=True)


@router.get("/events")
async def list_events(
    request: Request,
    event_type: str = Query("", description="按公司事件类型过滤"),
    direction: str = Query("", description="按方向过滤: positive/negative/neutral"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return only persisted and hash-verified corporate events."""
    try:
        all_events = _canonical_events()
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"canonical corporate events unavailable: {type(exc).__name__}") from exc
    filtered = all_events
    if event_type:
        filtered = [event for event in filtered if event["event_type"] == event_type]
    if direction:
        filtered = [event for event in filtered if event["event_direction"] == direction]

    now = datetime.now().astimezone().date()
    by_type_30d = Counter(event["event_type"] for event in all_events if datetime.fromisoformat(event["event_date"]).date() >= now - timedelta(days=30))
    by_type_90d = Counter(event["event_type"] for event in all_events if datetime.fromisoformat(event["event_date"]).date() >= now - timedelta(days=90))

    return api_success(
        data={
            "events": filtered[offset : offset + limit],
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "stats": {"total": len(all_events), "by_type_30d": dict(by_type_30d), "by_type_90d": dict(by_type_90d)},
            "factor_performance": [],
        },
        request=request,
    )


@router.get("/events/{event_id}")
async def event_detail(request: Request, event_id: str):
    try:
        event = next((item for item in _canonical_events() if item["id"] == event_id), None)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"canonical corporate events unavailable: {type(exc).__name__}") from exc
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return api_success(data=event, request=request)
