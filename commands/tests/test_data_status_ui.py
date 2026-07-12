"""Tests for V7.1 Data Status / Provider Failure UI — 后端 API 路由测试"""
import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from factor_lab.api_server.main import app



def _configured_ui_token() -> str:
    token = os.environ.get("HERMES_UI_TOKEN", "").strip()
    if token:
        return token
    env_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith("HERMES_UI_TOKEN="):
                return raw_line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


client = TestClient(app)
if (token := _configured_ui_token()):
    client.headers.update({"Authorization": f"Bearer {token}"})


def _seed_test_source():
    """在 V5 DataRegistry 中注册一个测试数据源"""
    from factor_lab.data_source.registry import DataRegistry
    from factor_lab.data_source.spec import DataSourceSpec, DataSourceCategory, DataSourceCapability
    registry = DataRegistry()
    spec = DataSourceSpec(
        source_id="test_v71_source",
        name="V7.1 Test Source",
        category=DataSourceCategory.MARKET.value,
        capabilities=[DataSourceCapability.REALTIME_QUOTE.value],
        priority=1,
    )
    registry.register(spec)
    return "test_v71_source"


def test_data_providers_endpoint():
    """GET /api/data/providers 返回 200 且包含 sources 列表"""
    resp = client.get("/api/data/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert "total" in data
    assert "checked_at" in data


def test_data_providers_filter():
    """GET /api/data/providers?source_id= 过滤单个数据源"""
    src_id = _seed_test_source()
    resp = client.get(f"/api/data/providers?source_id={src_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["sources"][0]["source_id"] == src_id


def test_data_providers_unknown_source():
    """未知 source_id 返回 error"""
    resp = client.get("/api/data/providers?source_id=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_data_overview_endpoint():
    """GET /api/data/overview 返回 200 且包含 summary"""
    resp = client.get("/api/data/overview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "summary" in data
    assert "checked_at" in data
    s = data["summary"]
    assert "total_sources" in s
    assert "active" in s
    assert "degraded" in s
    assert "inactive" in s
    assert "blocking_issues" in s


def test_data_freshness_endpoint():
    """GET /api/data/freshness 返回 200 且包含 freshness 报告"""
    resp = client.get("/api/data/freshness")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_status" in data
    assert "files" in data


def test_data_gaps_endpoint():
    """GET /api/data/gaps 返回 200 且包含 gaps 报告"""
    resp = client.get("/api/data/gaps")
    assert resp.status_code == 200
    data = resp.json()
    assert "gaps" in data
    assert "summary" in data
    assert "report_time" in data


def test_data_fetch_log_endpoint():
    """GET /api/data/fetch-log 返回 200 且包含 entries 列表"""
    resp = client.get("/api/data/fetch-log")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert "total" in data


def test_data_fetch_log_limit():
    """GET /api/data/fetch-log?limit=10 正常工作"""
    resp = client.get("/api/data/fetch-log?limit=10")
    assert resp.status_code == 200


def test_data_routes_registered():
    """确认 5 个数据路由均已注册 — 通过 HTTP 请求验证"""
    paths = ["/api/data/overview", "/api/data/providers", "/api/data/freshness", "/api/data/gaps", "/api/data/fetch-log"]
    for path in paths:
        resp = client.get(path)
        # 只要返回 200（有数据）或 200（含错误信息）就算路由存在
        assert resp.status_code == 200, f"路由 {path} 返回 {resp.status_code}"


def test_provider_health_has_required_fields():
    """每个数据源应包含健康必要字段"""
    resp = client.get("/api/data/providers")
    data = resp.json()
    for src in data["sources"]:
        assert "source_id" in src
        assert "name" in src
        assert "status" in src
        assert "health" in src
        h = src["health"]
        assert "success_rate" in h
        assert "total_calls" in h
        assert "error_count" in h
        assert "last_check" in h


def test_data_overview_summary_counts():
    """overview 的计数应合理"""
    resp = client.get("/api/data/overview")
    data = resp.json()["data"]
    s = data["summary"]
    assert s["total_sources"] >= 0
    total = s["active"] + s["degraded"] + s["inactive"] + s["unchecked"]
    assert total == s["total_sources"], f"状态计数 {total} 不等于总数 {s['total_sources']}"
