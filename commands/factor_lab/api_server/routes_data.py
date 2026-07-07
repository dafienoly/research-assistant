"""API Data Status routes — V7.1 数据状态 / Provider Failure UI

提供数据源健康状态、数据新鲜度、数据缺口和拉取日志的 API 端点。
核心原则: 数据失败明确展示，禁止静默 fallback。
"""
from fastapi import APIRouter, Query
from pathlib import Path
import json
import os

from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.health import HealthTracker

router = APIRouter()


def _get_registry_and_tracker():
    """获取 DataRegistry 和 HealthTracker 实例"""
    registry = DataRegistry()
    tracker = HealthTracker(registry)
    return registry, tracker


@router.get("/data/overview")
async def data_overview():
    """聚合数据状态概览 — 提供给前端卡片摘要"""
    registry, tracker = _get_registry_and_tracker()
    sources = registry.list_sources()

    # 从 spec 文件加载完整健康信息
    provider_details = []
    for entry in sources:
        spec = registry.get_source(entry["source_id"])
        if spec:
            provider_details.append(spec)

    # 统计健康状态
    total = len(provider_details)
    active = sum(1 for s in provider_details if s.status == "active")
    degraded = sum(1 for s in provider_details if s.status == "degraded")
    inactive = sum(1 for s in provider_details if s.status == "inactive")
    unchecked = sum(1 for s in provider_details if s.status == "unchecked")

    # 新鲜度检查
    freshness = _run_freshness_check()
    freshness_status = freshness.get("overall_status", "unknown")
    blocking_freshness = freshness.get("blocking", False)

    # 缺口检查
    gaps = _run_gap_report()
    blocking_gaps = gaps.get("summary", {}).get("blocking_gaps", 0)
    total_gaps = gaps.get("summary", {}).get("total_gaps", 0)

    return {
        "checked_at": freshness.get("check_time", ""),
        "summary": {
            "total_sources": total,
            "active": active,
            "degraded": degraded,
            "inactive": inactive,
            "unchecked": unchecked,
            "blocking_issues": (1 if blocking_freshness else 0) + blocking_gaps,
            "freshness_status": freshness_status,
            "total_gaps": total_gaps,
        },
    }


@router.get("/data/providers")
async def data_providers(source_id: str = None):
    """数据源健康详情 — 含成功率、延迟、近期错误"""
    registry, tracker = _get_registry_and_tracker()

    if source_id:
        spec = registry.get_source(source_id)
        if spec is None:
            return {"error": f"source '{source_id}' not found"}
        specs = [spec]
    else:
        entries = registry.list_sources()
        specs = []
        for entry in entries:
            spec = registry.get_source(entry["source_id"])
            if spec:
                specs.append(spec)

    results = []
    for spec in specs:
        # 尝试获取更详细的健康报告
        try:
            report = tracker.check_health(spec.source_id)
            health_detail = {
                "success_rate": report.success_rate,
                "total_calls": report.total_calls,
                "error_count": report.error_count,
                "avg_latency_ms": report.avg_latency_ms,
                "last_check": report.last_check,
                "recent_errors": report.recent_errors,
            }
        except Exception:
            # Fallback: 使用 spec 上记录的健康摘要
            h = spec.health or {}
            health_detail = {
                "success_rate": h.get("success_rate", 100),
                "total_calls": h.get("total_calls", 0),
                "error_count": h.get("error_count", 0),
                "avg_latency_ms": h.get("avg_latency_ms", 0),
                "last_check": h.get("last_check", ""),
                "recent_errors": [],
            }

        results.append({
            "source_id": spec.source_id,
            "name": spec.name,
            "category": spec.category,
            "capabilities": spec.capabilities,
            "priority": spec.priority,
            "status": spec.status,
            "health": health_detail,
        })

    return {
        "checked_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
        ).isoformat(),
        "total": len(results),
        "sources": results,
    }


@router.get("/data/freshness")
async def data_freshness():
    """数据文件新鲜度报告"""
    report = _run_freshness_check()
    return report


@router.get("/data/gaps")
async def data_gaps():
    """数据缺口报告"""
    report = _run_gap_report()
    return report


@router.get("/data/fetch-log")
async def data_fetch_log(limit: int = Query(50, ge=1, le=500)):
    """最近数据拉取日志 — 含失败记录"""
    from config import PATHS

    fetch_log_path = PATHS["audit"] / "fetch_log.jsonl"
    entries = []

    if fetch_log_path.exists():
        with open(fetch_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    # 取最近的 limit 条
    entries.reverse()
    entries = entries[:limit]

    return {
        "total": len(entries),
        "entries": entries,
    }


# =========================================================================
# Internal helpers — 复用已有检查模块
# =========================================================================


def _run_freshness_check() -> dict:
    """运行 FreshnessChecker 检查"""
    try:
        from data_quality import FreshnessChecker

        checker = FreshnessChecker()
        report = checker.check_all()
        return report
    except Exception as e:
        return {
            "check_time": "",
            "overall_status": "error",
            "blocking": True,
            "files": [],
            "error": str(e),
        }


def _run_gap_report() -> dict:
    """运行 DataGapReporter 报告"""
    try:
        from data_quality import DataGapReporter

        reporter = DataGapReporter()
        report = reporter.report()
        return report
    except Exception as e:
        return {
            "report_time": "",
            "gaps": [],
            "summary": {"total_gaps": 0, "blocking_gaps": 0, "partial_gaps": 0, "blocking_codex": False},
            "error": str(e),
        }
