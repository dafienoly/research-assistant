#!/usr/bin/env python3
"""V5 Data Integrity Check — 修复后验证 K线新鲜度、schema、U1过滤、市值字段"""
import json, os, sys, csv, glob
from datetime import datetime, timedelta, timezone

OUTPUT = None
for i, a in enumerate(sys.argv):
    if a == "--output" and i+1 < len(sys.argv):
        OUTPUT = sys.argv[i+1]

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (root, not commands/)
DATA_DIR = os.path.join(BASE, "data")
KLINE_DIR = os.path.join(DATA_DIR, "market", "daily_kline")
UNIVERSE_FILE = os.path.join(DATA_DIR, "universes.json")
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST)

def check_kline():
    """检查K线 freshness 和 schema"""
    checks = {}
    if not os.path.isdir(KLINE_DIR):
        return {"status": "FAIL", "detail": f"Kline dir not found: {KLINE_DIR}"}
    
    files = [f for f in os.listdir(KLINE_DIR) if f.endswith(".csv") and not f.startswith(".")]
    kline_files = [f for f in files if "_daily_kline" in f]
    hist_files = [f for f in files if "_hist" in f]
    
    latest_date = None
    schema_ok = True
    schema_errors = []
    zero_volume_anomalies = 0
    
    for fname in kline_files:
        fpath = os.path.join(KLINE_DIR, fname)
        with open(fpath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                continue
            # Check schema
            fields = list(rows[0].keys())
            if "code" not in fields:
                schema_errors.append(f"{fname}: missing 'code' column, fields={fields}")
                schema_ok = False
            expected = {"code", "timeString", "open", "high", "low", "close", "volume", "amount"}
            missing = expected - set(fields)
            if missing:
                schema_errors.append(f"{fname}: missing columns {missing}")
                schema_ok = False
            # Check latest date
            dates = sorted([r.get("timeString", "") for r in rows])
            if dates:
                fd = dates[-1]
                if latest_date is None or fd > latest_date:
                    latest_date = fd
            # Zero volume anomalies
            for r in rows:
                try:
                    v = float(r.get("volume", 0))
                    c = float(r.get("close", 0))
                    o = float(r.get("open", 0))
                    if v == 0 and abs(c - o) < 0.01:
                        zero_volume_anomalies += 1
                except:
                    pass
    
    # Check duplicates
    duplicates = []
    for hf in hist_files:
        base = hf.replace("_hist.csv", "")
        pair = [f for f in kline_files if base in f]
        if pair:
            hpath = os.path.join(KLINE_DIR, hf)
            ppath = os.path.join(KLINE_DIR, pair[0])
            with open(hpath) as f1, open(ppath) as f2:
                if f1.read() == f2.read():
                    duplicates.append(hf)
    
    stale_days = 999
    if latest_date:
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                ld = datetime.strptime(latest_date[:10], fmt)
                stale_days = (TODAY - ld).days
                break
            except:
                continue
    
    status = "PASS"
    if stale_days > 3:
        status = "FAIL"
    if not schema_ok:
        status = "FAIL"
    
    return {
        "status": status,
        "kline_file_count": len(kline_files),
        "hist_file_count": len(hist_files),
        "latest_date": latest_date or "N/A",
        "stale_days": stale_days,
        "schema_ok": schema_ok,
        "schema_errors": schema_errors[:5],
        "duplicate_hist_files": duplicates,
        "zero_volume_anomalies": zero_volume_anomalies,
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
