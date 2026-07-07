"""V7.5 Report Center — 报告中心 API 测试

覆盖:
  - 健康检查 /reports/health
  - 概览统计 /reports/summary
  - 报告列表 /reports (类型过滤、分页)
  - 详情查看 /reports/detail/{type}/{id}
  - 删除 /reports/{type}/{id}
  - 最近报告 /reports/recent
  - 边界条件: 空目录、不存在的路径、无效类型
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from factor_lab.api_server.main import app
from factor_lab.api_server.routes_reports import _get_reports_base

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════
# Fixtures — 测试用报告目录构建
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def reports_base(tmp_path):
    """在临时目录构建仿真的报告目录结构"""
    base = tmp_path / "HermesReports"
    base.mkdir()

    # ── backtest ──
    bt = base / "backtests" / "test_factor"
    bt.mkdir(parents=True)
    _write_json(bt / "metrics.json", {
        "strategy_name": "TestFactor Top20",
        "factor_name": "test_factor",
        "sharpe": 1.53,
        "cagr": 45.52,
        "max_drawdown": -13.63,
        "cumulative_return": 70.65,
        "sortino": 2.17,
        "volatility": 24.58,
        "win_rate": 59.27,
        "total_days": 359,
        "start_date": "2025-01-02",
        "end_date": "2026-06-30",
        "rebalance_freq": "monthly",
        "benchmark": "沪深300",
        "universe": "中证500",
        "generated_at": "2026-07-05T08:53:48.981978+08:00",
        "beta": 0.9065,
        "information_ratio": 0.85,
        "calmar": 3.34,
    })
    (bt / "report.html").write_text("<html><body>回测报告</body></html>", encoding="utf-8")
    (bt / "returns.csv").write_text("date,return\n2025-01-02,0.01\n2025-01-03,-0.005\n", encoding="utf-8")
    (bt / "equity_curve.csv").write_text("date,equity\n2025-01-02,1.0\n2025-01-03,0.995\n", encoding="utf-8")

    # ── strategy ──
    st = base / "strategies" / "single_strategy"
    st.mkdir(parents=True)
    (st / "策略分析报告_2026-07-06T15-44-28.html").write_text(
        "<html><body>策略报告内容</body></html>", encoding="utf-8"
    )
    (st / "自定义策略报告_2026-07-06T15-44-28.html").write_text(
        "<html><body>自定义策略</body></html>", encoding="utf-8"
    )

    # ── version ──
    vr = base / "version_reports"
    vr.mkdir(parents=True)
    _write_json(vr / "completion_V7.0_20260706_131809.json", {
        "version": "V7.0",
        "name": "Modern Frontend Dashboard",
        "status": "completed",
        "completed_at": "2026-07-06T13:18:09+08:00",
        "commits": [{"hash": "abc1234", "message": "feat: frontend dashboard"}],
        "files_changed": ["frontend/src/App.jsx", "frontend/src/pages/Dashboard.jsx"],
    })
    _write_json(vr / "version_report_20260707_174521.json", {
        "generated_at": "2026-07-07T17:45:21.858536+08:00",
        "current_version": "V7.5",
        "total_completed": 47,
        "total_failed": 0,
        "versions": [
            {"version": "V3.0", "name": "Alpha Factory Foundation", "status": "completed"},
            {"version": "V7.0", "name": "Modern Frontend Dashboard", "status": "completed"},
        ],
    })
    # latest.json 应该被跳过
    _write_json(vr / "latest.json", {"current_version": "V7.5"})

    # ── session ──
    sb = base / "session_backups" / "ac_20260706_150601_7418eb"
    sb.mkdir(parents=True)
    _write_json(sb / "request.json", {
        "agent": "hermes_developer",
        "prompt": "实现 V7.5 报告中心 Report Center",
        "version": "V7.5",
        "created_at": "2026-07-06T15:06:01+08:00",
    })
    _write_json(sb / "summary.json", {
        "status": "completed",
        "agent": "hermes_developer",
    })
    (sb / "answer.md").write_text("## 完成\n报告中心已实现。", encoding="utf-8")

    # ── roadmap ──
    rb = base / "roadmap_backups" / "roadmap_backup_20260707_084801"
    rb.mkdir(parents=True)
    _write_json(rb / "roadmap.json", {
        "versions": [
            {"version": "V7.5", "name": "Report Center", "status": "in_progress"},
            {"version": "V7.6", "name": "Risk Dashboard", "status": "pending"},
        ],
    })

    return base


def _write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def client(reports_base, monkeypatch):
    """使用临时报告目录和 monkeypatch 的 TestClient"""
    monkeypatch.setattr("factor_lab.api_server.routes_reports._get_reports_base", lambda: reports_base)
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════════


class TestHealth:
    def test_health_ok(self, client, reports_base):
        resp = client.get("/api/reports/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["exists"] is True
        assert data["reports_base"] == str(reports_base)
        assert "subdirs" in data
        assert "backtests" in data["subdirs"]

    def test_health_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.api_server.routes_reports._get_reports_base",
            lambda: Path("/nonexistent/path")
        )
        c = TestClient(app)
        resp = c.get("/api/reports/health")
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["exists"] is False


# ═══════════════════════════════════════════════════════════════════
# 概览统计
# ═══════════════════════════════════════════════════════════════════


class TestSummary:
    def test_summary_counts(self, client, reports_base):
        resp = client.get("/api/reports/summary")
        assert resp.status_code == 200
        data = resp.json()
        # 1 backtest + 2 strategy + 2 version (+ latest.json 被跳过) + 1 session + 1 roadmap
        assert data["total"] == 7
        assert data["by_type"]["backtest"] == 1
        assert data["by_type"]["strategy"] == 2
        assert data["by_type"]["version"] == 2  # latest.json 被跳过
        assert data["by_type"]["session"] == 1
        assert data["by_type"]["roadmap"] == 1
        assert data["recent_7d"] >= 7
        assert data["total_size_mb"] >= 0  # 小文件可能不足 1MB
        assert data["report_base"] == str(reports_base)
        assert "generated_at" in data

    def test_summary_empty_base(self, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.api_server.routes_reports._get_reports_base",
            lambda: Path("/tmp/empty_reports_dir_xyz")
        )
        c = TestClient(app)
        resp = c.get("/api/reports/summary")
        data = resp.json()
        assert data["total"] == 0
        assert "error" in data

    def test_summary_with_zero_reports(self, tmp_path, monkeypatch):
        """空目录下所有类型都是 0"""
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(
            "factor_lab.api_server.routes_reports._get_reports_base",
            lambda: empty
        )
        c = TestClient(app)
        resp = c.get("/api/reports/summary")
        data = resp.json()
        assert data["total"] == 0
        for k in ("backtest", "strategy", "version", "session", "roadmap"):
            assert data["by_type"][k] == 0
        assert "report_base" in data


# ═══════════════════════════════════════════════════════════════════
# 报告列表
# ═══════════════════════════════════════════════════════════════════


class TestListReports:
    def test_list_all(self, client):
        resp = client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 7
        assert len(data["reports"]) == 7
        assert data["type"] == "all"
        assert data["display_name"] == "全部报告"

    def test_list_by_type_backtest(self, client):
        resp = client.get("/api/reports?type=backtest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["type"] == "backtest"
        r = data["reports"][0]
        assert r["type"] == "backtest"
        assert r["name"] == "TestFactor Top20"
        assert r["factor"] == "test_factor"
        assert r["metrics"]["sharpe"] == 1.53
        assert r["metrics"]["cagr"] == 45.52
        assert r["has_html"] is True
        assert r["has_csv"] is True

    def test_list_by_type_strategy(self, client):
        resp = client.get("/api/reports?type=strategy")
        data = resp.json()
        assert data["total"] == 2
        assert all(r["type"] == "strategy" for r in data["reports"])
        assert data["display_name"] == "策略报告"
        assert data["icon"] == "📈"

    def test_list_by_type_version(self, client):
        resp = client.get("/api/reports?type=version")
        data = resp.json()
        assert data["total"] == 2
        # 确认 latest.json 被跳过
        ids = [r["id"] for r in data["reports"]]
        assert "latest.json" not in ids
        # 确认 completion 报告有 commits/files_changed
        comp = [r for r in data["reports"] if r.get("is_completion")]
        assert len(comp) >= 1
        assert comp[0]["commits"] == [{"hash": "abc1234", "message": "feat: frontend dashboard"}]
        assert "files_changed" in comp[0]

    def test_list_by_type_session(self, client):
        resp = client.get("/api/reports?type=session")
        data = resp.json()
        assert data["total"] == 1
        r = data["reports"][0]
        assert r["type"] == "session"
        assert r["agent"] == "hermes_developer"
        assert r["status"] == "completed"
        assert "报告中心" in r["prompt_preview"]

    def test_list_by_type_roadmap(self, client):
        resp = client.get("/api/reports?type=roadmap")
        data = resp.json()
        assert data["total"] == 1
        r = data["reports"][0]
        assert r["type"] == "roadmap"
        assert r["has_json"] is True

    def test_list_pagination(self, client):
        resp = client.get("/api/reports?limit=3&offset=0")
        data = resp.json()
        assert len(data["reports"]) == 3
        assert data["limit"] == 3
        assert data["offset"] == 0
        assert data["total"] == 7

        resp2 = client.get("/api/reports?limit=3&offset=3")
        data2 = resp2.json()
        assert len(data2["reports"]) == 3

        resp3 = client.get("/api/reports?limit=3&offset=10")
        data3 = resp3.json()
        assert len(data3["reports"]) == 0

    def test_list_invalid_type_defaults_to_all(self, client):
        resp = client.get("/api/reports?type=unknown_type")
        data = resp.json()
        assert data["total"] == 7  # falls back to discovering all types
        assert data["type"] == "unknown_type"  # 保留原始过滤值

    def test_list_sorting_by_created_at(self, client):
        resp = client.get("/api/reports?sort=created_at")
        data = resp.json()
        assert data["total"] == 7
        # 按 created_at 倒序
        dates = [r.get("created_at", "") for r in data["reports"]]
        assert dates == sorted(dates, reverse=True)

    def test_list_empty_base(self, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.api_server.routes_reports._get_reports_base",
            lambda: Path("/nonexistent/reports_dir_abc")
        )
        c = TestClient(app)
        resp = c.get("/api/reports")
        data = resp.json()
        assert data["total"] == 0
        assert len(data["reports"]) == 0
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════
# 详情查看
# ═══════════════════════════════════════════════════════════════════


class TestDetail:
    def test_backtest_detail(self, client):
        resp = client.get("/api/reports/detail/backtest/test_factor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "backtest"
        assert data["id"] == "test_factor"
        assert data["metrics"]["sharpe"] == 1.53
        assert data["metrics"]["factor_name"] == "test_factor"
        assert "回测报告" in data["html_content"]
        assert "returns_csv" in data
        assert len(data["files"]) >= 4

    def test_strategy_detail(self, client):
        resp = client.get(
            "/api/reports/detail/strategy/single_strategy/策略分析报告_2026-07-06T15-44-28.html"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "strategy"
        assert "策略报告内容" in data["html_content"]
        assert data["size_bytes"] > 0

    def test_version_detail_completion(self, client):
        resp = client.get("/api/reports/detail/version/completion_V7.0_20260706_131809.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "version"
        assert data["data"]["version"] == "V7.0"
        assert data["data"]["status"] == "completed"
        assert len(data["data"]["commits"]) == 1

    def test_version_detail_report(self, client):
        resp = client.get("/api/reports/detail/version/version_report_20260707_174521.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "version"
        assert data["data"]["current_version"] == "V7.5"
        assert data["data"]["total_completed"] == 47

    def test_session_detail(self, client):
        resp = client.get("/api/reports/detail/session/ac_20260706_150601_7418eb")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "session"
        assert data["request"]["agent"] == "hermes_developer"
        assert data["summary"]["status"] == "completed"
        assert "报告中心已实现" in data["answer_preview"]

    def test_roadmap_detail(self, client):
        resp = client.get("/api/reports/detail/roadmap/roadmap_backup_20260707_084801")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "roadmap"
        assert "roadmap.json" in data["json_files"]
        assert "V7.5" in json.dumps(data["content"])
        assert data["total_files"] >= 1

    def test_detail_not_found(self, client):
        resp = client.get("/api/reports/detail/backtest/nonexistent_factor")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_detail_unknown_type(self, client):
        resp = client.get("/api/reports/detail/unknown_type/some_id")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert "unknown" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# 删除报告
# ═══════════════════════════════════════════════════════════════════


class TestDelete:
    def test_delete_backtest(self, client, reports_base):
        resp = client.delete("/api/reports/backtest/test_factor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert not (reports_base / "backtests" / "test_factor").exists()

    def test_delete_strategy(self, client, reports_base):
        resp = client.delete(
            "/api/reports/strategy/single_strategy/策略分析报告_2026-07-06T15-44-28.html"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        # 另一个策略报告应该还在
        other = reports_base / "strategies" / "single_strategy" / "自定义策略报告_2026-07-06T15-44-28.html"
        assert other.exists()

    def test_delete_version(self, client, reports_base):
        resp = client.delete("/api/reports/version/completion_V7.0_20260706_131809.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert not (reports_base / "version_reports" / "completion_V7.0_20260706_131809.json").exists()

    def test_delete_session(self, client, reports_base):
        resp = client.delete("/api/reports/session/ac_20260706_150601_7418eb")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert not (reports_base / "session_backups" / "ac_20260706_150601_7418eb").exists()

    def test_delete_roadmap(self, client, reports_base):
        resp = client.delete("/api/reports/roadmap/roadmap_backup_20260707_084801")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert not (reports_base / "roadmap_backups" / "roadmap_backup_20260707_084801").exists()

    def test_delete_not_found(self, client):
        resp = client.delete("/api/reports/backtest/nonexistent")
        data = resp.json()
        assert "error" in data
        assert "not found" in data["error"]

    def test_delete_unknown_type(self, client):
        resp = client.delete("/api/reports/unknown_type/some_id")
        data = resp.json()
        assert "error" in data

    def test_delete_empty_base(self, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.api_server.routes_reports._get_reports_base",
            lambda: Path("/nonexistent_reports_xyz")
        )
        c = TestClient(app)
        resp = c.delete("/api/reports/backtest/test")
        data = resp.json()
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════
# 最近报告
# ═══════════════════════════════════════════════════════════════════


class TestRecent:
    def test_recent_reports(self, client):
        """所有测试报告都在最近 720 小时内"""
        resp = client.get("/api/reports/recent?hours=720")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hours"] == 720
        assert data["total"] == 7

    def test_recent_within_hours(self, client):
        """使用 1 小时窗口，所有文件的 mtime 是当前时间"""
        resp = client.get("/api/reports/recent?hours=1")
        data = resp.json()
        assert data["hours"] == 1
        assert data["total"] >= 0

    def test_recent_invalid_hours_default(self, client):
        resp = client.get("/api/reports/recent")
        data = resp.json()
        assert data["hours"] == 48  # default

    def test_recent_empty_base(self, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.api_server.routes_reports._get_reports_base",
            lambda: Path("/tmp/void_reports_xxx")
        )
        c = TestClient(app)
        resp = c.get("/api/reports/recent")
        data = resp.json()
        assert data["total"] == 0
        assert data["reports"] == []
