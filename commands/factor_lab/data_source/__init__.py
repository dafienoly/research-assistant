"""Data Source Registry V5.0 — 数据源注册表

Centralized catalog of all available data sources, their capabilities,
priority, health status, and configuration. Foundation for V5.x data
pipeline (V5.1: Provider, V5.2: Realtime Quote Ingest, V5.4: Quality Gate,
V5.5: No-Fallback, V5.6: Lineage).
"""

from factor_lab.data_source.spec import DataSourceSpec, DataSourceCategory, DataSourceCapability, DataSourceStatus
from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.health import HealthTracker, HealthReport
from factor_lab.data_source.discovery import resolve_source, list_capable, get_fallback_chain

# V5.2 — Realtime Quote Ingest
from factor_lab.data_source.quote import Quote, QuoteResult, BatchQuoteResult
from factor_lab.data_source.adapters import (
    QuoteAdapter,
    EastmoneyQuoteAdapter,
    RsscastQuoteAdapter,
    TencentQuoteAdapter,
    SinaQuoteAdapter,
    get_adapter,
    list_adapters,
)
from factor_lab.data_source.ingest import RealtimeQuoteEngine

__all__ = [
    # V5.0
    "DataSourceSpec", "DataSourceCategory", "DataSourceCapability", "DataSourceStatus",
    "DataRegistry",
    "HealthTracker", "HealthReport",
    "resolve_source", "list_capable", "get_fallback_chain",
    # V5.2
    "Quote", "QuoteResult", "BatchQuoteResult",
    "QuoteAdapter",
    "EastmoneyQuoteAdapter", "RsscastQuoteAdapter",
    "TencentQuoteAdapter", "SinaQuoteAdapter",
    "get_adapter", "list_adapters",
    "RealtimeQuoteEngine",
]
