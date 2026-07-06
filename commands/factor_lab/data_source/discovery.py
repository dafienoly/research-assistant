"""Discovery — 数据源发现与路由

Query API for finding the best data source for a given capability,
listing fallback chains, and resolving source identity.
"""

from __future__ import annotations

from typing import Optional

from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.spec import DataSourceSpec, DataSourceStatus


# Singleton registry
_registry_instance = None


def _get_registry() -> DataRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = DataRegistry()
    return _registry_instance


def resolve_source(capability: str, category: str = None,
                   preferred: str = None) -> Optional[DataSourceSpec]:
    """找到指定能力的最佳可用数据源

    Args:
        capability: 所需能力 (e.g. 'realtime_quote')
        category: 可选分类限定
        preferred: 优先使用指定数据源

    Returns:
        DataSourceSpec 或 None（无可用数据源）
    """
    registry = _get_registry()

    # Try preferred first
    if preferred:
        spec = registry.get_source(preferred)
        if spec and capability in spec.capabilities:
            if spec.status in (DataSourceStatus.ACTIVE.value, DataSourceStatus.UNCHECKED.value):
                return spec

    # Find best by priority
    return registry.get_preferred(capability=capability, category=category)


def list_capable(capability: str, category: str = None) -> list[dict]:
    """列出所有具备指定能力的数据源

    Args:
        capability: 能力名称
        category: 可选分类限定

    Returns:
        数据源列表 (index entries)
    """
    registry = _get_registry()
    return registry.list_sources(category=category, capability=capability)


def get_fallback_chain(capability: str, category: str = None) -> list[DataSourceSpec]:
    """获取指定能力的降级链（按优先级排序的全部活跃源）

    返回完整的 DataSourceSpec 对象列表（非仅 index entry），
    按 priority 升序排列。
    """
    registry = _get_registry()
    matches = registry.list_sources(category=category, capability=capability)
    matches.sort(key=lambda x: (x.get("priority", 10), x.get("source_id", "")))

    result = []
    for m in matches:
        spec = registry.get_source(m["source_id"])
        if spec:
            result.append(spec)

    return result
