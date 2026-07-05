"""Baostock 全数据类型获取器 — 免费无限量

所有函数返回 (records, errors) 元组。
每个记录包含 pub_date/asof_date 字段用于防未来函数。
"""

import os, csv, time, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 数据目录（Hermes 内部）
BASE = Path("/home/ly/.hermes/research-assistant/data")
DIRS = {
    "fundamentals": BASE / "fundamentals",
    "tags": BASE / "tags",
    "macro": BASE / "macro",
    "market": BASE / "market",
    "features": BASE / "features",
    "audit": BASE / "audit",
}
for d in DIRS.values():
    d.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _login():
    """登录 Baostock（带 DNS 修补）"""
    try:
        import dns_patch
    except ImportError:
        pass
    import baostock as bs
    bs.login()
    return bs


def _safe_int(v, default=0):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default


def _safe_float(v, default=0.0):
    try:
        return round(float(v), 4)
    except (ValueError, TypeError):
        return default


def _write_csv(path: Path, fieldnames: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return len(rows)


def _read_symbols() -> list[str]:
    """读取现有标签中的股票代码"""
    codes = set()
    for f_name in ["semiconductor_chain_tags.csv", "stock_theme_tags.csv", "industry_chain_tags.csv"]:
        p = DIRS["tags"] / f_name
        if p.exists():
            with open(p, encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    c = row.get("code", "") or row.get("symbol", "")
                    if c:
                        codes.add(c)
    return sorted(codes)


# ====================================================================
# 基本面
# ====================================================================

def fetch_profit_data(codes: list[str] | None = None) -> tuple[int, int]:
    """盈利能力 — fundamentals/profit_data.csv"""
    bs = _login()
    if codes is None:
        codes = _read_symbols()
    rows = []
    errors = 0
    for code in codes:
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        try:
            rs = bs.query_profit_data(f"{exchange}.{code}", year=2026, quarter=1)
            row = None
            while rs.next():
                row = rs.get_row_data()
                break
            if not row or not row[3]:
                rs = bs.query_profit_data(f"{exchange}.{code}", year=2025, quarter=4)
                while rs.next():
                    row = rs.get_row_data()
                    break
            if row and len(row) > 7:
                rows.append({
                    "code": code, "report_date": row[2] or "",
                    "pub_date": row[1] or "", "asof_date": row[2] or "",
                    "roe": _safe_float(row[3]), "net_margin": _safe_float(row[4]),
                    "gross_margin": _safe_float(row[5]), "net_profit": _safe_float(row[6]),
                    "eps": _safe_float(row[7]), "source": "baostock",
                    "fetch_time": now_str(),
                })
        except Exception:
            errors += 1
        time.sleep(0.05)
    bs.logout()
    n = _write_csv(DIRS["fundamentals"] / "profit_data.csv",
                    ["code", "report_date", "pub_date", "asof_date", "roe", "net_margin",
                     "gross_margin", "net_profit", "eps", "source", "fetch_time"], rows)
    return n, errors


def fetch_balance_data(codes: list[str] | None = None) -> tuple[int, int]:
    """资产负债表 — fundamentals/balance_data.csv"""
    bs = _login()
    if codes is None:
        codes = _read_symbols()
    rows = []
    errors = 0
    for code in codes:
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        try:
            rs = bs.query_balance_data(f"{exchange}.{code}", year=2026, quarter=1)
            row = None
            while rs.next():
                row = rs.get_row_data()
                break
            if not row or not row[3]:
                rs = bs.query_balance_data(f"{exchange}.{code}", year=2025, quarter=4)
                while rs.next():
                    row = rs.get_row_data()
                    break
            if row and len(row) > 7:
                rows.append({
                    "code": code, "report_date": row[2] or "", "pub_date": row[1] or "",
                    "asof_date": row[2] or "",
                    "total_assets": _safe_float(row[3]), "total_liab": _safe_float(row[4]),
                    "debt_ratio": _safe_float(row[5]), "current_assets": _safe_float(row[6]),
                    "current_liab": _safe_float(row[7]),
                    "source": "baostock", "fetch_time": now_str(),
                })
        except Exception:
            errors += 1
        time.sleep(0.05)
    bs.logout()
    n = _write_csv(DIRS["fundamentals"] / "balance_data.csv",
                    ["code", "report_date", "pub_date", "asof_date", "total_assets",
                     "total_liab", "debt_ratio", "current_assets", "current_liab",
                     "source", "fetch_time"], rows)
    return n, errors


def fetch_cash_flow_data(codes: list[str] | None = None) -> tuple[int, int]:
    """现金流量 — fundamentals/cash_flow_data.csv"""
    bs = _login()
    if codes is None:
        codes = _read_symbols()
    rows = []
    errors = 0
    for code in codes:
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        try:
            rs = bs.query_cash_flow_data(f"{exchange}.{code}", year=2025, quarter=4)
            while rs.next():
                row = rs.get_row_data()
                if row and len(row) > 5:
                    rows.append({
                        "code": code, "report_date": row[2] or "", "pub_date": row[1] or "",
                        "asof_date": row[2] or "",
                        "ocf": _safe_float(row[3]), "icf": _safe_float(row[4]),
                        "fcf": _safe_float(row[5]),
                        "source": "baostock", "fetch_time": now_str(),
                    })
                    break
        except Exception:
            errors += 1
        time.sleep(0.05)
    bs.logout()
    n = _write_csv(DIRS["fundamentals"] / "cash_flow_data.csv",
                    ["code", "report_date", "pub_date", "asof_date", "ocf", "icf", "fcf",
                     "source", "fetch_time"], rows)
    return n, errors


def fetch_forecast_report(codes: list[str] | None = None) -> tuple[int, int]:
    """业绩预告 — fundamentals/forecast_report.csv"""
    bs = _login()
    if codes is None:
        codes = _read_symbols()
    rows = []
    errors = 0
    for code in codes:
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        try:
            rs = bs.query_forecast_report(f"{exchange}.{code}", "2026-01-01", "2026-12-31")
            while rs.next():
                row = rs.get_row_data()
                if row and len(row) > 4 and row[2]:
                    rows.append({
                        "code": code, "pub_date": row[1] or "", "report_date": row[2] or "",
                        "asof_date": row[2] or "",
                        "type": row[3] or "", "profit_range": row[4] or "",
                        "source": "baostock", "fetch_time": now_str(),
                    })
                    break
        except Exception:
            errors += 1
        time.sleep(0.05)
    bs.logout()
    n = _write_csv(DIRS["fundamentals"] / "forecast_report.csv",
                    ["code", "pub_date", "report_date", "asof_date", "type", "profit_range",
                     "source", "fetch_time"], rows)
    return n, errors


# ====================================================================
# 复权因子
# ====================================================================

def fetch_adjust_factor(codes: list[str] | None = None) -> tuple[int, int]:
    """复权因子 — market/adjust_factor.csv"""
    bs = _login()
    if codes is None:
        codes = _read_symbols()
    rows = []
    errors = 0
    for code in codes:
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        try:
            rs = bs.query_adjust_factor(f"{exchange}.{code}")
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) >= 4:
                    rows.append({
                        "code": code, "date": r[1] or "",
                        "adjust_factor": _safe_float(r[2], 1.0),
                        "dividend": _safe_float(r[3], 0.0),
                        "source": "baostock", "fetch_time": now_str(),
                    })
        except Exception:
            errors += 1
        time.sleep(0.1)
    bs.logout()
    n = _write_csv(DIRS["market"] / "adjust_factor.csv",
                    ["code", "date", "adjust_factor", "dividend", "source", "fetch_time"], rows)
    return n, errors


# ====================================================================
# 股票分类
# ====================================================================

def fetch_stock_industry(codes: list[str] | None = None) -> tuple[int, int]:
    """行业分类 — tags/stock_industry.csv"""
    bs = _login()
    if codes is None:
        codes = _read_symbols()
    rows = []
    errors = 0
    for code in codes:
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        try:
            rs = bs.query_stock_industry(f"{exchange}.{code}")
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) >= 4:
                    rows.append({
                        "code": code, "name": r[2], "industry": r[3],
                        "industry_type": r[4] if len(r) > 4 else "",
                        "asof_date": r[0] if r[0] else now_str()[:10],
                        "source": "baostock", "fetch_time": now_str(),
                    })
                    break
        except Exception:
            errors += 1
        time.sleep(0.05)
    bs.logout()
    n = _write_csv(DIRS["tags"] / "stock_industry.csv",
                    ["code", "name", "industry", "industry_type", "asof_date",
                     "source", "fetch_time"], rows)
    return n, errors


