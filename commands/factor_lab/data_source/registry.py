"""DataRegistry — 数据源注册表管理系统

File-based registry following the Alpha Registry pattern in
factor_lab/alpha/registry.py. Maintains an index + per-source spec files
in HermesData.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from factor_lab.data_source.spec import (
    DataSourceSpec,
    DataSourceStatus,
    validate_spec,
    VALID_STATUSES,
)


CST = timezone(timedelta(hours=8))
REGISTRY_ROOT = Path("/mnt/d/HermesData/data_source_registry")


def _registry_index_path() -> Path:
    return REGISTRY_ROOT / "registry_index.json"


def _registry_config_path() -> Path:
    return REGISTRY_ROOT / "config.json"


# =========================================================================
# 默认数据源 (seeded from existing provider_matrix.py system)
# =========================================================================
DEFAULT_SOURCES = [
    DataSourceSpec(
        source_id="rsscast_mcp",
        name="RSScast MCP 主数据源",
        category="market",
        capabilities=["realtime_quote", "kline_daily", "kline_minute", "snapshot", "overview", "index"],
        priority=1,
        config={"requires_api_key": True, "env_var": "RSSCAST_API_KEY"},
    ),
    DataSourceSpec(
        source_id="eastmoney_direct",
        name="Eastmoney Direct 直连",
        category="market",
        capabilities=["realtime_quote", "kline_daily"],
        priority=2,
        config={"geo_blocked": True, "note": "非中国IP被CDN层拒绝"},
    ),
    DataSourceSpec(
        source_id="tencent_qt",
        name="Tencent qt.gtimg.cn 实时行情",
        category="market",
        capabilities=["realtime_quote", "kline_daily"],
        priority=3,
        config={"base_url": "https://qt.gtimg.cn", "encoding": "gbk"},
    ),
    DataSourceSpec(
        source_id="sina",
        name="Sina hq.sinajs.cn 实时行情备用",
        category="market",
        capabilities=["realtime_quote"],
        priority=4,
        config={"base_url": "https://hq.sinajs.cn"},
    ),
    DataSourceSpec(
        source_id="akshare_spot",
        name="AKShare 全A快照",
        category="market",
        capabilities=["snapshot"],
        priority=1,
        config={"endpoint": "stock_zh_a_spot"},
    ),
    DataSourceSpec(
        source_id="baostock",
        name="Baostock 免费数据",
        category="fundamental",
        capabilities=["fundamental", "kline_daily", "kline_minute"],
        priority=1,
        config={"network_policy": "adapter_owned", "note": "连接与代理策略由 ingestion adapter 管理"},
    ),
    DataSourceSpec(
        source_id="announcement",
        name="CNINFO/SSE/SZSE 公告",
        category="announcement",
        capabilities=["announcement"],
        priority=1,
        config={"sources": ["cninfo", "sse", "szse"]},
    ),
]


# =========================================================================
# Internal helpers
# =========================================================================

def _ensure_registry():
    REGISTRY_ROOT.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[dict]:
    _ensure_registry()
    idx_path = _registry_index_path()
    if idx_path.exists():
        return json.loads(idx_path.read_text(encoding="utf-8"))
    return []


def _save_index(index: list[dict]):
    _ensure_registry()
    idx_path = _registry_index_path()
    idx_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _source_dir(source_id: str) -> Path:
    return REGISTRY_ROOT / source_id


def _spec_path(source_id: str) -> Path:
    return _source_dir(source_id) / "data_source_spec.json"


# =========================================================================
# Registry API
# =========================================================================

class DataRegistry:
    """数据源注册表 — CRUD + 查询"""

    def __init__(self):
        _ensure_registry()

    # ---- CRUD ----

    def register(self, spec: DataSourceSpec) -> dict:
        """注册或更新数据源"""
        errors = validate_spec(spec)
        if errors:
            return {"status": "error", "errors": errors}

        now = datetime.now(CST).isoformat()
        spec.updated_at = now
        if not spec.created_at:
            spec.created_at = now

        # Write spec file
        source_dir = _source_dir(spec.source_id)
        source_dir.mkdir(parents=True, exist_ok=True)
        _spec_path(spec.source_id).write_text(
            json.dumps(spec.to_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # Update index
        index = _load_index()
        entry = {
            "source_id": spec.source_id,
            "name": spec.name,
            "category": spec.category,
            "capabilities": spec.capabilities,
            "priority": spec.priority,
            "status": spec.status,
        }
        existing = [i for i, e in enumerate(index) if e["source_id"] == spec.source_id]
        if existing:
            index[existing[0]] = entry
        else:
            index.append(entry)
        _save_index(index)

        return {"status": "registered", "source_id": spec.source_id}

    def list_sources(self, category: str = None, capability: str = None,
                     status: str = None) -> list[dict]:
        """列出数据源，支持按分类、能力、状态筛选

        Returns:
            匹配的数据源列表 (index entries)
        """
        index = _load_index()
        result = index

        if category:
            result = [e for e in result if e.get("category") == category]
        if capability:
            result = [e for e in result if capability in e.get("capabilities", [])]
        if status:
            result = [e for e in result if e.get("status") == status]

        return result

    def get_source(self, source_id: str) -> Optional[DataSourceSpec]:
        """获取数据源完整规范"""
        path = _spec_path(source_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return DataSourceSpec.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def update_status(self, source_id: str, new_status: str) -> dict:
        """更新数据源状态"""
        if new_status not in VALID_STATUSES:
            return {"status": "error", "error": f"invalid status '{new_status}'"}

        spec = self.get_source(source_id)
        if spec is None:
            return {"status": "error", "error": f"source '{source_id}' not found"}

        spec.status = new_status
        spec.updated_at = datetime.now(CST).isoformat()
        self.register(spec)

        return {"status": "updated", "source_id": source_id, "new_status": new_status}

    def get_preferred(self, capability: str, category: str = None) -> Optional[DataSourceSpec]:
        """获取指定能力的最高优先级活跃数据源"""
        matches = self.list_sources(category=category, capability=capability)
        active = [m for m in matches if m.get("status") in (DataSourceStatus.ACTIVE.value, DataSourceStatus.UNCHECKED.value)]
        if not active:
            return None
        # Sort by priority (lower = better)
        active.sort(key=lambda x: x.get("priority", 10))
        return self.get_source(active[0]["source_id"])

    def delete_source(self, source_id: str) -> dict:
        """删除数据源"""
        import shutil

        index = _load_index()
        new_index = [e for e in index if e["source_id"] != source_id]
        if len(new_index) == len(index):
            return {"status": "error", "error": f"source '{source_id}' not found"}

        _save_index(new_index)

        # Remove directory
        sdir = _source_dir(source_id)
        if sdir.exists():
            shutil.rmtree(sdir)

        return {"status": "deleted", "source_id": source_id}

    # ---- Seeds ----

    def seed_defaults(self) -> int:
        """注册所有默认数据源，返回注册数量"""
        count = 0
        for spec in DEFAULT_SOURCES:
            result = self.register(spec)
            if result["status"] == "registered":
                count += 1
        return count

    def is_seeded(self) -> bool:
        """检查是否已初始化种子数据"""
        index = _load_index()
        # Check if at least 4 of the default sources exist
        default_ids = {s.source_id for s in DEFAULT_SOURCES}
        registered_ids = {e["source_id"] for e in index}
        return len(default_ids & registered_ids) >= 4

    # ---- Config ----

    def get_config(self) -> dict:
        """获取注册表级配置"""
        _ensure_registry()
        cfg_path = _registry_config_path()
        if cfg_path.exists():
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        return {}

    def save_config(self, config: dict):
        """保存注册表级配置"""
        _ensure_registry()
        _registry_config_path().write_text(
            json.dumps(config, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
