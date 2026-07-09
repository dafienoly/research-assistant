"""Risk Dashboard API routes — V7.6 风险仪表盘

提供对 V4.4 Risk Sentinel / Kill Switch / Incident Log 的 REST API:
  - /api/risk/overview       — 聚合风险概览
  - /api/risk/alerts         — 活跃告警列表
  - /api/risk/kill-switch    — Kill Switch 详情 + 被拦操作
  - /api/risk/history        — 检查周期历史 + 事件历史
  - /api/risk/dimensions     — 5 维度逐项状态

通过模块级 RiskSentinel 单例连接底层风险引擎。
测试时可用 monkeypatch 替换 _get_sentinel()。
"""
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from factor_lab.risk import RiskSentinel, SentinelStatus

CST = timezone(timedelta(hours=8))

router = APIRouter()


# ---------------------------------------------------------------------------
# 单例 Sentinel（模块级，延迟初始化）
# ---------------------------------------------------------------------------
_sentinel_instance: Optional[RiskSentinel] = None


def _get_sentinel() -> RiskSentinel:
    """返回全局 RiskSentinel 单例（供测试 monkeypatch）"""
    global _sentinel_instance
    if _sentinel_instance is None:
        _sentinel_instance = RiskSentinel()
        # sentinel starts un-armed by default; arm so rules can be checked
        _sentinel_instance.arm()
    return _sentinel_instance


def _reset_sentinel():
    """重置单例（测试用）"""
    global _sentinel_instance
    _sentinel_instance = None


def _build_overview(sentinel: RiskSentinel) -> dict:
    """构建统一的概览响应"""
    status = sentinel.get_status()
    ks = sentinel.kill_switch
    il = sentinel.incident_log

    return {
        "status": status.status,
        "last_check_at": status.last_check_at,
        "n_rules_checked": status.n_rules_checked,
        "n_violations": status.n_violations,
        "n_blockers": status.n_blockers,
        "n_open_incidents": status.n_open_incidents,
        "kill_switch_state": ks.state,
        "kill_switch_triggered": ks.is_triggered(),
        "kill_switch_blocked": ks.is_blocked(),
        "incident_summary": il.summary(),
        "dimensions": status.dimensions,
        "status_label": _status_label(status.status),
    }


def _status_label(status: str) -> str:
    labels = {
        "healthy": "健康",
        "degraded": "降级",
        "critical": "危急",
        "blocked": "阻塞",
        "unknown": "未知",
    }
    return labels.get(status, status)


# ===================================================================
# 端点
# ===================================================================


@router.get("/risk/overview")
def risk_overview():
    """GET /api/risk/overview — 聚合风险概览

    返回整体状态、维度状态、告警摘要、Kill Switch 快照。
    """
    sentinel = _get_sentinel()
    return _build_overview(sentinel)


@router.get("/risk/alerts")
def risk_alerts(
    severity: str = Query("", description="按严重程度过滤"),
    status: str = Query("", description="按状态过滤 (open/acknowledged/resolved/closed)"),
    limit: int = Query(100, description="最多返回条数"),
):
    """GET /api/risk/alerts — 活跃告警列表

    返回 IncidentLog 中的事件，支持按 severity / status 过滤。
    """
    sentinel = _get_sentinel()
    incidents = sentinel.incident_log.incidents

    # 过滤
    filtered = []
    for inc in incidents:
        if severity and inc.severity != severity:
            continue
        if status and inc.status != status:
            continue
        filtered.append(inc)

    # 按触发时间倒序
    filtered.sort(key=lambda i: i.triggered_at, reverse=True)

    return {
        "total": len(filtered),
        "count": min(len(filtered), limit),
        "alerts": [inc.to_dict() for inc in filtered[:limit]],
    }


@router.get("/risk/kill-switch")
def risk_kill_switch():
    """GET /api/risk/kill-switch — Kill Switch 详情

    包含当前状态、触发信息、被拦操作记录。
    """
    sentinel = _get_sentinel()
    ks = sentinel.kill_switch

    return {
        "name": ks.name,
        "state": ks.state,
        "status": ks.status.to_dict(),
        "triggered_at": ks.status.triggered_at,
        "triggered_by_rule": ks.status.triggered_by_rule,
        "n_actions_blocked": ks.status.n_actions_blocked,
        "blocked_actions": ks.get_blocked_action_report()[-20:],
        "auto_recovery_enabled": ks.status.auto_recovery_enabled,
    }


@router.get("/risk/history")
def risk_history(
    cycles: int = Query(20, description="返回最近 N 次检查周期"),
    incidents_limit: int = Query(50, description="返回最近 N 条事件"),
):
    """GET /api/risk/history — 检查周期历史 + 事件历史"""
    sentinel = _get_sentinel()

    return {
        "check_cycles": sentinel.get_check_history(cycles),
        "incidents": [
            inc.to_dict()
            for inc in sentinel.incident_log.get_recent(incidents_limit)
        ],
    }


@router.get("/risk/dimensions")
def risk_dimensions():
    """GET /api/risk/dimensions — 5 维度逐项状态"""
    sentinel = _get_sentinel()
    status = sentinel.get_status()

    return {
        "dimensions": status.dimensions,
        "overall_status": status.status,
    }
