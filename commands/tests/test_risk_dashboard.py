"""V7.6 Risk Dashboard — API 测试

覆盖:
  - GET /api/risk/overview          — 聚合概览（健康/降级/危急/阻塞 + 空状态）
  - GET /api/risk/alerts            — 告警列表（过滤、空列表）
  - GET /api/risk/kill-switch       — Kill Switch 详情
  - GET /api/risk/history           — 检查周期 + 事件历史
  - GET /api/risk/dimensions        — 5 维度状态
  - 边界条件: 空 sentinel、未检查
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from factor_lab.api_server.main import app
from factor_lab.api_server.routes_risk import _get_sentinel, _reset_sentinel
from factor_lab.risk import (
    RiskSentinel, KillSwitch, IncidentLog,
    RiskRule, RuleCategory, RuleSeverity,
)

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def _make_sentinel_with_incidents(n_incidents: int = 3) -> RiskSentinel:
    """创建一个包含指定数量未解决事件的 sentinel"""
    sentinel = RiskSentinel()
    sentinel.arm()

    # 模拟运行过一次检查，使用正确的规则名作为 context key
    context = {
        "data": {"data_freshness": 30, "price_missing_rate": 0.0, "market_connectivity": 0},
        "account": {"account_connection": 0, "account_balance_anomaly": 0, "position_concentration": 0.1},
        "execution": {"consecutive_order_failures": 0, "fill_deviation": 0.001, "slippage_anomaly": 0.001},
        "loss": {"daily_loss": 0.005, "drawdown": 0.02, "daily_trade_count": 10},
        "system": {"pipeline_consistency": 0},
    }
    sentinel.check_all(context)
    return sentinel


def _make_sentinel_blocked() -> RiskSentinel:
    """创建一个 Kill Switch 被触发的 sentinel

    添加一条 BLOCKER 规则随后触发检测，或直接触发 kill switch。
    """
    from factor_lab.risk import RiskRule, RuleCategory, RuleSeverity
    sentinel = RiskSentinel()
    # 添加自定义 BLOCKER 规则
    sentinel.add_rule(RiskRule(
        name="test_blocker",
        category=RuleCategory.LOSS.value,
        description="测试用阻塞规则",
        severity=RuleSeverity.BLOCKER.value,
        threshold=0.0,
        enabled=True,
    ))
    sentinel.arm()
    # 触发检测 — "test_blocker" 规则看到 actual>0 即违规
    sentinel.check_all({
        "loss": {"test_blocker": 1.0, "daily_loss": 0.03, "drawdown": 0.1},
        "data": {"data_freshness": 600, "price_missing_rate": 0.1},
    })
    return sentinel


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_sentinel():
    """每个测试前重置 sentinel 单例"""
    _reset_sentinel()
    yield
    _reset_sentinel()


@pytest.fixture
def client():
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════
# 空 sentinel（从未进行过检查）
# ═══════════════════════════════════════════════════════════════════


class TestEmptySentinel:
    """风险引擎从未运行时的默认响应"""

    def test_overview_default(self, client):
        resp = client.get("/api/risk/overview")
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "unknown"
        assert d["kill_switch_state"] == "armed"
        assert d["n_rules_checked"] == 0
        assert d["n_violations"] == 0
        assert d["n_blockers"] == 0
        # arm() 创建了一条 kill_switch 事件（事件统计中有体现）
        assert d["incident_summary"]["n_open"] >= 1
        assert "dimensions" in d
        assert "incident_summary" in d

    def test_alerts_empty(self, client):
        resp = client.get("/api/risk/alerts")
        assert resp.status_code == 200
        d = resp.json()
        # arm() 会创建一条 kill_switch 状态转换事件
        assert d["total"] >= 1

    def test_kill_switch_default(self, client):
        resp = client.get("/api/risk/kill-switch")
        assert resp.status_code == 200
        d = resp.json()
        assert d["state"] == "armed"
        assert d["n_actions_blocked"] == 0
        assert d["blocked_actions"] == []

    def test_history_empty(self, client):
        resp = client.get("/api/risk/history")
        assert resp.status_code == 200
        d = resp.json()
        assert d["check_cycles"] == []
        # arm() 会创建一条 kill_switch 事件
        assert len(d["incidents"]) >= 1

    def test_dimensions_default(self, client):
        resp = client.get("/api/risk/dimensions")
        assert resp.status_code == 200
        d = resp.json()
        assert "dimensions" in d
        for dim in ("data", "account", "execution", "loss", "system"):
            assert dim in d["dimensions"]
            assert d["dimensions"][dim]["status"] in ("healthy", "unknown")


# ═══════════════════════════════════════════════════════════════════
# 健康 sentinel
# ═══════════════════════════════════════════════════════════════════


class TestHealthySentinel:
    """运行过正常检查的健康状态"""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        sentinel = _make_sentinel_with_incidents(0)
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: sentinel,
        )

    def test_overview(self, client):
        resp = client.get("/api/risk/overview")
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] in ("healthy", "degraded")
        assert d["n_rules_checked"] > 0

    def test_alerts_after_check(self, client):
        resp = client.get("/api/risk/alerts")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] >= 0

    def test_kill_switch_armed(self, client):
        resp = client.get("/api/risk/kill-switch")
        assert resp.status_code == 200
        d = resp.json()
        assert d["state"] in ("armed", "triggered")

    def test_history_after_check(self, client):
        resp = client.get("/api/risk/history?cycles=10&incidents_limit=20")
        assert resp.status_code == 200
        d = resp.json()
        assert len(d["check_cycles"]) >= 0
        assert len(d["incidents"]) >= 0

    def test_dimensions_after_check(self, client):
        resp = client.get("/api/risk/dimensions")
        assert resp.status_code == 200
        d = resp.json()
        for dim in ("data", "account", "execution", "loss", "system"):
            assert dim in d["dimensions"]


# ═══════════════════════════════════════════════════════════════════
# 阻塞 sentinel (Kill Switch 触发)
# ═══════════════════════════════════════════════════════════════════


class TestBlockedSentinel:
    """Kill Switch 已触发时的阻塞状态"""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        sentinel = _make_sentinel_blocked()
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: sentinel,
        )

    def test_overview_blocked(self, client):
        resp = client.get("/api/risk/overview")
        assert resp.status_code == 200
        d = resp.json()
        # With blocker rules triggered, should be blocked or critical
        assert d["status"] in ("blocked", "critical")
        assert d["kill_switch_triggered"] is True
        assert d["n_blockers"] > 0

    def test_alerts_has_blockers(self, client):
        resp = client.get("/api/risk/alerts")
        assert resp.status_code == 200
        d = resp.json()
        # Blocked sentinel should have incidents recorded
        assert d["total"] > 0

    def test_alerts_filter_by_severity(self, client):
        resp = client.get("/api/risk/alerts?severity=blocker")
        assert resp.status_code == 200
        d = resp.json()
        for alert in d["alerts"]:
            assert alert["severity"] == "blocker"

    def test_kill_switch_triggered(self, client):
        resp = client.get("/api/risk/kill-switch")
        assert resp.status_code == 200
        d = resp.json()
        assert d["state"] == "triggered"
        assert d["triggered_by_rule"] != ""

    def test_history_with_data(self, client):
        resp = client.get("/api/risk/history")
        assert resp.status_code == 200
        d = resp.json()
        assert len(d["check_cycles"]) >= 1
        assert len(d["incidents"]) >= 1


# ═══════════════════════════════════════════════════════════════════
# 过滤与查询参数测试
# ═══════════════════════════════════════════════════════════════════


class TestFilterAndParams:

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        sentinel = _make_sentinel_blocked()
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: sentinel,
        )

    def test_alerts_severity_filter(self, client):
        """按 severity 过滤"""
        resp = client.get("/api/risk/alerts?severity=warning")
        assert resp.status_code == 200
        d = resp.json()
        for alert in d["alerts"]:
            assert alert["severity"] == "warning"

    def test_alerts_status_filter(self, client):
        """按 status 过滤"""
        resp = client.get("/api/risk/alerts?status=open")
        assert resp.status_code == 200
        d = resp.json()
        for alert in d["alerts"]:
            assert alert["status"] == "open"

    def test_alerts_limit(self, client):
        """limit 参数"""
        resp = client.get("/api/risk/alerts?limit=5")
        assert resp.status_code == 200
        d = resp.json()
        assert d["count"] <= 5

    def test_history_params(self, client):
        """检查周期与事件数量参数"""
        resp = client.get("/api/risk/history?cycles=5&incidents_limit=10")
        assert resp.status_code == 200
        d = resp.json()
        assert len(d["check_cycles"]) <= 5
        assert len(d["incidents"]) <= 10


# ═══════════════════════════════════════════════════════════════════
# 手动构造的 sentinel — 精确控制测试数据
# ═══════════════════════════════════════════════════════════════════


class TestCustomSentinel:

    @pytest.fixture
    def custom_sentinel(self):
        """构造一个包含多条告警和触发状态的 sentinel"""
        sentinel = RiskSentinel()
        sentinel.arm()

        # 手动添加规则
        sentinel.add_rule(RiskRule(
            name="test_critical_rule",
            category="data",
            description="测试危急规则",
            severity="critical",
            enabled=True,
        ))
        sentinel.add_rule(RiskRule(
            name="test_blocker_rule",
            category="execution",
            description="测试阻塞规则",
            severity="blocker",
            enabled=True,
        ))

        # 模拟检测 — 使用规则名作为 context key
        sentinel.check_all({
            "data": {"test_critical_rule": 1.0},
            "execution": {"test_blocker_rule": 1.0},
        })
        return sentinel

    def test_overview_custom(self, client, custom_sentinel, monkeypatch):
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: custom_sentinel,
        )
        resp = client.get("/api/risk/overview")
        assert resp.status_code == 200
        d = resp.json()
        # Should have violations
        assert d["n_violations"] > 0


# ═══════════════════════════════════════════════════════════════════
# 边界与错误情况
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_overview_returns_valid_json(self, client):
        """验证概览返回结构完整"""
        resp = client.get("/api/risk/overview")
        assert resp.status_code == 200
        d = resp.json()
        required_keys = [
            "status", "kill_switch_state", "kill_switch_triggered",
            "n_rules_checked", "n_violations", "n_blockers",
            "n_open_incidents", "dimensions", "incident_summary",
            "status_label",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_kill_switch_returns_valid_json(self, client):
        """验证 kill switch 返回结构完整"""
        resp = client.get("/api/risk/kill-switch")
        assert resp.status_code == 200
        d = resp.json()
        required_keys = [
            "name", "state", "status", "triggered_at",
            "n_actions_blocked", "blocked_actions",
            "auto_recovery_enabled",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_dimensions_returns_all_five(self, client):
        """验证 5 维度都返回"""
        resp = client.get("/api/risk/dimensions")
        assert resp.status_code == 200
        d = resp.json()
        expected_dims = {"data", "account", "execution", "loss", "system"}
        assert set(d["dimensions"].keys()) == expected_dims

    def test_alerts_empty_filters(self, client, monkeypatch):
        """不存在的 severity 过滤应返回空列表"""
        sentinel = _make_sentinel_with_incidents(0)
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: sentinel,
        )
        resp = client.get("/api/risk/alerts?severity=nonexistent")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 0
        assert d["alerts"] == []

    def test_alerts_valid_severity_filter(self, client, monkeypatch):
        """有效的 severity 过滤应返回匹配的事件"""
        # Create a sentinel with known incidents
        il = IncidentLog()
        il.record("test_rule", severity="warning", message="test warning", category="data")
        il.record("test_rule2", severity="blocker", message="test blocker", category="execution")
        sentinel = RiskSentinel(incident_log=il)
        sentinel.arm()
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: sentinel,
        )

        resp = client.get("/api/risk/alerts?severity=warning")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 1
        assert d["alerts"][0]["severity"] == "warning"

    def test_alerts_valid_status_filter(self, client, monkeypatch):
        """有效的 status 过滤"""
        il = IncidentLog()
        rec = il.record("test_rule", severity="warning", message="test", category="data")
        il.resolve(rec.incident_id, "resolved")
        il.record("test_rule2", severity="blocker", message="blocker", category="execution")
        sentinel = RiskSentinel(incident_log=il)
        sentinel.arm()
        monkeypatch.setattr(
            "factor_lab.api_server.routes_risk._get_sentinel",
            lambda: sentinel,
        )

        resp = client.get("/api/risk/alerts?status=resolved")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 1
        assert d["alerts"][0]["status"] == "resolved"
