"""Adapters — 行情提供者适配器

Each adapter wraps an existing provider (eastmoney_direct, rsscast_mcp,
provider_matrix, etc.) and normalises its output to a standardised
dict format that the RealtimeQuoteEngine converts to Quote objects.

Adapter contract:
  fetch(symbols: list[str]) -> dict[str, dict]

  Returns a dict keyed by 6-digit symbol code, where each value is a
  normalised dict with the canonical fields:
    symbol, name, price, open, high, low, volume, amount,
    change_pct, change_amount, prev_close, amplitude, turnover_rate

  On complete failure returns {} — individual missing symbols within an
  otherwise successful batch are simply absent from the dict.
"""

from __future__ import annotations

import time
import re
from abc import ABC, abstractmethod
from typing import Optional


# =========================================================================
# Base adapter
# =========================================================================

class QuoteAdapter(ABC):
    """行情适配器基类"""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """数据源ID，对应 DataSourceSpec.source_id"""
        ...

    @abstractmethod
    def fetch(self, symbols: list[str]) -> dict[str, dict]:
        """获取并规范化行情数据

        Args:
            symbols: 6位股票代码列表

        Returns:
            dict[symbol -> normalised dict]  空dict = 完全失败
        """
        ...


def _normalise_code(code: str) -> str:
    """提取6位数字代码"""
    digits = re.sub(r"\D", "", str(code or ""))
    return digits[-6:] if len(digits) >= 6 else ""


# =========================================================================
# Eastmoney adapter
# =========================================================================

