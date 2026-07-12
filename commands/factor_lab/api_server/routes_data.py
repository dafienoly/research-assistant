"""API Data Status routes — V7.1 数据状态 / Provider Failure UI

提供数据源健康状态、数据新鲜度、数据缺口和拉取日志的 API 端点。
核心原则: 数据失败明确展示，禁止静默 fallback。
"""
from collections import deque
from fastapi import APIRouter, Query
from pathlib import Path
import json

from datetime import datetime, timezone, timedelta

from factor_lab.api_server.response import api_success
from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.health import HealthTracker

CST = timezone(timedelta(hours=8))

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HEALTH_ROOT = PROJECT_ROOT / "data" / "audit" / "health"
PROJECTION_MANIFEST = PROJECT_ROOT / "data" / "audit" / "manifests" / "factor_input_projection.json"
EXPLICIT_MANIFESTS = {
    "reference": PROJECT_ROOT / "data" / "normalized" / "reference" / "manifest.json",
    "live_snapshot": PROJECT_ROOT / "data" / "normalized" / "market" / "live_snapshot.manifest.json",
    "market_turnover": PROJECT_ROOT / "data" / "normalized" / "derived" / "market_turnover" / "manifest.json",
    "benchmarks": PROJECT_ROOT / "data" / "normalized" / "derived" / "benchmarks" / "manifest.json",
    "etf_holdings": PROJECT_ROOT / "data" / "normalized" / "etf_holdings" / "holdings.manifest.json",
    "corporate_events": PROJECT_ROOT / "data" / "normalized" / "events" / "corporate_events" / "manifest.json",
    "regulatory_watchlist": PROJECT_ROOT / "data" / "normalized" / "events" / "regulatory_watchlist.manifest.json",
    "event_truth": PROJECT_ROOT / "data" / "normalized" / "events" / "event_truth" / "manifest.json",
}


