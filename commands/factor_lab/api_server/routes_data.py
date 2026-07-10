"""API Data Status routes — V7.1 数据状态 / Provider Failure UI

提供数据源健康状态、数据新鲜度、数据缺口和拉取日志的 API 端点。
核心原则: 数据失败明确展示，禁止静默 fallback。
"""
from fastapi import APIRouter, Query
from pathlib import Path
import json
import os

from datetime import datetime, timezone, timedelta

from factor_lab.api_server.response import api_response, api_success
from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.health import HealthTracker

CST = timezone(timedelta(hours=8))

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


# =========================================================================
# /api/data/coverage — 数据覆盖扫描
# /api/data/manifests — 数据清单
# 前端 DataStatus.tsx 依赖这两个端点
# =========================================================================


@router.get("/data/coverage")
async def data_coverage():
    """扫描数据目录，返回各数据集的覆盖统计（匹配 datahub 管线实际产出）"""
    import csv
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent.parent.parent  # .../research-assistant/
    data_dir = base / "data"
    kline_dir = data_dir / "market" / "daily_kline"
    norm_dir = data_dir / "normalized"
    fund_flow_dir = norm_dir / "fund_flow"
    market_dir = norm_dir / "market"
    fundamentals_dir = norm_dir / "fundamentals"

    coverage = []
    total_stocks = 0
    total_rows = 0

    # helper: 快速读 CSV 首尾行获取起止日期和行数
    def _read_csv_meta(files, date_col, symbol_col=None):
        if not files:
            return 0, "", "", 0
        dates = []
        row_count = 0
        for f in files[:50]:  # 抽样提速，但文件数少时全读
            try:
                with open(f, newline="", encoding="utf-8-sig") as fh:
                    lines = fh.readlines()
                    if len(lines) < 2:
                        continue
                    header = lines[0].strip().split(",")
                    if date_col not in header:
                        continue
                    di = header.index(date_col)
                    # 第一行数据
                    first = lines[1].strip().split(",")
                    if di < len(first):
                        dates.append(first[di])
                    # 最后一行
                    last = lines[-1].strip().split(",")
                    if di < len(last):
                        dates.append(last[di])
                    row_count += len(lines) - 1
            except Exception:
                continue
        valid = [d for d in dates if d]
        return len(files), min(valid) if valid else "", max(valid) if valid else "", row_count

    # K线日线
    if kline_dir.exists():
        kfiles = sorted(kline_dir.glob("*_daily_kline.csv"))
        if kfiles:
            all_dates = []
            for f in kfiles:
                try:
                    with open(f, newline="") as fh:
                        reader = csv.DictReader(fh)
                        rows = list(reader)
                        dates = [r.get("timeString", "") for r in rows if r.get("timeString")]
                        all_dates.extend(dates)
                except Exception:
                    continue
            valid = [d for d in all_dates if d]
            coverage.append({
                "dataset": "daily_kline",
                "stock_count": len(kfiles),
                "row_count": len(all_dates),
                "trade_days": [min(valid), max(valid)] if valid else ["", ""],
                "latest_date": max(valid) if valid else "",
                "missing_rate": 0,
            })
            total_stocks += len(kfiles)
            total_rows += len(all_dates)

    # 个股估值
    if market_dir.exists():
        mfiles = sorted(market_dir.glob("valuation_*.csv"))
        if mfiles:
            cnt, d_min, d_max, r_cnt = _read_csv_meta(mfiles, "trade_date")
            coverage.append({
                "dataset": "valuation",
                "stock_count": cnt,
                "row_count": r_cnt,
                "trade_days": [d_min, d_max] if d_min else ["", ""],
                "latest_date": d_max or "",
                "missing_rate": 0,
            })
            total_stocks += cnt
            total_rows += r_cnt

    # 个股资金流
    if fund_flow_dir.exists():
        ffiles = sorted(fund_flow_dir.glob("*.csv"))
        if ffiles:
            cnt, d_min, d_max, r_cnt = _read_csv_meta(ffiles, "trade_date")
            coverage.append({
                "dataset": "fund_flow",
                "stock_count": cnt,
                "row_count": r_cnt,
                "trade_days": [d_min, d_max] if d_min else ["", ""],
                "latest_date": d_max or "",
                "missing_rate": round((1 - cnt / 5863) * 100, 1) if cnt < 5863 else 0,
            })
            total_stocks += cnt
            total_rows += r_cnt

    # 个股基本面（新增）
    if fundamentals_dir.exists():
        fafiles = sorted(fundamentals_dir.glob("*.csv"))
        if fafiles:
            cnt, d_min, d_max, r_cnt = _read_csv_meta(fafiles, "end_date")
            coverage.append({
                "dataset": "fundamentals",
                "stock_count": cnt,
                "row_count": r_cnt,
                "trade_days": [d_min, d_max] if d_min else ["", ""],
                "latest_date": d_max or "",
                "missing_rate": round((1 - cnt / 5528) * 100, 1) if cnt < 5528 else 0,
            })
            total_stocks += cnt
            total_rows += r_cnt

    return api_success(data={
        "coverage": coverage,
        "total_stocks": total_stocks,
        "total_rows": total_rows,
    })