class EastmoneyQuoteAdapter(QuoteAdapter):
    """Eastmoney Direct 实时行情适配器"""

    def __init__(self):
        self._provider = None  # lazy import

    @property
    def provider_id(self) -> str:
        return "eastmoney_direct"

    def _get_provider(self):
        if self._provider is None:
            from eastmoney_direct import EastmoneyProvider
            self._provider = EastmoneyProvider()
        return self._provider

    def fetch(self, symbols: list[str]) -> dict[str, dict]:
        t0 = time.time()
        provider = self._get_provider()
        try:
            raw = provider.get_quotes(symbols)
        except Exception:
            return {}
        elapsed = (time.time() - t0) * 1000

        result = {}
        for code, data in raw.items():
            normalised = _normalise_code(code)
            if not normalised:
                continue
            result[normalised] = {
                "symbol": normalised,
                "name": data.get("name", ""),
                "price": data.get("price"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "volume": data.get("volume"),
                "amount": data.get("amount"),
                "change_pct": data.get("change_pct"),
                "change_amount": data.get("change_amount"),
                "prev_close": None,
                "amplitude": None,
                "turnover_rate": None,
                "source_id": self.provider_id,
                "_latency_ms": round(elapsed, 1),
            }
        return result


# =========================================================================
# RSScast adapter
# =========================================================================

class RsscastQuoteAdapter(QuoteAdapter):
    """RSScast MCP 实时行情适配器"""

    def __init__(self):
        self._provider = None

    @property
    def provider_id(self) -> str:
        return "rsscast_mcp"

    def _get_provider(self):
        if self._provider is None:
            from provider_matrix import RSScastProvider
            self._provider = RSScastProvider()
        return self._provider

    def fetch(self, symbols: list[str]) -> dict[str, dict]:
        t0 = time.time()
        provider = self._get_provider()
        try:
            raw = provider.get_quotes(symbols)
        except Exception:
            return {}
        elapsed = (time.time() - t0) * 1000

        result = {}
        for code, data in raw.items():
            normalised = _normalise_code(code)
            if not normalised:
                continue
            result[normalised] = {
                "symbol": normalised,
                "name": data.get("name", ""),
                "price": data.get("price"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "volume": data.get("volume"),
                "amount": data.get("amount"),
                "change_pct": data.get("change_pct"),
                "change_amount": data.get("change_amount"),
                "prev_close": data.get("prev_close"),
                "amplitude": data.get("amplitude"),
                "turnover_rate": data.get("turnover_rate"),
                "source_id": self.provider_id,
                "_latency_ms": round(elapsed, 1),
            }
        return result


# =========================================================================
# Tencent adapter
# =========================================================================

class TencentQuoteAdapter(QuoteAdapter):
    """Tencent qt.gtimg.cn 实时行情适配器"""

    def __init__(self):
        self._provider = None

    @property
    def provider_id(self) -> str:
        return "tencent_qt"

    def _get_provider(self):
        if self._provider is None:
            from provider_matrix import TencentProvider
            self._provider = TencentProvider()
        return self._provider

    def fetch(self, symbols: list[str]) -> dict[str, dict]:
        t0 = time.time()
        provider = self._get_provider()
        try:
            raw = provider.get_quotes(symbols)
        except Exception:
            return {}
        elapsed = (time.time() - t0) * 1000

        result = {}
        for code, data in raw.items():
            normalised = _normalise_code(code)
            if not normalised:
                continue
            result[normalised] = {
                "symbol": normalised,
                "name": data.get("name", ""),
                "price": data.get("price"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "volume": data.get("volume"),
                "amount": data.get("amount"),
                "change_pct": data.get("change_pct"),
                "change_amount": data.get("change_amount") if "change_amount" in data else None,
                "prev_close": data.get("prev_close"),
                "amplitude": data.get("amplitude"),
                "turnover_rate": data.get("turnover_rate"),
                "source_id": self.provider_id,
                "_latency_ms": round(elapsed, 1),
            }
        return result


# =========================================================================
# Sina adapter
# =========================================================================

class SinaQuoteAdapter(QuoteAdapter):
    """Sina hq.sinajs.cn 实时行情适配器"""

    def __init__(self):
        self._provider = None

    @property
    def provider_id(self) -> str:
        return "sina"

    def _get_provider(self):
        if self._provider is None:
            from provider_matrix import SinaProvider
            self._provider = SinaProvider()
        return self._provider

    def fetch(self, symbols: list[str]) -> dict[str, dict]:
        t0 = time.time()
        provider = self._get_provider()
        try:
            raw = provider.get_quotes(symbols)
        except Exception:
            return {}
        elapsed = (time.time() - t0) * 1000

        result = {}
        for code, data in raw.items():
            normalised = _normalise_code(code)
            if not normalised:
                continue
            result[normalised] = {
                "symbol": normalised,
                "name": data.get("name", ""),
                "price": data.get("price"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "volume": data.get("volume"),
                "amount": data.get("amount"),
                "change_pct": data.get("change_pct"),
                "change_amount": data.get("change_amount") if "change_amount" in data else None,
                "prev_close": data.get("prev_close"),
                "amplitude": None,
                "turnover_rate": None,
                "source_id": self.provider_id,
                "_latency_ms": round(elapsed, 1),
            }
        return result


# =========================================================================
# Adapter registry
# =========================================================================

def _discover_adapters() -> dict[str, QuoteAdapter]:
    """构建 source_id → adapter 映射"""
    adapters: dict[str, QuoteAdapter] = {}
    for cls in (EastmoneyQuoteAdapter, RsscastQuoteAdapter,
                TencentQuoteAdapter, SinaQuoteAdapter):
        instance = cls()
        adapters[instance.provider_id] = instance
    return adapters


# Singleton cache
_ADAPTERS: Optional[dict[str, QuoteAdapter]] = None


def get_adapter(source_id: str) -> Optional[QuoteAdapter]:
    """获取指定数据源的适配器"""
    global _ADAPTERS
    if _ADAPTERS is None:
        _ADAPTERS = _discover_adapters()
    return _ADAPTERS.get(source_id)


def list_adapters() -> list[str]:
    """列出所有已注册的适配器ID"""
    global _ADAPTERS
    if _ADAPTERS is None:
        _ADAPTERS = _discover_adapters()
    return list(_ADAPTERS.keys())
