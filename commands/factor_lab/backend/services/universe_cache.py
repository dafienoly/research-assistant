"""Thread‑safe in‑memory cache for universe (U0–U4 + ETF) data.

Provides a singleton UniverseCache with configurable TTL (default 1 hour).
Designed to prevent the /api/universe endpoint from blocking the event loop
while build_all() runs (~120s of synchronous Tushare calls).
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Dict, Optional


class UniverseCache:
    """In‑memory universe data cache with TTL expiry.

    Thread‑safe via ``threading.Lock``.  All public methods acquire the lock
    so that background rebuilds and concurrent reads don't race.

    Attributes
    ----------
    ttl_seconds : int
        How long cached data is considered fresh (default 3600 = 1 hour).
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None  # None=empty, {} is valid data
        self._timestamp: Optional[float] = None  # time.time() when _cache was set
        self._ttl = ttl_seconds

    # ── public API ──────────────────────────────────────────────────────

    def get(self) -> Optional[Dict[str, Any]]:
        """Return a **deep copy** of the cached universe data, or *None*."""
        with self._lock:
            if self._cache is None:
                return None
            return copy.deepcopy(self._cache)

    def set(self, data: Dict[str, Any]) -> None:
        """Replace the cache contents and reset the timestamp to now."""
        with self._lock:
            self._cache = dict(data)  # shallow copy is fine – we never mutate
            self._timestamp = time.time()

    def invalidate(self) -> None:
        """Clear the cache.  The next ``get()`` will return *None*."""
        with self._lock:
            self._cache = None
            self._timestamp = None

    def is_fresh(self) -> bool:
        """*True* when the cache is populated and its age < *ttl_seconds*."""
        with self._lock:
            if self._timestamp is None:
                return False
            return (time.time() - self._timestamp) < self._ttl

    @property
    def age_seconds(self) -> Optional[float]:
        """Seconds since the cache was last set, or *None* if empty."""
        with self._lock:
            if self._timestamp is None:
                return None
            return time.time() - self._timestamp

    @property
    def built_at(self) -> Optional[str]:
        """The ``built_at`` timestamp from the cached ``meta`` dict, if any."""
        with self._lock:
            if self._cache is None:
                return None
            meta = self._cache.get("meta", {})
            return meta.get("built_at") if isinstance(meta, dict) else None

    # ── internal helpers (caller MUST hold the lock) ─────────────────────


# ══════════════════════════════════════════════════════════════════════════
# Singleton helpers
# ══════════════════════════════════════════════════════════════════════════

_CACHE_SINGLETON: Optional[UniverseCache] = None
_SINGLETON_LOCK = threading.Lock()


def get_cache() -> UniverseCache:
    """Return the application‑wide ``UniverseCache`` singleton."""
    global _CACHE_SINGLETON
    if _CACHE_SINGLETON is None:
        with _SINGLETON_LOCK:
            if _CACHE_SINGLETON is None:
                _CACHE_SINGLETON = UniverseCache()
    return _CACHE_SINGLETON


def reset_cache() -> None:
    """Replace the singleton with a fresh empty cache (useful in tests)."""
    global _CACHE_SINGLETON
    with _SINGLETON_LOCK:
        _CACHE_SINGLETON = UniverseCache()
