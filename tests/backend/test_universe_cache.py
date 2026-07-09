#!/usr/bin/env python3
"""Tests for ``backend.services.universe_cache`` — thread‑safe UniverseCache."""

from __future__ import annotations

import sys
import os
import time
import threading
from pathlib import Path
from typing import Any

import pytest

# 确保项目根目录在 sys.path 上
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from factor_lab.backend.services.universe_cache import UniverseCache, get_cache, reset_cache

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def clear_global_cache():
    """每次测试前重置全局单例，避免跨测试污染。"""
    reset_cache()
    yield
    reset_cache()


@pytest.fixture()
def cache() -> UniverseCache:
    """返回一个 TTL 极短的缓存实例（便于测试过期）。"""
    return UniverseCache(ttl_seconds=1)  # 1 秒过期


@pytest.fixture()
def sample_data() -> dict[str, Any]:
    """模拟 build_all() 返回数据。"""
    return {
        "meta": {
            "version": "4.1",
            "built_at": "2026-07-09T12:00:00+08:00",
            "description": "V4.1 分层股票池",
        },
        "universes": {
            "U0": {"name": "U0", "label": "全A基础池", "total_stocks": 5000, "stocks": []},
            "U1": {"name": "U1", "label": "用户可交易池", "total_stocks": 4500, "stocks": []},
            "U2": {"name": "U2", "label": "AI/半导体广义池", "total_stocks": 315, "stocks": []},
            "U3": {"name": "U3", "label": "半导体核心池", "total_stocks": 200, "stocks": []},
            "U4": {"name": "U4", "label": "匹配对照池", "total_stocks": 100, "stocks": []},
            "ETF": {"name": "ETF", "label": "ETF替代池", "total_stocks": 15, "stocks": []},
        },
    }


# =========================================================================
# 基础功能测试
# =========================================================================


