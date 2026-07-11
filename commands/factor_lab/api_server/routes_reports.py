"""Research report center for backtest and strategy reports only."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from factor_lab.api_server.response import api_success

CST = timezone(timedelta(hours=8))
router = APIRouter()


def _get_reports_base() -> Path:
    return Path(os.environ.get("HERMES_REPORTS_BASE", "/mnt/d/HermesReports"))


def _inside(base: Path, target: Path) -> Path:
    resolved = target.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise HTTPException(status_code=400, detail="Invalid report path")
    return resolved


def _discover_backtest_reports() -> list[dict]:
    directory = _get_reports_base() / "backtests"
    if not directory.exists():
        return []
    reports = []
    for item in sorted(directory.iterdir(), reverse=True):
        if not item.is_dir():
            continue
        metrics = {}
        try:
            metrics = json.loads((item / "metrics.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        reports.append({
            "id": item.name,
            "type": "backtest",
            "name": metrics.get("strategy_name", metrics.get("factor_name", item.name)),
            "factor": metrics.get("factor_name", ""),
            "created_at": metrics.get("generated_at", datetime.fromtimestamp(item.stat().st_mtime, CST).isoformat()),
            "size_bytes": sum(path.stat().st_size for path in item.iterdir() if path.is_file()),
            "metrics": {key: metrics.get(key) for key in ("sharpe", "cagr", "max_drawdown", "cumulative_return", "total_days")},
        })
    return reports


def _discover_strategy_reports() -> list[dict]:
    directory = _get_reports_base() / "strategies"
    if not directory.exists():
        return []
    reports = []
    for path in sorted(directory.glob("*/*"), reverse=True):
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}:
            reports.append({
                "id": f"{path.parent.name}/{path.name}",
                "type": "strategy",
                "name": path.stem,
                "group": path.parent.name,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, CST).isoformat(),
                "size_bytes": path.stat().st_size,
            })
    return reports


DISCOVERERS = {"backtest": _discover_backtest_reports, "strategy": _discover_strategy_reports}


def _all_reports() -> list[dict]:
    reports = [report for discover in DISCOVERERS.values() for report in discover()]
    return sorted(reports, key=lambda report: report.get("created_at", ""), reverse=True)


@router.get("/reports/health")
async def reports_health(request: Request):
    base = _get_reports_base()
    return api_success(data={"status": "ok" if base.is_dir() else "unavailable", "reports_base": str(base)}, request=request)


@router.get("/reports/summary")
async def reports_summary(request: Request):
    reports = _all_reports()
    cutoff = datetime.now(CST) - timedelta(days=7)
    recent = 0
    for report in reports:
        try:
            if datetime.fromisoformat(report["created_at"]) >= cutoff:
                recent += 1
        except (KeyError, ValueError, TypeError):
            continue
    return api_success(data={
        "total": len(reports),
        "by_type": {name: sum(1 for report in reports if report["type"] == name) for name in DISCOVERERS},
        "recent_7d": recent,
        "total_size_mb": round(sum(report.get("size_bytes", 0) for report in reports) / 1024 / 1024, 1),
        "report_base": str(_get_reports_base()),
    }, request=request)


@router.get("/reports")
async def list_reports(request: Request, type: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    if type and type not in DISCOVERERS:
        raise HTTPException(status_code=400, detail="Supported report types: backtest, strategy")
    reports = DISCOVERERS[type]() if type else _all_reports()
    return api_success(data={"total": len(reports), "offset": offset, "limit": limit, "reports": reports[offset:offset + limit]}, request=request)


@router.get("/reports/detail/{report_type}/{report_id:path}")
async def report_detail(report_type: str, report_id: str, request: Request):
    base = _get_reports_base()
    if report_type == "backtest":
        target = _inside(base, base / "backtests" / report_id)
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Report not found")
        metrics = {}
        try:
            metrics = json.loads((target / "metrics.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        payload = {"type": "backtest", "id": report_id, "metrics": metrics, "files": [path.name for path in target.iterdir() if path.is_file()]}
    elif report_type == "strategy":
        target = _inside(base, base / "strategies" / report_id)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Report not found")
        payload = {"type": "strategy", "id": report_id, "size_bytes": target.stat().st_size, "html_content": target.read_text(encoding="utf-8", errors="replace")[:20000]}
    else:
        raise HTTPException(status_code=400, detail="Supported report types: backtest, strategy")
    return api_success(data=payload, request=request)


@router.delete("/reports/{report_type}/{report_id:path}")
async def delete_report(report_type: str, report_id: str, request: Request):
    base = _get_reports_base()
    if report_type == "backtest":
        target = _inside(base, base / "backtests" / report_id)
    elif report_type == "strategy":
        target = _inside(base, base / "strategies" / report_id)
    else:
        raise HTTPException(status_code=400, detail="Supported report types: backtest, strategy")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    shutil.rmtree(target) if target.is_dir() else target.unlink()
    return api_success(data={"status": "deleted", "id": report_id}, request=request)


@router.get("/reports/recent")
async def recent_reports(request: Request, hours: int = Query(48, ge=1, le=720)):
    cutoff = datetime.now(CST) - timedelta(hours=hours)
    reports = []
    for report in _all_reports():
        try:
            if datetime.fromisoformat(report["created_at"]) >= cutoff:
                reports.append(report)
        except (KeyError, ValueError, TypeError):
            continue
    return api_success(data={"hours": hours, "total": len(reports), "reports": reports}, request=request)
