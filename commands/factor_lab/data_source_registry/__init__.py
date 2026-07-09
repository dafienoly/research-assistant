# Data Source Registry V5.0 — 数据源注册表
"""
Data Source Registry 管理所有接入的数据源及其状态。
每个数据源记录: source_id, name, type, provider, status, refresh_frequency, last_refresh, record_count

用法:
  from data_source_registry.registry import list_sources, get_source, register_source
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
REGISTRY_FILE = Path("/mnt/d/HermesData/data_source_registry.json")


def _load():
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text())
    return {"sources": [], "version": "1.0"}


def _save(data):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(data, indent=2))


def register_source(source_id, name, source_type, provider, refresh_freq="1d"):
    data = _load()
    for s in data["sources"]:
        if s["source_id"] == source_id:
            return s
    entry = {
        "source_id": source_id, "name": name, "type": source_type,
        "provider": provider, "refresh_frequency": refresh_freq,
        "status": "pending", "last_refresh": "", "record_count": 0,
    }
    data["sources"].append(entry)
    _save(data)
    return entry


def list_sources(source_type=None):
    data = _load()
    if source_type:
        return [s for s in data["sources"] if s["type"] == source_type]
    return data["sources"]


def get_source(source_id):
    for s in _load()["sources"]:
        if s["source_id"] == source_id:
            return s
    return None


def update_source_status(source_id: str, status: str, last_refresh: str = "",
                         record_count: int = 0, extra: Optional[dict] = None) -> dict:
    """更新数据源状态

    Args:
        source_id: 数据源ID
        status: 新状态 (pending/active/degraded/inactive)
        last_refresh: 最近刷新时间 (ISO格式或空字符串)
        record_count: 当前记录数
        extra: 额外字段 (合并到 entry 中)

    Returns:
        {"status": "ok"} 或 {"status": "error", "error": "..."}
    """
    VALID_STATUSES = {"pending", "active", "degraded", "inactive"}
    if status not in VALID_STATUSES:
        return {"status": "error", "error": f"invalid status '{status}'"}

    data = _load()
    for entry in data["sources"]:
        if entry["source_id"] == source_id:
            entry["status"] = status
            if last_refresh:
                entry["last_refresh"] = last_refresh
            if record_count > 0:
                entry["record_count"] = record_count
            entry["updated_at"] = datetime.now(CST).isoformat()
            if extra:
                entry.update(extra)
            _save(data)
            return {"status": "ok", "source_id": source_id, "new_status": status}

    return {"status": "error", "error": f"source '{source_id}' not found"}


def batch_update_source_status(source_ids: list[str], status: str,
                               last_refresh: str = "", record_count: int = 0,
                               extra: Optional[dict] = None) -> dict:
    """批量更新数据源状态"""
    now_ts = datetime.now(CST).isoformat()
    valid_statuses = {"pending", "active", "degraded", "inactive"}
    if status not in valid_statuses:
        return {"status": "error", "error": f"invalid status '{status}'"}

    data = _load()
    updated, not_found = [], []
    for source_id in source_ids:
        for entry in data["sources"]:
            if entry["source_id"] == source_id:
                entry["status"] = status
                if last_refresh:
                    entry["last_refresh"] = last_refresh
                if record_count > 0:
                    entry["record_count"] = record_count
                entry["updated_at"] = now_ts
                if extra:
                    entry.update(extra)
                updated.append(source_id)
                break
        else:
            not_found.append(source_id)

    if updated:
        _save(data)
    return {
        "status": "ok",
        "updated": updated,
        "not_found": not_found,
        "new_status": status,
    }


def delete_source(source_id: str) -> dict:
    """删除数据源"""
    data = _load()
    before = len(data["sources"])
    data["sources"] = [s for s in data["sources"] if s["source_id"] != source_id]
    if len(data["sources"]) < before:
        _save(data)
        return {"status": "ok", "source_id": source_id}
    return {"status": "error", "error": f"source '{source_id}' not found"}
