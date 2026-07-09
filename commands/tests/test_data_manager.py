#!/usr/bin/env python3
"""
Tests for DataManager — bootstrap / update / health CLI commands.

Uses monkeypatching/mocking to avoid real Tushare API calls.
Tests cover:
  - Bootstrap: manifest creation, provider self_check integration, arg validation
  - Update: freshness report, provider iteration
  - Health: table output, coverage/missing rates, all-provider coverage
  - Error handling: invalid source, empty providers, missing --start
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

# ── Path setup ──
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from commands.data_manager import (
    DataManager,
    MANIFEST_DIR,
    HEALTH_DIR,
    MANIFESTS_TOUCH_RECORD,
    FRESHNESS_FILE,
    HEALTH_FILE,
    cmd_bootstrap,
    cmd_update,
    cmd_health,
)

CST = timezone(timedelta(hours=8))

# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def clean_audit_dirs():
    """Ensure clean audit dirs before each test."""
    for d in [MANIFEST_DIR, HEALTH_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
    yield


class MockProvider:
    """模拟 BaseProvider 实例"""

    def __init__(self, name: str = "tushare_market", status: str = "ok",
                 errors: list[str] = None, warnings: list[str] = None,
                 freshness: dict[str, str] = None,
                 enabled_types: list[str] = None):
        self._name = name
        self._status = status
        self._errors = errors or []
        self._warnings = warnings or []
        self._freshness = freshness or {"daily": "20260707", "trade_cal": "ok"}
        self._enabled_types = enabled_types or ["daily", "daily_basic", "adj_factor", "stk_limit"]

    @property
    def capability(self):
        class Cap:
            pass
        cap = Cap()
        cap.name = self._name
        cap.coverage_start = "20000101"
        cap.coverage_end = "20260708"
        for t in self._enabled_types:
            setattr(cap, f"can_{t}", True)
        return cap

    def self_check(self):
        from commands.data_providers import ProviderHealth
        h = ProviderHealth(
            source_id=self._name,
            status=self._status,
            errors=self._errors,
            warnings=self._warnings,
            data_freshness=self._freshness,
            last_check=datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        )
        return h


@pytest.fixture
def mock_all_providers_ok(monkeypatch):
    """所有 5 个 Provider 返回 ok"""
    names = [
        "tushare_market", "tushare_fina", "tushare_stock",
        "tushare_fund_flow", "tushare_event",
    ]
    providers = [MockProvider(name=n, status="ok") for n in names]

    def _mock_get(self):
        return providers

    monkeypatch.setattr(
        "commands.data_manager.DataManager._get_providers",
        _mock_get,
    )
    return providers


@pytest.fixture
def mock_one_provider_fails(monkeypatch):
    """一个 Provider 失败，其余 ok"""
    providers = [
        MockProvider(name="tushare_market", status="ok"),
        MockProvider(name="tushare_fina", status="error",
                     errors=["API limit exceeded"]),
        MockProvider(name="tushare_stock", status="partial",
                     warnings=["index_daily empty"]),
        MockProvider(name="tushare_fund_flow", status="ok"),
        MockProvider(name="tushare_event", status="ok"),
    ]

    def _mock_get(self):
        return providers

    monkeypatch.setattr(
        "commands.data_manager.DataManager._get_providers",
        _mock_get,
    )
    return providers


@pytest.fixture
def mock_empty_providers(monkeypatch):
    """返回空列表（没有 Provider）"""

    def _mock_get(self):
        return []

    monkeypatch.setattr(
        "commands.data_manager.DataManager._get_providers",
        _mock_get,
    )
    return []


# ═════════════════════════════════════════════════════════════════════════
# DataManager 基本测试
# ═════════════════════════════════════════════════════════════════════════


class TestDataManagerInit:
    def test_default_source(self):
        dm = DataManager()
        assert dm.source == "tushare"

    def test_invalid_source(self):
        with pytest.raises(ValueError, match="不支持的数据源"):
            DataManager(source="baostock")


# ═════════════════════════════════════════════════════════════════════════
# Bootstrap 测试
# ═════════════════════════════════════════════════════════════════════════


class TestBootstrap:
    def test_bootstrap_all_ok(self, mock_all_providers_ok):
        dm = DataManager()
        result = dm.bootstrap(start="20190101")

        assert len(result) == 5
        for pid, info in result.items():
            assert info["status"] == "ok"
            assert "manifest_path" in info
            assert Path(info["manifest_path"]).exists()

        # 验证全局 manifest
        touch = MANIFEST_DIR / MANIFESTS_TOUCH_RECORD
        assert touch.exists()
        data = json.loads(touch.read_text())
        assert data["source"] == "tushare"
        assert data["start"] == "20190101"
        assert len(data["providers"]) == 5

    def test_bootstrap_with_provider_failure(self, mock_one_provider_fails):
        dm = DataManager()
        result = dm.bootstrap(start="20200101")

        assert result["tushare_fina"]["status"] == "error"
        assert result["tushare_market"]["status"] == "ok"
        assert result["tushare_stock"]["status"] == "partial"

        # 失败的 provider 不应创建 manifest
        fina_manifest = MANIFEST_DIR / "manifest_tushare_fina.json"
        assert not fina_manifest.exists()

    def test_bootstrap_missing_start(self):
        dm = DataManager()
        with pytest.raises(ValueError, match="--start"):
            dm.bootstrap(start="")

    def test_bootstrap_empty_providers(self, mock_empty_providers):
        dm = DataManager()
        result = dm.bootstrap(start="20200101")
        assert len(result) == 0

    def test_bootstrap_manifest_content(self, mock_all_providers_ok):
        dm = DataManager()
        result = dm.bootstrap(start="20190101")

        market_result = result["tushare_market"]
        manifest_path = market_result["manifest_path"]

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["source"] == "tushare"
        assert manifest["start_date"] == "20190101"
        assert "daily" in manifest["data_types"]
        assert manifest["bootstrapped_at"] is not None

    def test_bootstrap_with_end_date(self, mock_all_providers_ok):
        dm = DataManager()
        result = dm.bootstrap(start="20190101", end="20261231")

        touch = MANIFEST_DIR / MANIFESTS_TOUCH_RECORD
        data = json.loads(touch.read_text())
        assert data["end"] == "20261231"


# ═════════════════════════════════════════════════════════════════════════
# Update 测试
# ═════════════════════════════════════════════════════════════════════════


class TestUpdate:
    def test_update_all_ok(self, mock_all_providers_ok):
        dm = DataManager()
        result = dm.update(days=5)

        assert len(result) == 5
        for pid, info in result.items():
            assert info["status"] == "ok"
            assert "freshness" in info
            assert "checked_at" in info

        # 验证 freshness 文件
        freshness = HEALTH_DIR / FRESHNESS_FILE
        assert freshness.exists()
        data = json.loads(freshness.read_text())
        assert data["source"] == "tushare"
        assert data["days"] == 5
        assert len(data["providers"]) == 5

    def test_update_with_partial_failure(self, mock_one_provider_fails):
        dm = DataManager()
        result = dm.update(days=3)

        assert result["tushare_fina"]["status"] == "error"
        assert result["tushare_stock"]["status"] == "partial"
        assert result["tushare_market"]["status"] == "ok"

    def test_update_invalid_days(self, mock_all_providers_ok):
        dm = DataManager()
        with pytest.raises(ValueError, match="--days 必须"):
            dm.update(days=0)

    def test_update_freshness_record(self, mock_all_providers_ok):
        dm = DataManager()
        dm.update(days=10)

        freshness = HEALTH_DIR / FRESHNESS_FILE
        with open(freshness) as f:
            record = json.load(f)

        assert "updated_at" in record
        assert record["providers"]["tushare_market"]["freshness"]["daily"] == "20260707"


# ═════════════════════════════════════════════════════════════════════════
# Health 测试
# ═════════════════════════════════════════════════════════════════════════


class TestHealth:
    def test_health_all_ok(self, mock_all_providers_ok):
        dm = DataManager()
        rows = dm.health()

        assert len(rows) == 5
        for r in rows:
            assert r["status"] == "ok"
            assert r["latest_date"] == "20260707"
            assert r["data_types"] >= 2

    def test_health_mixed_status(self, mock_one_provider_fails):
        dm = DataManager()
        rows = dm.health()

        status_map = {r["provider"]: r["status"] for r in rows}
        assert status_map["tushare_fina"] == "error"
        assert status_map["tushare_stock"] == "partial"
        assert status_map["tushare_market"] == "ok"

    def test_health_report_file(self, mock_all_providers_ok):
        dm = DataManager()
        dm.health()

        report = HEALTH_DIR / HEALTH_FILE
        assert report.exists()

        with open(report) as f:
            data = json.load(f)

        assert data["source"] == "tushare"
        assert data["summary"]["total"] == 5
        assert data["summary"]["ok"] == 5
        assert data["summary"]["error"] == 0
        assert data["summary"]["missing_pct"] == 0.0

    def test_health_summary_with_failures(self, mock_one_provider_fails):
        dm = DataManager()
        dm.health()

        report = HEALTH_DIR / HEALTH_FILE
        with open(report) as f:
            data = json.load(f)

        summary = data["summary"]
        assert summary["total"] == 5
        assert summary["ok"] == 3
        assert summary["partial"] == 1
        assert summary["error"] == 1
        assert summary["missing_pct"] > 0

    def test_health_with_past_freshness(self, mock_all_providers_ok):
        # 预先写入 freshness 记录
        past = {
            "source": "tushare",
            "days": 5,
            "updated_at": "2026-07-07 15:30:00",
            "providers": {},
        }
        freshness_file = HEALTH_DIR / FRESHNESS_FILE
        with open(freshness_file, "w") as f:
            json.dump(past, f)

        dm = DataManager()
        # 应正常运行不报错
        rows = dm.health()
        assert len(rows) == 5


# ═════════════════════════════════════════════════════════════════════════
# CLI Handler 测试
# ═════════════════════════════════════════════════════════════════════════


class TestCLIHandlers:
    def test_cmd_bootstrap_minimal(self, mock_all_providers_ok, capsys):
        cmd_bootstrap(["--source", "tushare", "--start", "20190101"])
        captured = capsys.readouterr()
        assert "全量数据初始化" in captured.out or "汇总" in captured.out

    def test_cmd_bootstrap_missing_start(self, mock_all_providers_ok, capsys):
        cmd_bootstrap(["--source", "tushare"])
        captured = capsys.readouterr()
        assert "用法" in captured.out

    def test_cmd_update_default(self, mock_all_providers_ok, capsys):
        cmd_update(["--source", "tushare"])
        captured = capsys.readouterr()
        assert "增量数据更新" in captured.out or "汇总" in captured.out

    def test_cmd_update_with_days(self, mock_all_providers_ok, capsys):
        cmd_update(["--source", "tushare", "--days", "10"])
        captured = capsys.readouterr()
        assert "days=10" in captured.out or "汇总" in captured.out

    def test_cmd_health(self, mock_all_providers_ok, capsys):
        cmd_health(["--source", "tushare"])
        captured = capsys.readouterr()
        assert "数据源健康状态" in captured.out
        assert "覆盖率" in captured.out
        assert "缺失率" in captured.out
    