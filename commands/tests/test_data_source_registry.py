"""V5.0 Data Source Registry — Tests

Covers:
  - DataSourceSpec creation and validation
  - Registry CRUD (register, list, get, update, delete)
  - Preferred source resolution
  - Seed defaults
  - Health tracking and status transitions
  - Discovery API (resolve, fallback chain)
  - Persistence across reloads
  - Edge cases (empty registry, unknown source, invalid inputs)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from factor_lab.data_source.spec import (
    DataSourceSpec, DataSourceCategory, DataSourceCapability, DataSourceStatus,
    validate_spec, VALID_CATEGORIES, VALID_CAPABILITIES, VALID_STATUSES,
)
from factor_lab.data_source.registry import DataRegistry, DEFAULT_SOURCES
from factor_lab.data_source.health import HealthTracker, HealthReport
from factor_lab.data_source.discovery import resolve_source, list_capable, get_fallback_chain

CST = timezone(timedelta(hours=8))


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def isolated_registry(monkeypatch, tmp_path):
    """将注册表根目录重定向到临时目录"""
    from factor_lab.data_source import registry as reg_mod
    from factor_lab.data_source import health as hlth_mod

    test_root = tmp_path / "data_source_registry"
    monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
    monkeypatch.setattr(hlth_mod, "REGISTRY_ROOT", test_root)
    yield DataRegistry()


@pytest.fixture()
def seeded_registry(isolated_registry):
    """预填充种子数据的注册表"""
    isolated_registry.seed_defaults()
    return isolated_registry


# =========================================================================
# Spec Tests
# =========================================================================

def test_spec_create_minimal():
    """最小规格创建"""
    spec = DataSourceSpec(source_id="test_source", name="Test Source")
    assert spec.source_id == "test_source"
    assert spec.name == "Test Source"
    assert spec.category == "market"
    assert spec.capabilities == ["realtime_quote"]
    assert spec.status == "unchecked"
    assert spec.priority == 10
    assert spec.created_at != ""
    assert spec.updated_at != ""


def test_spec_create_full():
    """完整规格创建"""
    spec = DataSourceSpec(
        source_id="my_provider",
        name="My Provider",
        category="fundamental",
        capabilities=["kline_daily", "kline_minute", "fundamental"],
        priority=1,
        status="active",
        config={"api_key": "test"},
    )
    assert spec.source_id == "my_provider"
    assert spec.category == "fundamental"
    assert "kline_daily" in spec.capabilities
    assert spec.priority == 1
    assert spec.status == "active"


def test_spec_to_from_dict():
    """序列化与反序列化"""
    spec = DataSourceSpec(
        source_id="roundtrip",
        name="Round Trip",
        category="event",
        capabilities=["announcement"],
        priority=5,
        config={"url": "http://test"},
    )
    d = spec.to_dict()
    assert d["source_id"] == "roundtrip"
    assert d["category"] == "event"

    restored = DataSourceSpec.from_dict(d)
    assert restored.source_id == spec.source_id
    assert restored.name == spec.name
    assert restored.category == spec.category
    assert restored.priority == spec.priority
    assert restored.config == spec.config


def test_validate_spec_valid():
    """合法 spec 通过验证"""
    spec = DataSourceSpec(source_id="valid", name="Valid Source")
    errors = validate_spec(spec)
    assert errors == []


def test_validate_spec_missing_id():
    """缺少 source_id 报错"""
    spec = DataSourceSpec(source_id="", name="No ID")
    errors = validate_spec(spec)
    assert len(errors) >= 1
    assert any("source_id" in e for e in errors)


def test_validate_spec_missing_name():
    """缺少 name 报错"""
    spec = DataSourceSpec(source_id="no_name", name="")
    errors = validate_spec(spec)
    assert len(errors) >= 1
    assert any("name" in e for e in errors)


def test_validate_spec_invalid_category():
    """非法分类报错"""
    spec = DataSourceSpec(source_id="bad_cat", name="Bad", category="unknown")
    errors = validate_spec(spec)
    assert any("category" in e for e in errors)


def test_validate_spec_invalid_capability():
    """非法能力报错"""
    spec = DataSourceSpec(source_id="bad_cap", name="Bad", capabilities=["invalid_cap"])
    errors = validate_spec(spec)
    assert any("capability" in e for e in errors)


def test_validate_spec_invalid_status():
    """非法状态报错"""
    spec = DataSourceSpec(source_id="bad_st", name="Bad", status="unknown")
    errors = validate_spec(spec)
    assert any("status" in e for e in errors)


def test_validate_spec_negative_priority():
    """负优先级报错"""
    spec = DataSourceSpec(source_id="neg", name="Negative", priority=-1)
    errors = validate_spec(spec)
    assert any("priority" in e for e in errors)


# =========================================================================
# Registry CRUD Tests
# =========================================================================

def test_registry_register(isolated_registry):
    """注册新数据源"""
    spec = DataSourceSpec(source_id="test_reg", name="Test Register", priority=3)
    result = isolated_registry.register(spec)
    assert result["status"] == "registered"
    assert result["source_id"] == "test_reg"


def test_registry_register_invalid(isolated_registry):
    """无效 spec 注册失败"""
    spec = DataSourceSpec(source_id="", name="")
    result = isolated_registry.register(spec)
    assert result["status"] == "error"
    assert "errors" in result


def test_registry_list(isolated_registry):
    """列出数据源"""
    s1 = DataSourceSpec(source_id="src_a", name="Source A", category="market")
    s2 = DataSourceSpec(source_id="src_b", name="Source B", category="fundamental")
    isolated_registry.register(s1)
    isolated_registry.register(s2)

    all_sources = isolated_registry.list_sources()
    assert len(all_sources) == 2


def test_registry_list_filter_category(isolated_registry):
    """按分类筛选"""
    s1 = DataSourceSpec(source_id="src_a", name="Source A", category="market")
    s2 = DataSourceSpec(source_id="src_b", name="Source B", category="fundamental")
    isolated_registry.register(s1)
    isolated_registry.register(s2)

    market_sources = isolated_registry.list_sources(category="market")
    assert len(market_sources) == 1
    assert market_sources[0]["source_id"] == "src_a"


def test_registry_list_filter_capability(isolated_registry):
    """按能力筛选"""
    s1 = DataSourceSpec(source_id="src_a", name="Source A",
                        capabilities=["realtime_quote"])
    s2 = DataSourceSpec(source_id="src_b", name="Source B",
                        capabilities=["kline_daily"])
    isolated_registry.register(s1)
    isolated_registry.register(s2)

    capable = isolated_registry.list_sources(capability="kline_daily")
    assert len(capable) == 1
    assert capable[0]["source_id"] == "src_b"


def test_registry_list_filter_status(isolated_registry):
    """按状态筛选"""
    s1 = DataSourceSpec(source_id="src_a", name="Source A", status="active")
    s2 = DataSourceSpec(source_id="src_b", name="Source B", status="inactive")
    isolated_registry.register(s1)
    isolated_registry.register(s2)

    active = isolated_registry.list_sources(status="active")
    assert len(active) == 1


def test_registry_get_source(isolated_registry):
    """获取完整 spec"""
    spec = DataSourceSpec(source_id="get_test", name="Get Test")
    isolated_registry.register(spec)

    fetched = isolated_registry.get_source("get_test")
    assert fetched is not None
    assert fetched.source_id == "get_test"
    assert fetched.name == "Get Test"


def test_registry_get_source_not_found(isolated_registry):
    """获取不存在的源返回 None"""
    fetched = isolated_registry.get_source("nonexistent")
    assert fetched is None


def test_registry_get_preferred(isolated_registry):
    """最高优先级活跃源"""
    s1 = DataSourceSpec(source_id="high_pri", name="High Priority",
                        category="market", capabilities=["realtime_quote"],
                        priority=1, status="active")
    s2 = DataSourceSpec(source_id="low_pri", name="Low Priority",
                        category="market", capabilities=["realtime_quote"],
                        priority=10, status="active")
    isolated_registry.register(s1)
    isolated_registry.register(s2)

    preferred = isolated_registry.get_preferred(capability="realtime_quote")
    assert preferred is not None
    assert preferred.source_id == "high_pri"


def test_registry_get_preferred_only_active(isolated_registry):
    """仅考虑 active/unchecked 源"""
    s1 = DataSourceSpec(source_id="inactive_src", name="Inactive",
                        category="market", capabilities=["realtime_quote"],
                        priority=1, status="inactive")
    s2 = DataSourceSpec(source_id="active_src", name="Active",
                        category="market", capabilities=["realtime_quote"],
                        priority=5, status="active")
    isolated_registry.register(s1)
    isolated_registry.register(s2)

    preferred = isolated_registry.get_preferred(capability="realtime_quote")
    assert preferred is not None
    assert preferred.source_id == "active_src"


def test_registry_get_preferred_none(isolated_registry):
    """无匹配源返回 None"""
    preferred = isolated_registry.get_preferred(capability="nonexistent")
    assert preferred is None


def test_registry_update_status(isolated_registry):
    """更新状态"""
    spec = DataSourceSpec(source_id="status_test", name="Status Test")
    isolated_registry.register(spec)

    result = isolated_registry.update_status("status_test", "active")
    assert result["status"] == "updated"
    assert result["new_status"] == "active"

    fetched = isolated_registry.get_source("status_test")
    assert fetched.status == "active"


def test_registry_update_status_invalid(isolated_registry):
    """非法状态更新被拒绝"""
    spec = DataSourceSpec(source_id="bad_st", name="Bad")
    isolated_registry.register(spec)

    result = isolated_registry.update_status("bad_st", "invalid_status")
    assert result["status"] == "error"


def test_registry_delete_source(isolated_registry):
    """删除数据源"""
    spec = DataSourceSpec(source_id="delete_me", name="Delete Me")
    isolated_registry.register(spec)
    assert isolated_registry.get_source("delete_me") is not None

    result = isolated_registry.delete_source("delete_me")
    assert result["status"] == "deleted"
    assert isolated_registry.get_source("delete_me") is None


def test_registry_delete_not_found(isolated_registry):
    """删除不存在的源报错"""
    result = isolated_registry.delete_source("nonexistent")
    assert result["status"] == "error"


def test_registry_update_register(isolated_registry):
    """重新注册覆盖已有源"""
    s1 = DataSourceSpec(source_id="update_src", name="Original", priority=10)
    isolated_registry.register(s1)
    s2 = DataSourceSpec(source_id="update_src", name="Updated", priority=5)
    isolated_registry.register(s2)

    fetched = isolated_registry.get_source("update_src")
    assert fetched.name == "Updated"
    assert fetched.priority == 5

    # Index should have only one entry
    all_sources = isolated_registry.list_sources()
    assert len(all_sources) == 1


# =========================================================================
# Seed Tests
# =========================================================================

def test_seed_defaults(isolated_registry):
    """种子数据注册"""
    count = isolated_registry.seed_defaults()
    assert count == len(DEFAULT_SOURCES)

    all_sources = isolated_registry.list_sources()
    assert len(all_sources) == len(DEFAULT_SOURCES)


def test_seed_contains_expected(isolated_registry):
    """种子包含已知数据源"""
    isolated_registry.seed_defaults()

    ids = {s["source_id"] for s in isolated_registry.list_sources()}
    assert "rsscast_mcp" in ids
    assert "akshare_spot" in ids
    assert "tencent_qt" in ids
    assert "sina" in ids
    assert "baostock" in ids
    assert "announcement" in ids
    assert "eastmoney_direct" in ids


def test_is_seeded_after_seed(isolated_registry):
    """种子化后 is_seeded 返回 True"""
    assert isolated_registry.is_seeded() is False
    isolated_registry.seed_defaults()
    assert isolated_registry.is_seeded() is True


def test_seed_is_idempotent(isolated_registry):
    """多次种子化幂等"""
    isolated_registry.seed_defaults()
    count1 = len(isolated_registry.list_sources())
    isolated_registry.seed_defaults()
    count2 = len(isolated_registry.list_sources())
    assert count1 == count2


# =========================================================================
# Persistence Tests
# =========================================================================

def test_persistence_across_reload(isolated_registry):
    """注册表跨重载持久化"""
    import importlib

    isolated_registry.seed_defaults()

    # Create a new registry instance pointing to same test dir
    r2 = DataRegistry()
    all_sources = r2.list_sources()
    assert len(all_sources) == len(DEFAULT_SOURCES)

    spec = r2.get_source("rsscast_mcp")
    assert spec is not None
    assert spec.name == "RSScast MCP 主数据源"


# =========================================================================
# Health Tests
# =========================================================================

def test_health_record_and_check(isolated_registry):
    """健康记录与检查"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    tracker.record_call("rsscast_mcp", success=True, latency_ms=150)
    tracker.record_call("rsscast_mcp", success=True, latency_ms=200)
    tracker.record_call("rsscast_mcp", success=False, latency_ms=0, error="timeout")

    report = tracker.check_health("rsscast_mcp")
    assert report.source_id == "rsscast_mcp"
    assert report.total_calls == 3
    assert report.error_count == 1
    assert report.success_rate == pytest.approx(66.7, abs=0.1)
    assert report.status == "degraded"  # 66.7% is in 50-80 range