def _read_json(path: Path) -> dict:
    """Read one durable manifest; never discover sibling data files."""
    if not path.is_file():
        return {"status": "MISSING", "path": str(path), "error": "manifest_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "INVALID", "path": str(path), "error": type(exc).__name__}
    if not isinstance(payload, dict):
        return {"status": "INVALID", "path": str(path), "error": "manifest_not_object"}
    return payload


def _health(name: str) -> dict:
    return _read_json(HEALTH_ROOT / name)


def _projection() -> dict:
    return _read_json(PROJECTION_MANIFEST)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


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

    return api_success(data={
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
    })


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
        "checked_at": datetime.now(CST).isoformat(),
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
    entries = deque(maxlen=limit)

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
    entries = list(reversed(entries))

    return {
        "total": len(entries),
        "entries": entries,
    }


# =========================================================================
# Internal helpers — 复用已有检查模块
# =========================================================================


def _run_freshness_check() -> dict:
    """Read the DataHub freshness manifest without rescanning CSV files."""
    report = _health("freshness.json")
    status = str(report.get("status", "MISSING")).upper()
    return {
        **report,
        "check_time": report.get("generated_at", ""),
        "overall_status": "ok" if status == "OK" else status.lower(),
        "blocking": status not in {"OK", "PARTIAL"},
        "source": "datahub:audit/health/freshness.json",
    }


def _run_gap_report() -> dict:
    """Read canonical missing-data and auxiliary projection manifests."""
    missing = _health("missing.json")
    projection = _projection()
    gaps: list[dict] = []
    missing_count = int(missing.get("missing_stocks", 0) or 0)
    if missing_count:
        gaps.append({
            "name": "canonical_market",
            "description": f"{missing_count} 个 U0 标的缺少 canonical 行情",
            "category": "market",
            "gap_type": "missing_canonical_data",
            "impact": "blocking",
            "blocking_codex": True,
            "affected_stocks": missing.get("missing_codes_sample", []),
        })
    for name, item in (projection.get("datasets") or {}).items():
        status = str((item or {}).get("status", "MISSING")).upper()
        if status not in {"OK", "COMPLETE"}:
            gaps.append({
                "name": name,
                "description": f"DataHub projection status={status}",
                "category": "auxiliary",
                "gap_type": "manifest_status",
                "impact": "partial",
                "blocking_codex": False,
                "status": status,
                "source": (item or {}).get("source"),
            })
    if not projection.get("datasets"):
        gaps.append({
            "name": "factor_input_projection",
            "description": "DataHub factor input projection manifest missing or invalid",
            "category": "auxiliary",
            "gap_type": "manifest_missing",
            "impact": "partial",
            "blocking_codex": False,
            "status": "MISSING",
        })
    return {
        "report_time": missing.get("generated_at") or projection.get("generated_at", ""),
        "source": "datahub:audit/health/missing.json+factor_input_projection.json",
        "gaps": gaps,
        "summary": {
            "total_gaps": len(gaps),
            "blocking_gaps": sum(1 for item in gaps if item.get("blocking_codex")),
            "partial_gaps": sum(1 for item in gaps if not item.get("blocking_codex")),
            "blocking_codex": any(item.get("blocking_codex") for item in gaps),
        },
    }


# =========================================================================
# /api/data/coverage — 数据覆盖扫描
# /api/data/manifests — 数据清单
# 前端 DataStatus.tsx 依赖这两个端点
# =========================================================================


@router.get("/data/coverage")
async def data_coverage():
    """Return coverage already computed by the DataHub audit pipeline."""
    report = _health("coverage.json")
    if report.get("status") == "MISSING":
        return api_success(data={"status": "MISSING", "coverage": [], "source": report})
    latest = report.get("latest_date", "")
    projection = _projection()
    projection_rows = []
    for name, item in (projection.get("datasets") or {}).items():
        item = item or {}
        projection_rows.append({
            "dataset": name,
            "stock_count": item.get("records") or item.get("symbols") or 0,
            "row_count": item.get("rows") or item.get("record_count") or 0,
            "trade_days": [item.get("start_date", ""), item.get("end_date", "")],
            "latest_date": item.get("observed_at", "") or item.get("end_date", ""),
            "missing_rate": None,
            "manifest_status": str(item.get("status", "MISSING")).upper(),
        })
    return api_success(data={
        "status": report.get("universe_status", "MISSING"),
        "source": "datahub:audit/health/coverage.json",
        "coverage": [{
            "dataset": "daily_kline",
            "stock_count": report.get("stocks_with_data", 0),
            "row_count": report.get("total_rows", 0),
            "trade_days": [report.get("earliest_date", ""), latest],
            "latest_date": latest,
            "missing_rate": 0 if not report.get("total_stocks") else round(
                100 * report.get("active_missing_files", 0) / report.get("total_stocks", 1), 3
            ),
            "manifest_status": report.get("universe_status", "MISSING"),
        }, *projection_rows],
        "total_stocks": report.get("total_stocks", 0),
        "total_rows": report.get("total_rows", 0),
        "generated_at": report.get("generated_at", ""),
    })


@router.get("/data/manifests")
async def data_manifests():
    """Return only explicit DataHub manifests and audit-health reports."""
    manifests = []
    for manifest_id, path in EXPLICIT_MANIFESTS.items():
        payload = _read_json(path)
        status = str(payload.get("status", "MISSING")).upper()
        if manifest_id == "event_truth" and (
            payload.get("run_status") != "COMPLETE"
            or any(not item.get("sha256") for item in payload.get("results", []) if isinstance(item, dict))
        ):
            status = "LEGACY_UNVERIFIED"
        manifests.append({
            "manifest_id": manifest_id,
            "source_id": payload.get("source") or "datahub",
            "dataset": manifest_id,
            "file": _display_path(path),
            "record_count": payload.get("rows") or payload.get("total_records") or payload.get("records") or 0,
            "file_size": path.stat().st_size if path.is_file() else 0,
            "file_hash": payload.get("sha256", ""),
            "created_at": payload.get("generated_at", ""),
            "lineage": [payload.get("source")] if payload.get("source") else [],
            "children": [],
            "status": status,
        })
    for name in ("coverage.json", "freshness.json", "missing.json", "integrity.json", "survivorship.json"):
        payload = _health(name)
        manifests.append({
            "manifest_id": f"audit:{name.removesuffix('.json')}",
            "source_id": "datahub:audit",
            "dataset": f"audit_{name.removesuffix('.json')}",
            "file": _display_path(HEALTH_ROOT / name),
            "record_count": payload.get("total_rows") or payload.get("files_checked") or 0,
            "file_size": (HEALTH_ROOT / name).stat().st_size if (HEALTH_ROOT / name).is_file() else 0,
            "file_hash": payload.get("sha256", ""),
            "created_at": payload.get("generated_at", ""),
            "lineage": [payload.get("source")] if payload.get("source") else [],
            "children": [],
            "status": str(payload.get("status") or payload.get("universe_status") or "MISSING").upper(),
        })
    return api_success(data={"manifests": manifests, "source": "datahub:explicit-manifests"})