def fetch_index_constituents() -> tuple[int, int]:
    """指数成分股 — tags/index_membership.csv"""
    bs = _login()
    rows = []
    errors = 0
    for idx_name, idx_func in [
        ("hs300", bs.query_hs300_stocks),
        ("sz50", bs.query_sz50_stocks),
        ("zz500", bs.query_zz500_stocks),
    ]:
        try:
            rs = idx_func("2026-07-03")
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) >= 2:
                    code_long = r[0].strip() if r[0] else ""
                    code_short = code_long.split(".")[1] if "." in code_long else code_long
                    name = r[1] if len(r) > 1 else ""
                    rows.append({
                        "code": code_short, "name": name, "index": idx_name,
                        "asof_date": "2026-07-03",
                        "source": "baostock", "fetch_time": now_str(),
                    })
        except Exception:
            errors += 1
    bs.logout()
    n = _write_csv(DIRS["tags"] / "index_membership.csv",
                    ["code", "name", "index", "asof_date", "source", "fetch_time"], rows)
    return n, errors


# ====================================================================
# 宏观数据
# ====================================================================

def fetch_macro_data() -> dict:
    """宏观数据 — macro/*.csv"""
    bs = _login()
    results = {}
    for name, func, fields in [
        ("cpi", bs.query_cpi_data, ["date", "cpi_yoy", "cpi_mom", "cpi_accu"]),
        ("ppi", bs.query_ppi_data, ["date", "ppi_yoy", "ppi_mom"]),
        ("pmi", bs.query_pmi_data, ["date", "pmi", "pmi_yoy"]),
        ("deposit_rate", bs.query_deposit_rate_data, ["date", "deposit_rate"]),
        ("loan_rate", bs.query_loan_rate_data, ["date", "loan_rate_1y", "loan_rate_5y"]),
        ("m2", bs.query_money_supply_data_month, ["date", "m2", "m2_yoy"]),
    ]:
        try:
            rs = func("2020-01-01", "2026-12-31")
            rows = []
            while rs.next():
                r = rs.get_row_data()
                if r and r[0]:
                    row = {"date": r[0], "source": "baostock", "fetch_time": now_str()}
                    for i, f in enumerate(fields[1:], 1):
                        if i < len(r):
                            row[f] = _safe_float(r[i])
                    rows.append(row)
            n = _write_csv(DIRS["macro"] / f"{name}.csv", fields + ["source", "fetch_time"], rows)
            results[name] = n
        except Exception as e:
            results[name] = f"ERR:{e}"
    bs.logout()
    return results