def test_health_active_threshold(isolated_registry):
    """高成功率 → active"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    for _ in range(20):
        tracker.record_call("rsscast_mcp", success=True, latency_ms=100)

    report = tracker.check_health("rsscast_mcp")
    assert report.status == "active"
    assert report.success_rate == 100.0


def test_health_inactive_threshold(isolated_registry):
    """低成功率 → inactive"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    for _ in range(10):
        tracker.record_call("rsscast_mcp", success=False, error="failed")

    report = tracker.check_health("rsscast_mcp")
    assert report.status == "inactive"
    assert report.error_count == 10


def test_health_unchecked(isolated_registry):
    """无记录 → unchecked"""
    tracker = HealthTracker(isolated_registry)
    report = tracker.check_health("unknown_source")
    assert report.status == "unchecked"
    assert report.total_calls == 0


def test_health_auto_updates_status(isolated_registry):
    """健康检查自动更新注册表状态"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    # Record failures
    for _ in range(10):
        tracker.record_call("rsscast_mcp", success=False, error="timeout")

    tracker.check_health("rsscast_mcp")
    spec = isolated_registry.get_source("rsscast_mcp")
    assert spec.status == "inactive"


def test_health_avg_latency(isolated_registry):
    """平均延迟计算"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    tracker.record_call("rsscast_mcp", success=True, latency_ms=100)
    tracker.record_call("rsscast_mcp", success=True, latency_ms=200)
    tracker.record_call("rsscast_mcp", success=False, latency_ms=0, error="err")

    report = tracker.check_health("rsscast_mcp")
    # avg_latency only counts successful calls with positive latency
    assert report.avg_latency_ms == 150.0


