"""Data Health Dashboard V5.8 — 数据健康状态 API"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.data_source_registry import list_sources

CST = timezone(timedelta(hours=8))


def health_check() -> dict:
    """返回所有数据源的健康状态"""
    sources = list_sources()
    results = []
    for s in sources:
        results.append({
            "source_id": s["source_id"],
            "name": s["name"],
            "type": s["type"],
            "status": s.get("status", "unknown"),
            "last_refresh": s.get("last_refresh", ""),
            "record_count": s.get("record_count", 0),
            "healthy": s.get("status") == "active",
        })
    return {
        "checked_at": datetime.now(CST).isoformat(),
        "total_sources": len(sources),
        "healthy": sum(1 for r in results if r["healthy"]),
        "unhealthy": sum(1 for r in results if not r["healthy"]),
        "sources": results,
    }
