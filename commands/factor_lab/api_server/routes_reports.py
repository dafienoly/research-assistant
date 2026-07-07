"""Report Center API routes — V7.5 统一报告管理中心

提供对 HermesReports 目录下所有报告的发现、查看、管理接口:
  - backtest:   <REPORTS_BASE>/backtests/<factor>/report.html / metrics.json
  - strategy:   <REPORTS_BASE>/strategies/<group>/<report_name>.html
  - version:    <REPORTS_BASE>/version_reports/completion_*.json / version_report_*.json
  - session:    <REPORTS_BASE>/session_backups/<sid>/
  - roadmap:    <REPORTS_BASE>/roadmap_backups/<backup>/

可通过环境变量 HERMES_REPORTS_BASE 自定义报告根目录，默认 /mnt/d/HermesReports。
"""
import json, os, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Query

CST = timezone(timedelta(hours=8))

router = APIRouter()


# ──────────────────────────────────────────────
# 报告根目录（运行时读取环境变量，方便测试时动态切换）
# ──────────────────────────────────────────────

def _get_reports_base() -> Path:
    """返回 HermesReports 根目录（优先读环境变量，否则用默认值）"""
    return Path(os.environ.get("HERMES_REPORTS_BASE", "/mnt/d/HermesReports"))


def _healthy() -> dict:
    """检查报告中心基础目录状态"""
    base = _get_reports_base()
    return {
        "reports_base": str(base),
        "exists": base.exists(),
        "is_dir": base.is_dir() if base.exists() else False,
        "subdirs": sorted(
            [d.name for d in base.iterdir() if d.is_dir()]
        ) if base.exists() else [],
    }


def _ensure_base() -> bool:
    """确保基础目录存在，返回是否可用"""
    base = _get_reports_base()
    return base.exists() and base.is_dir()


def _parse_timestamp(ts_str: str) -> datetime:
    """容忍多种时间戳格式的解析"""
    for fmt in ("%Y%m%d_%H%M%S", "%Y-%m-%dT%H-%M-%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y%m%d%H%M%S", "iso8601"):
        if fmt == "iso8601":
            try:
                return datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
        try:
            return datetime.strptime(ts_str, fmt)
        except (ValueError, TypeError):
            continue
    # fallback: 从文件名提取第一个日期模式
    import re
    m = re.search(r"(\d{8})_?(\d{6})?", ts_str)
    if m:
        date_part = m.group(1)
        time_part = m.group(2) or "000000"
        try:
            return datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    return datetime.now(CST)


def _file_age_hours(path: Path) -> float:
    """文件存在时间（小时）"""
    if not path.exists():
        return 0
    return (datetime.now(CST).timestamp() - path.stat().st_mtime) / 3600


def _suffix_popular(report_type: str) -> tuple:
    """返回 (display_name, icon)"""
    M = {
        "backtest": ("回测报告", "📊"),
        "strategy": ("策略报告", "📈"),
        "version":  ("版本报告", "📋"),
        "session":  ("Session备份", "💾"),
        "roadmap":  ("路线图备份", "🗺️"),
        "all":      ("全部报告", "📁"),
    }
    return M.get(report_type, (report_type, "📄"))


# ──────────────────────────────────────────────
# 发现报告
# ──────────────────────────────────────────────

def _discover_backtest_reports() -> list[dict]:
    """发现所有回测报告"""
    base = _get_reports_base()
    results = []
    bt_dir = base / "backtests"
    if not bt_dir.exists():
        return results
    for sub in sorted(bt_dir.iterdir(), reverse=True):
        if not sub.is_dir():
            continue
        metrics_file = sub / "metrics.json"
        html_file = sub / "report.html"
        # 优先从 metrics.json 读取元信息
        meta = {}
        if metrics_file.exists():
            try:
                meta = json.loads(metrics_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        results.append({
            "id": sub.name,
            "type": "backtest",
            "name": meta.get("strategy_name", meta.get("factor_name", sub.name)),
            "factor": meta.get("factor_name", ""),
            "created_at": meta.get("generated_at", datetime.fromtimestamp(sub.stat().st_mtime, tz=CST).isoformat()),
            "size_bytes": sum(f.stat().st_size for f in sub.iterdir() if f.is_file()) if sub.exists() else 0,
            "metrics": {
                "sharpe": meta.get("sharpe"),
                "cagr": meta.get("cagr"),
                "max_drawdown": meta.get("max_drawdown"),
                "cumulative_return": meta.get("cumulative_return"),
                "total_days": meta.get("total_days"),
            },
            "has_html": html_file.exists(),
            "has_csv": (sub / "returns.csv").exists(),
            "path": str(sub),
        })
    return results


def _discover_strategy_reports() -> list[dict]:
    """发现所有策略报告（HTML）"""
    base = _get_reports_base()
    results = []
    strat_dir = base / "strategies"
    if not strat_dir.exists():
        return results
    for group in sorted(strat_dir.iterdir(), reverse=True):
        if not group.is_dir():
            continue
        for f in sorted(group.iterdir(), reverse=True):
            if f.suffix.lower() in (".html", ".htm"):
                # 从文件名提取信息
                name = f.stem
                size = f.stat().st_size
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=CST).isoformat()
                results.append({
                    "id": f"{group.name}/{f.name}",
                    "type": "strategy",
                    "name": name,
                    "group": group.name,
                    "created_at": mtime,
                    "size_bytes": size,
                    "has_html": True,
                    "path": str(f),
                })
    return results