def test_health_recent_errors(isolated_registry):
    """最近错误记录"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    for i in range(15):
        tracker.record_call("rsscast_mcp", success=False, error=f"error_{i}")

    report = tracker.check_health("rsscast_mcp")
    assert len(report.recent_errors) <= 5
    assert all("error_" in e for e in report.recent_errors)


def test_health_rolling_window(isolated_registry):
    """仅使用最近 ROLLING_WINDOW 条记录"""
    isolated_registry.seed_defaults()
    tracker = HealthTracker(isolated_registry)

    # 200 records: first 100 all failures, next 100 all successes
    for _ in range(100):
        tracker.record_call("rsscast_mcp", success=False, error="fail")
    for _ in range(100):
        tracker.record_call("rsscast_mcp", success=True, latency_ms=50)

    report = tracker.check_health("rsscast_mcp")
    # Should only see the last 100 (all successes)
    assert report.total_calls == 100
    assert report.success_rate == 100.0


# =========================================================================
# Discovery Tests
# =========================================================================

def test_discovery_resolve_source(seeded_registry):
    """resolve_source 返回最佳源"""
    result = resolve_source("realtime_quote")
    assert result is not None
    assert result.source_id == "rsscast_mcp"


def test_discovery_resolve_with_preferred(seeded_registry):
    """resolve_source 优先使用 preferred"""
    result = resolve_source("realtime_quote", preferred="tencent_qt")
    assert result is not None
    assert result.source_id == "tencent_qt"


def test_discovery_resolve_preferred_not_capable(seeded_registry):
    """preferred 不具备能力时回退"""
    # announcement can't do realtime_quote, so should fall back to rsscast_mcp
    result = resolve_source("realtime_quote", preferred="announcement")
    assert result is not None
    assert result.source_id != "announcement"


def test_discovery_list_capable(seeded_registry):
    """list_capable 列出具备能力的源"""
    capable = list_capable("kline_daily")
    assert len(capable) >= 4  # rsscast, eastmoney, tencent, baostock
    ids = {c["source_id"] for c in capable}
    assert "rsscast_mcp" in ids


def test_discovery_fallback_chain(seeded_registry):
    """fallback 链按优先级排列"""
    chain = get_fallback_chain("realtime_quote")
    assert len(chain) >= 3
    # rsscast has priority 1, eastmoney 2, tencent 3
    priorities = [s.priority for s in chain]
    assert priorities == sorted(priorities)


def test_discovery_no_match(isolated_registry):
    """无匹配返回 None/空"""
    result = resolve_source("nonexistent_capability")
    assert result is None

    capable = list_capable("nonexistent_capability")
    assert capable == []

    chain = get_fallback_chain("nonexistent_capability")
    assert chain == []


# =========================================================================
# Edge Cases
# =========================================================================

def test_empty_registry(isolated_registry):
    """空注册表行为"""
    assert isolated_registry.list_sources() == []
    assert isolated_registry.get_source("anything") is None
    assert isolated_registry.get_preferred("realtime_quote") is None


def test_register_with_extra_fields(isolated_registry):
    """带额外字段的 spec 注册"""
    spec = DataSourceSpec(source_id="extra", name="Extra Fields",
                          config={"custom": "value", "host": "localhost", "port": 8080})
    result = isolated_registry.register(spec)
    assert result["status"] == "registered"

    fetched = isolated_registry.get_source("extra")
    assert fetched.config["custom"] == "value"


def test_get_preferred_with_category(seeded_registry):
    """带分类的 preferred 查询"""
    # fundamental category should return baostock
    result = seeded_registry.get_preferred(capability="fundamental", category="fundamental")
    assert result is not None
    assert result.source_id == "baostock"


def test_health_record_for_unknown_source(isolated_registry):
    """从未注册的源记录健康"""
    tracker = HealthTracker(isolated_registry)
    # Should not crash
    tracker.record_call("unknown", success=True)
    report = tracker.check_health("unknown")
    assert report.total_calls == 1


def test_config_save_load(isolated_registry):
    """注册表配置持久化"""
    config = {"default_priority_map": {"market": 1, "fundamental": 2}}
    isolated_registry.save_config(config)

    loaded = isolated_registry.get_config()
    assert loaded == config