class TestUniverseCacheBasic:
    """UniverseCache 基础功能。"""

    def test_initial_state_is_empty(self, cache: UniverseCache):
        """新建缓存为空。"""
        assert cache.get() is None
        assert cache.age_seconds is None
        assert cache.built_at is None
        assert cache.is_fresh() is False

    def test_set_and_get(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """set 后 get 返回数据的副本。"""
        cache.set(sample_data)
        retrieved = cache.get()
        assert retrieved is not None
        assert retrieved["meta"]["version"] == "4.1"
        assert "U0" in retrieved["universes"]
        assert "U1" in retrieved["universes"]
        assert "U2" in retrieved["universes"]
        assert "U3" in retrieved["universes"]
        assert "U4" in retrieved["universes"]
        assert "ETF" in retrieved["universes"]

    def test_get_returns_copy(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """get 返回的是副本，修改不影响内部缓存。"""
        cache.set(sample_data)
        retrieved = cache.get()
        assert retrieved is not None
        retrieved["universes"]["U0"]["total_stocks"] = 9999

        # 内部数据不受影响
        second = cache.get()
        assert second is not None
        assert second["universes"]["U0"]["total_stocks"] == 5000

    def test_invalidate(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """invalidate 后 get 返回 None。"""
        cache.set(sample_data)
        assert cache.get() is not None

        cache.invalidate()
        assert cache.get() is None
        assert cache.age_seconds is None
        assert cache.built_at is None

    def test_built_at_from_meta(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """built_at 从 data['meta']['built_at'] 读取。"""
        cache.set(sample_data)
        assert cache.built_at == "2026-07-09T12:00:00+08:00"

    def test_built_at_none_when_empty(self, cache: UniverseCache):
        """空缓存时 built_at 为 None。"""
        assert cache.built_at is None


# =========================================================================
# TTL / 新鲜度测试
# =========================================================================


class TestUniverseFreshness:
    """TTL 和新鲜度判断。"""

    def test_is_fresh_after_set(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """set 后立即 is_fresh() 返回 True。"""
        cache.set(sample_data)
        assert cache.is_fresh() is True

    def test_is_not_fresh_after_ttl(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """超过 TTL 后 is_fresh() 返回 False。"""
        cache.set(sample_data)
        time.sleep(1.1)  # TTL = 1s
        assert cache.is_fresh() is False

    def test_age_seconds_increases(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """age_seconds 随时间增长。"""
        cache.set(sample_data)
        age1 = cache.age_seconds
        assert age1 is not None and age1 < 0.1

        time.sleep(0.5)
        age2 = cache.age_seconds
        assert age2 is not None and age2 >= 0.4

    def test_default_ttl_is_one_hour(self):
        """默认 TTL 为 3600 秒。"""
        c = UniverseCache()
        assert c._ttl == 3600

    def test_custom_ttl(self):
        """可以设置自定义 TTL。"""
        c = UniverseCache(ttl_seconds=300)
        assert c._ttl == 300


# =========================================================================
# 线程安全测试
# =========================================================================


class TestThreadSafety:
    """并发读写时的线程安全。"""

    def test_concurrent_set_and_get(self, sample_data: dict[str, Any]):
        """多个线程同时 set/get 不崩溃。"""
        c = UniverseCache()
        errors: list[Exception] = []

        def writer(n: int):
            try:
                for _ in range(20):
                    data = dict(sample_data)
                    data["meta"]["built_at"] = f"2026-07-09T{12+n:02d}:00:00+08:00"
                    data["universes"]["U0"]["total_stocks"] = 5000 + n
                    c.set(data)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    _ = c.get()
                    _ = c.is_fresh()
                    _ = c.age_seconds
                    _ = c.built_at
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(i,))
            for i in range(4)
        ] + [
            threading.Thread(target=reader)
            for _ in range(4)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"线程测试出现异常: {errors}"

    def test_concurrent_get_returns_consistent(self, cache: UniverseCache, sample_data: dict[str, Any]):
        """get 返回的数据结构完整且一致。"""
        cache.set(sample_data)
        results: list[dict] = []
        lock = threading.Lock()

        def reader():
            data = cache.get()
            if data is not None:
                with lock:
                    results.append(data)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        # 所有读者看到一致的数据
        for r in results:
            assert r["meta"]["version"] == "4.1"
            assert set(r["universes"].keys()) == {"U0", "U1", "U2", "U3", "U4", "ETF"}

    def test_lock_is_reentrant(self):
        """测试 Lock 正常运作（非可重入但能安全释放）。"""
        c = UniverseCache()
        c.set({"meta": {"built_at": "t"}, "universes": {"U0": {}}})
        # 连续 get 不应死锁
        for _ in range(100):
            assert c.get() is not None
        assert c.is_fresh() is True


# =========================================================================
# Singleton 测试
# =========================================================================


class TestSingleton:
    """get_cache / reset_cache 单例行为。"""

    def test_get_cache_returns_same_instance(self):
        """get_cache 返回同一实例。"""
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2

    def test_reset_cache_creates_new_instance(self):
        """reset_cache 后 get_cache 返回新实例。"""
        c1 = get_cache()
        reset_cache()
        c2 = get_cache()
        assert c1 is not c2

    def test_reset_cache_clears_data(self, sample_data: dict[str, Any]):
        """reset_cache 后缓存数据清空。"""
        c = get_cache()
        c.set(sample_data)
        assert c.get() is not None

        reset_cache()
        c2 = get_cache()
        assert c2.get() is None


# =========================================================================
# 边界条件
# =========================================================================


class TestEdgeCases:
    """边界条件测试。"""

    def test_set_empty_data(self, cache: UniverseCache):
        """set 空字典后 get 返回非 None 但空。"""
        cache.set({})
        assert cache.get() == {}

    def test_set_none_value(self, cache: UniverseCache):
        """set 含 None 的数据不应崩溃。"""
        cache.set({"key": None, "universes": None})
        retrieved = cache.get()
        assert retrieved is not None
        assert retrieved["key"] is None

    def test_multiple_set_cycles(self, cache: UniverseCache):
        """多次 set 后取到的是最新数据。"""
        for i in range(5):
            cache.set({"meta": {"built_at": f"cycle_{i}"}, "universes": {}})
        retrieved = cache.get()
        assert retrieved is not None
        assert retrieved["meta"]["built_at"] == "cycle_4"

    def test_large_data_does_not_block(self):
        """大数据量下 set/get 不显著阻塞。"""
        c = UniverseCache()
        large_data = {
            "meta": {"built_at": "test"},
            "universes": {
                f"U{i}": {"stocks": [{"ts_code": f"{j:06d}.SH"} for j in range(500)]}
                for i in range(6)
            },
        }
        start = time.perf_counter()
        c.set(large_data)
        retrieved = c.get()
        elapsed = time.perf_counter() - start

        assert retrieved is not None
        assert elapsed < 1.0  # 远小于 1 秒