def _discover_version_reports() -> list[dict]:
    """发现所有版本完成报告（JSON）"""
    base = _get_reports_base()
    results = []
    vr_dir = base / "version_reports"
    if not vr_dir.exists():
        return results
    for f in sorted(vr_dir.iterdir(), reverse=True):
        if not f.is_file() or f.suffix != ".json":
            continue
        if f.name == "latest.json":
            continue
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # 兼容 completion_ 和 version_report_ 两种前缀
        is_completion = f.name.startswith("completion_")
        version = data.get("version", "")
        name = data.get("name", "")
        status = data.get("status", "completed" if is_completion else "report")
        # completion 文件包含 commits / files_changed
        commits = data.get("commits", [])
        files_changed = data.get("files_changed", [])
        results.append({
            "id": f.name,
            "type": "version",
            "version": version,
            "name": name or (f"Version {version}" if version else f.stem),
            "status": status,
            "is_completion": is_completion,
            "created_at": data.get("completed_at", data.get("generated_at",
                            datetime.fromtimestamp(f.stat().st_mtime, tz=CST).isoformat())),
            "size_bytes": f.stat().st_size,
            "commits": commits,
            "files_changed": files_changed,
            "path": str(f),
        })
    return results


def _discover_session_backups() -> list[dict]:
    """发现 Session 备份"""
    base = _get_reports_base()
    results = []
    sb_dir = base / "session_backups"
    if not sb_dir.exists():
        return results
    for d in sorted(sb_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        summary = {}
        sf = d / "summary.json"
        if sf.exists():
            try:
                summary = json.loads(sf.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        req = {}
        rf = d / "request.json"
        if rf.exists():
            try:
                req = json.loads(rf.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        results.append({
            "id": d.name,
            "type": "session",
            "name": f"Session {d.name[:22]}...",
            "agent": req.get("agent", ""),
            "prompt_preview": req.get("prompt", "")[:120],
            "status": summary.get("status", "unknown"),
            "created_at": req.get("created_at", ""),
            "size_bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.exists() else 0,
            "path": str(d),
        })
    return results


def _discover_roadmap_backups() -> list[dict]:
    """发现路线图备份"""
    base = _get_reports_base()
    results = []
    rb_dir = base / "roadmap_backups"
    if not rb_dir.exists():
        return results
    for d in sorted(rb_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        has_json = any(f.suffix == ".json" for f in d.iterdir())
        name = d.name
        mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=CST).isoformat()
        results.append({
            "id": d.name,
            "type": "roadmap",
            "name": name,
            "created_at": mtime,
            "size_bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.exists() else 0,
            "has_json": has_json,
            "path": str(d),
        })
    return results


_REPORT_DISCOVERERS = {
    "backtest": _discover_backtest_reports,
    "strategy": _discover_strategy_reports,
    "version":  _discover_version_reports,
    "session":  _discover_session_backups,
    "roadmap":  _discover_roadmap_backups,
}


def _discover_all() -> list[dict]:
    """发现所有类型的报告"""
    all_reports = []
    for discoverer in _REPORT_DISCOVERERS.values():
        all_reports.extend(discoverer())
    # 按创建时间倒序
    all_reports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return all_reports


# ──────────────────────────────────────────────
# API 端点
# ──────────────────────────────────────────────

@router.get("/reports/health")
async def reports_health():
    """报告中心健康检查"""
    h = _healthy()
    status = "ok" if h["exists"] else "unavailable"
    return {"status": status, **h}


@router.get("/reports/summary")
async def reports_summary():
    """报告中心概览统计"""
    if not _ensure_base():
        base = _get_reports_base()
        return {
            "total": 0, "by_type": {}, "recent_7d": 0,
            "total_size_mb": 0.0, "report_base": str(base),
            "error": "reports base not accessible",
            "generated_at": datetime.now(CST).isoformat(),
        }
    backtests = _discover_backtest_reports()
    strategies = _discover_strategy_reports()
    versions = _discover_version_reports()
    sessions = _discover_session_backups()
    roadmaps = _discover_roadmap_backups()

    total = len(backtests) + len(strategies) + len(versions) + len(sessions) + len(roadmaps)

    # 最近 7 天的报告
    seven_days_ago = datetime.now(CST).timestamp() - 7 * 86400
    recent = 0
    for r in _discover_all():
        ts = r.get("created_at", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                if dt.timestamp() > seven_days_ago:
                    recent += 1
            except (ValueError, TypeError):
                pass

    # 总大小
    total_bytes = sum(
        r.get("size_bytes", 0) for r in [*backtests, *strategies, *versions, *sessions, *roadmaps]
    )

    return {
        "total": total,
        "by_type": {
            "backtest": len(backtests),
            "strategy": len(strategies),
            "version": len(versions),
            "session": len(sessions),
            "roadmap": len(roadmaps),
        },
        "recent_7d": recent,
        "total_size_mb": round(total_bytes / (1024 * 1024), 1),
        "report_base": str(_get_reports_base()),
        "generated_at": datetime.now(CST).isoformat(),
    }


@router.get("/reports")
async def list_reports(
    type: Optional[str] = Query(None, description="过滤类型: backtest/strategy/version/session/roadmap"),
    sort: Optional[str] = Query("created_at", description="排序字段"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出报告，支持类型过滤和分页"""
    if not _ensure_base():
        return {"total": 0, "offset": offset, "limit": limit, "type": type or "all",
                "display_name": "全部报告", "icon": "📁", "reports": [],
                "error": "reports base not accessible"}
    if type and type in _REPORT_DISCOVERERS:
        all_reports = _REPORT_DISCOVERERS[type]()
    else:
        all_reports = _discover_all()
    total = len(all_reports)
    page = all_reports[offset:offset + limit]
    display_name, icon = _suffix_popular(type or "all")
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "type": type or "all",
        "display_name": display_name,
        "icon": icon,
        "reports": page,
    }


@router.get("/reports/backtest")
async def list_backtest_reports(limit: int = Query(50, ge=1, le=200)):
    """列出所有回测报告"""
    reports = _discover_backtest_reports()
    return {"total": len(reports), "reports": reports[:limit]}


@router.get("/reports/strategy")
async def list_strategy_reports(limit: int = Query(50, ge=1, le=200)):
    """列出所有策略报告"""
    reports = _discover_strategy_reports()
    return {"total": len(reports), "reports": reports[:limit]}


@router.get("/reports/version")
async def list_version_reports(limit: int = Query(50, ge=1, le=200)):
    """列出所有版本报告"""
    reports = _discover_version_reports()
    return {"total": len(reports), "reports": reports[:limit]}


@router.get("/reports/detail/{report_type}/{report_id:path}")
async def report_detail(report_type: str, report_id: str):
    """获取单个报告的详细内容"""
    if report_type == "backtest":
        return _backtest_detail(report_id)
    elif report_type == "strategy":
        return _strategy_detail(report_id)
    elif report_type == "version":
        return _version_detail(report_id)
    elif report_type == "session":
        return _session_detail(report_id)
    elif report_type == "roadmap":
        return _roadmap_detail(report_id)
    return {"error": f"unknown report type: {report_type}"}


@router.delete("/reports/{report_type}/{report_id:path}")
async def delete_report(report_type: str, report_id: str):
    """删除指定报告"""
    base = _get_reports_base()
    if not _ensure_base():
        return {"error": "reports base not accessible", "path": str(base)}
    if report_type == "backtest":
        target = base / "backtests" / report_id
    elif report_type == "strategy":
        target = base / "strategies" / report_id
        # report_id may be group/filename
        parts = report_id.split("/", 1)
        if len(parts) == 2:
            target = base / "strategies" / parts[0] / parts[1]
        else:
            # search
            targets = list(base.rglob(report_id))
            target = targets[0] if targets else None
    elif report_type == "version":
        target = base / "version_reports" / report_id
    elif report_type == "session":
        target = base / "session_backups" / report_id
    elif report_type == "roadmap":
        target = base / "roadmap_backups" / report_id
    else:
        return {"error": f"unknown report type: {report_type}"}

    if target is None or not target.exists():
        return {"error": "not found", "path": str(target) if target else report_id}

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"status": "deleted", "path": str(target)}
    except OSError as e:
        return {"error": str(e)}


@router.get("/reports/recent")
async def recent_reports(hours: int = Query(48, ge=1, le=720)):
    """最近 hours 小时内生成的报告"""
    cutoff = datetime.now(CST).timestamp() - hours * 3600
    recent = []
    for r in _discover_all():
        ts = r.get("created_at", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts) if "T" in ts else datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.timestamp() >= cutoff:
                recent.append(r)
        except (ValueError, TypeError):
            continue
    return {"hours": hours, "total": len(recent), "reports": recent}


# ──────────────────────────────────────────────
# 各类型报告的详细内容
# ──────────────────────────────────────────────

def _backtest_detail(report_id: str) -> dict:
    base = _get_reports_base()
    bt_dir = base / "backtests" / report_id
    if not bt_dir.exists():
        return {"error": "not found"}
    metrics = {}
    metrics_file = bt_dir / "metrics.json"
    if metrics_file.exists():
        try:
            metrics = json.loads(metrics_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    # 读取 HTML 内容（截取前几 KB 用于预览）
    html_content = ""
    html_file = bt_dir / "report.html"
    if html_file.exists():
        try:
            html_content = html_file.read_text(encoding="utf-8")[:50000]
        except (OSError, UnicodeDecodeError):
            pass
    # 读取 CSV 摘要
    returns_csv = ""
    csv_file = bt_dir / "returns.csv"
    if csv_file.exists():
        try:
            returns_csv = csv_file.read_text(encoding="utf-8")[:5000]
        except (OSError, UnicodeDecodeError):
            pass
    return {
        "id": report_id,
        "type": "backtest",
        "metrics": metrics,
        "html_content": html_content,
        "html_path": str(html_file) if html_file.exists() else "",
        "returns_csv": returns_csv,
        "files": [f.name for f in bt_dir.iterdir() if f.is_file()],
    }


def _strategy_detail(report_id: str) -> dict:
    base = _get_reports_base()
    parts = report_id.split("/", 1)
    if len(parts) == 2:
        target = base / "strategies" / parts[0] / parts[1]
    else:
        targets = list(base.rglob(report_id))
        target = targets[0] if targets else None
    if target is None or not target.exists():
        return {"error": "not found"}
    html_content = ""
    if target.suffix.lower() in (".html", ".htm"):
        try:
            html_content = target.read_text(encoding="utf-8")[:50000]
        except (OSError, UnicodeDecodeError):
            pass
    return {
        "id": report_id,
        "type": "strategy",
        "html_content": html_content,
        "html_path": str(target),
        "size_bytes": target.stat().st_size,
    }


def _version_detail(report_id: str) -> dict:
    base = _get_reports_base()
    target = base / "version_reports" / report_id
    if not target.exists():
        return {"error": "not found"}
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return {"error": "invalid json"}
    return {
        "id": report_id,
        "type": "version",
        "data": data,
        "size_bytes": target.stat().st_size,
    }


def _session_detail(report_id: str) -> dict:
    base = _get_reports_base()
    sd_dir = base / "session_backups" / report_id
    if not sd_dir.exists():
        return {"error": "not found"}
    summary = {}
    sf = sd_dir / "summary.json"
    if sf.exists():
        try:
            summary = json.loads(sf.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    req = {}
    rf = sd_dir / "request.json"
    if rf.exists():
        try:
            req = json.loads(rf.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    answer = ""
    af = sd_dir / "answer.md"
    if af.exists():
        try:
            answer = af.read_text(encoding="utf-8")[:50000]
        except (OSError, UnicodeDecodeError):
            pass
    return {
        "id": report_id,
        "type": "session",
        "summary": summary,
        "request": req,
        "answer_preview": answer[:2000],
        "answer_full": answer,
        "files": [f.name for f in sd_dir.iterdir() if f.is_file()],
    }


def _roadmap_detail(report_id: str) -> dict:
    base = _get_reports_base()
    rb_dir = base / "roadmap_backups" / report_id
    if not rb_dir.exists():
        return {"error": "not found"}
    json_files = [f.name for f in rb_dir.iterdir() if f.suffix == ".json"]
    content = {}
    for jf in rb_dir.glob("*.json"):
        try:
            content[jf.name] = json.loads(jf.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "id": report_id,
        "type": "roadmap",
        "content": content,
        "json_files": json_files,
        "total_files": sum(1 for _ in rb_dir.iterdir()),
    }