# ====================================================================
# 特征工程
# ====================================================================

def build_fundamental_features(codes: list[str] | None = None) -> int:
    """构建基本面因子 — features/fundamental_features.csv"""
    if codes is None:
        codes = _read_symbols()
    rows = []
    profit = {}
    for p in [DIRS["fundamentals"] / "profit_data.csv",
              DIRS["fundamentals"] / "balance_data.csv",
              DIRS["fundamentals"] / "cash_flow_data.csv"]:
        if p.exists():
            with open(p, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if r.get("code") not in profit:
                        profit[r["code"]] = {}
                    profit[r["code"]].update(r)

    for code in codes:
        d = profit.get(code, {})
        roe = _safe_float(d.get("roe"))
        nm = _safe_float(d.get("net_margin"))
        gm = _safe_float(d.get("gross_margin"))
        dr = _safe_float(d.get("debt_ratio"))
        ocf = _safe_float(d.get("ocf"))
        np = _safe_float(d.get("net_profit"))

        quality = min(100, max(0, (roe * 100 + nm * 100 + gm * 50) / 2.5))
        growth = min(100, max(0, (roe * 100 + np / 1e8) / 2))
        cashflow = min(100, max(0, 50 + (ocf / 1e8) * 5)) if ocf else 30
        balance_risk = min(100, max(0, dr * 100)) if dr else 50

        rows.append({
            "symbol": code, "name": d.get("name", ""),
            "report_date": d.get("report_date", ""),
            "pub_date": d.get("pub_date", ""),
            "roe": roe, "net_margin": nm, "gross_margin": gm,
            "debt_ratio": dr, "ocf_to_np": ocf / np if np else 0,
            "quality_score": round(quality, 1),
            "growth_score": round(growth, 1),
            "cashflow_score": round(cashflow, 1),
            "balance_risk_score": round(balance_risk, 1),
            "updated_at": now_str(),
        })

    n = _write_csv(DIRS["features"] / "fundamental_features.csv",
                    ["symbol", "name", "report_date", "pub_date", "roe", "net_margin",
                     "gross_margin", "debt_ratio", "ocf_to_np",
                     "quality_score", "growth_score", "cashflow_score",
                     "balance_risk_score", "updated_at"], rows)
    return n


def run_all(codes: list[str] | None = None) -> dict:
    """运行全部 Baostock 数据更新"""
    if codes is None:
        codes = _read_symbols()
    print(f"Baostock 全量更新: {len(codes)} 只股票")
    results = {}

    for name, fn in [
        ("profit_data", lambda: fetch_profit_data(codes)),
        ("balance_data", lambda: fetch_balance_data(codes)),
        ("cash_flow_data", lambda: fetch_cash_flow_data(codes)),
        ("forecast_report", lambda: fetch_forecast_report(codes)),
        ("adjust_factor", lambda: fetch_adjust_factor(codes)),
        ("stock_industry", lambda: fetch_stock_industry(codes)),
        ("index_constituents", lambda: fetch_index_constituents()),
        ("macro", lambda: fetch_macro_data()),
    ]:
        try:
            r = fn()
            results[name] = r
            if isinstance(r, tuple):
                print(f"  {name}: {r[0]} 条, {r[1]} 错误")
            elif isinstance(r, dict):
                print(f"  {name}: {r}")
        except Exception as e:
            results[name] = f"ERR:{e}"
            print(f"  {name}: FAILED - {e}")

    # 特征工程
    try:
        n = build_fundamental_features(codes)
        print(f"  fundamental_features: {n} 条")
        results["fundamental_features"] = n
    except Exception as e:
        results["fundamental_features"] = f"ERR:{e}"

    return results


if __name__ == "__main__":
    run_all()
