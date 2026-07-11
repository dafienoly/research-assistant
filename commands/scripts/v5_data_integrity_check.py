#!/usr/bin/env python3
"""V5 compatibility integrity report backed by canonical DataHub audits."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT = None
for i, a in enumerate(sys.argv):
    if a == "--output" and i+1 < len(sys.argv):
        OUTPUT = sys.argv[i+1]

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (root, not commands/)
DATA_DIR = os.path.join(BASE, "data")
HEALTH_DIR = Path(DATA_DIR) / "audit" / "health"
UNIVERSE_FILE = os.path.join(DATA_DIR, "universes.json")
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST)

def check_kline():
    """Validate canonical coverage, freshness and row-level integrity reports."""
    reports = {}
    errors = []
    for name in ("coverage", "freshness", "integrity"):
        path = HEALTH_DIR / f"{name}.json"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            generated = datetime.fromisoformat(str(report["generated_at"]))
            age_hours = (TODAY - generated.astimezone(CST)).total_seconds() / 3600
            if age_hours > 24:
                errors.append(f"{name} stale ({age_hours:.1f}h)")
            reports[name] = report
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{name} unavailable: {type(exc).__name__}")
    coverage = reports.get("coverage", {})
    freshness = reports.get("freshness", {})
    integrity = reports.get("integrity", {})
    passed = (
        not errors
        and coverage.get("universe_status") == "OK"
        and coverage.get("active_missing_files") == 0
        and coverage.get("empty_files") == 0
        and coverage.get("stocks_with_data") == coverage.get("total_stocks")
        and freshness.get("status") == "OK"
        and freshness.get("blocking_stock_count") == 0
        and integrity.get("status") == "OK"
        and integrity.get("problematic_file_count") == 0
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "source": "canonical_datahub_audits",
        "kline_file_count": coverage.get("stocks_with_data", 0),
        "expected_file_count": coverage.get("total_stocks", 0),
        "latest_date": coverage.get("latest_date", "N/A"),
        "freshness_status": freshness.get("status", "MISSING"),
        "integrity_status": integrity.get("status", "MISSING"),
        "problematic_file_count": integrity.get("problematic_file_count"),
        "errors": errors,
    }

def check_universe():
    """检查U1过滤和市值字段"""
    if not os.path.exists(UNIVERSE_FILE):
        return {"status": "FAIL", "detail": "universes.json not found"}
    
    with open(UNIVERSE_FILE) as f:
        data = json.load(f)
    
    universes = data.get("universes", data)
    u0 = universes.get("U0", {})
    u1 = universes.get("U1", {})
    
    u0_stocks = u0.get("stocks", u0.get("stock_list", []))
    u1_stocks = u1.get("stocks", u1.get("stock_list", []))
    
    if not u0_stocks or not u1_stocks:
        # Try alternate formats
        u0_stocks = u0 if isinstance(u0, list) else []
        u1_stocks = u1 if isinstance(u1, list) else []
    
    u0_count = len(u0_stocks) if isinstance(u0_stocks, list) else u0.get("total_stocks", 0)
    u1_count = len(u1_stocks) if isinstance(u1_stocks, list) else u1.get("total_stocks", 0)
    
    # Check U1 filtering
    delisted = 0
    st_count = 0
    name_tui = 0
    mv_nonnull = 0
    mv_total = 0
    industry_nan = 0
    
    stock_list = u1_stocks if isinstance(u1_stocks, list) else []
    for s in stock_list:
        if isinstance(s, dict):
            name = str(s.get("name", ""))
            if "退" in name:
                name_tui += 1
            if "ST" in name.upper() or "*ST" in name.upper():
                st_count += 1
            if s.get("list_status") == "D" or s.get("delist_date"):
                delisted += 1
            mv = s.get("total_mv", s.get("market_cap"))
            if mv is not None and mv != 0:
                mv_nonnull += 1
            mv_total += 1
            ind = s.get("industry", "")
            if ind == "nan" or ind == "" or ind is None:
                industry_nan += 1
    
    status = "PASS"
    if name_tui > 0:
        status = "FAIL"
    if delisted > 0:
        status = "FAIL"
    
    mv_ratio = mv_nonnull / max(mv_total, 1) * 100
    
    return {
        "status": status,
        "U0_count": u0_count,
        "U1_count": u1_count,
        "U1_is_subset": u1_count < u0_count if isinstance(u0_count, int) and isinstance(u1_count, int) else True,
        "delisted_in_U1": delisted,
        "ST_in_U1": st_count,
        "name_contains_tui_in_U1": name_tui,
        "total_mv_nonnull_ratio_pct": round(mv_ratio, 1),
        "industry_nan_count": industry_nan,
    }

def check_factor_api_consistency():
    """检查因子 API 是否已切换到真实 registry"""
    result_file = os.path.join(
        os.path.dirname(os.path.dirname(BASE)), 
        "mnt", "d", "HermesReports", "v5_1_remediation",
        "api_smoke_after.json"
    )
    if os.path.exists(result_file):
        with open(result_file) as f:
            data = json.load(f)
        for r in data.get("results", []):
            if r["endpoint"] == "/api/factors":
                return {"status": "checked", "factor_api_result_file": result_file}
    return {"status": "api_smoke_not_run_yet"}

if __name__ == "__main__":
    report = {
        "generated_at": datetime.now(CST).isoformat(),
        "kline": check_kline(),
        "universe": check_universe(),
        "factor_api": check_factor_api_consistency(),
    }
    
    print(json.dumps(report, indent=2, ensure_ascii=False))
    
    if OUTPUT:
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved to: {OUTPUT}")