@router.get("/data/manifests")
async def data_manifests():
    """读取 data/manifest.json + 自动探测其他数据集的清单"""
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent.parent.parent
    data_dir = base / "data"
    manifest_file = data_dir / "manifest.json"
    norm_dir = data_dir / "normalized"
    fund_flow_dir = norm_dir / "fund_flow"
    market_dir = norm_dir / "market"
    fundamentals_dir = norm_dir / "fundamentals"

    manifests = []

    # ── manifest.json (daily_kline) ──
    if manifest_file.exists():
        with open(manifest_file) as f:
            m = json.load(f)
        manifests.append({
            "manifest_id": "main",
            "source_id": "kline_refresh",
            "dataset": "daily_kline",
            "file": str(manifest_file),
            "record_count": m.get("summary", {}).get("total_kline_files", 0),
            "file_size": manifest_file.stat().st_size,
            "file_hash": "",
            "created_at": m.get("generated_at", ""),
            "lineage": ["Tushare daily"],
            "children": [f["file"] for f in m.get("files_analyzed", [])][:20],
        })

    # ── universes.json ──
    uf = data_dir / "universes.json"
    if uf.exists():
        manifests.append({
            "manifest_id": "universes",
            "source_id": "universe_builder",
            "dataset": "universe",
            "file": str(uf),
            "record_count": uf.stat().st_size,
            "file_size": uf.stat().st_size,
            "file_hash": "",
            "created_at": datetime.fromtimestamp(uf.stat().st_mtime, tz=CST).isoformat(),
            "lineage": ["Tushare stock_basic", "Tushare daily_basic"],
            "children": ["U0", "U1", "U2", "U3", "U4", "ETF"],
        })

    # ── 自动探测: valuation ──
    if market_dir.exists():
        mfiles = sorted(market_dir.glob("valuation_*.csv"))
        if mfiles:
            total_size = sum(f.stat().st_size for f in mfiles[:100])  # 抽样
            manifests.append({
                "manifest_id": "valuation",
                "source_id": "datahub",
                "dataset": "valuation",
                "file": str(market_dir),
                "record_count": len(mfiles),
                "file_size": total_size * (len(mfiles) // 100 + 1),
                "file_hash": "",
                "created_at": datetime.fromtimestamp(mfiles[0].stat().st_mtime, tz=CST).isoformat(),
                "lineage": ["Tushare daily_basic"],
                "children": [f.name for f in mfiles[:5]] + (["..."] if len(mfiles) > 5 else []),
            })

    # ── 自动探测: fund_flow ──
    if fund_flow_dir.exists():
        ffiles = sorted(fund_flow_dir.glob("*.csv"))
        if ffiles:
            total_size = sum(f.stat().st_size for f in ffiles[:100])
            manifests.append({
                "manifest_id": "fund_flow",
                "source_id": "datahub",
                "dataset": "fund_flow",
                "file": str(fund_flow_dir),
                "record_count": len(ffiles),
                "file_size": total_size * (len(ffiles) // 100 + 1),
                "file_hash": "",
                "created_at": datetime.fromtimestamp(ffiles[0].stat().st_mtime, tz=CST).isoformat(),
                "lineage": ["Tushare fund_flow"],
                "children": [f.name for f in ffiles[:5]] + (["..."] if len(ffiles) > 5 else []),
            })

    # ── 自动探测: fundamentals ──
    if fundamentals_dir.exists():
        fafiles = sorted(fundamentals_dir.glob("*.csv"))
        if fafiles:
            total_size = sum(f.stat().st_size for f in fafiles[:100])
            manifests.append({
                "manifest_id": "fundamentals",
                "source_id": "datahub",
                "dataset": "fundamentals",
                "file": str(fundamentals_dir),
                "record_count": len(fafiles),
                "file_size": total_size * (len(fafiles) // 100 + 1),
                "file_hash": "",
                "created_at": datetime.fromtimestamp(fafiles[0].stat().st_mtime, tz=CST).isoformat(),
                "lineage": ["Tushare fina_indicator"],
                "children": [f.name for f in fafiles[:5]] + (["..."] if len(fafiles) > 5 else []),
            })

    return api_success(data={"manifests": manifests})
