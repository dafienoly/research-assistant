# Data Source Registry V5.0 — 数据源注册表
"""
Data Source Registry 管理所有接入的数据源及其状态。
每个数据源记录: source_id, name, type, provider, status, refresh_frequency, last_refresh, record_count

用法:
  from data_source_registry.registry import list_sources, get_source, register_source
"""

import json
from pathlib import Path

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
