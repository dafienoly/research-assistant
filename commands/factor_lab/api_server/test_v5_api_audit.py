#!/usr/bin/env python3
"""V5 API Audit — parallel curl-subprocess approach for robust testing."""
import json, os, sys, time, subprocess, socket
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

CST = timezone(timedelta(hours=8))
BASE = "http://127.0.0.1:8766"
OUTFILE = "/home/ly/.hermes/research-assistant/data/audit/health/v5_api_audit.json"

# All GET endpoints
GET_ENDPOINTS = [
    "/api/health",
    "/api/version",
    "/api/status",
    "/api/agent-output",
    "/api/roadmap",
    "/api/roadmap/versions",
    "/api/agent-console/adapters",
    "/api/agent-console/sessions",
    "/api/versions/report/detail",
    "/api/agent-console/backups",
    "/api/backups",
    "/api/versions/report",
    "/api/data/health",
    "/api/data/sources",
    "/api/data/overview",
    "/api/data/providers",
    "/api/data/freshness",
    "/api/data/gaps",
    "/api/data/fetch-log",
    "/api/reports/health",
    "/api/reports/summary",
    "/api/reports",
    "/api/reports/backtest",
    "/api/reports/strategy",
    "/api/reports/version",
    "/api/reports/recent",
    "/api/risk/overview",
    "/api/risk/alerts",
    "/api/risk/kill-switch",
    "/api/risk/history",
    "/api/risk/dimensions",
    "/api/paper/balance",
    "/api/paper/positions",
    "/api/paper/orders",
    "/api/paper/fills",
    "/api/paper/status",
    "/api/shadow/status",
    "/api/feedback/stats",
    "/api/feedback",
    "/api/ops/health",
    "/api/ops/diagnostics",
    "/api/ops/ports",
    "/api/jobs",
    "/api/audit/events",
    "/api/universe",
    "/api/benchmarks",
    "/api/factors",
    "/api/backtests",
    "/api/portfolio/recommendation/latest",
    "/api/qmt/health",
    "/api/qmt/account",
    "/api/qmt/positions",
    "/api/live-readiness/latest",
    "/api/theme/semiconductor/status",
    "/api/theme/semiconductor/subsectors",
    "/api/theme/semiconductor/history",
    "/api/events",
    "/api/settings",
]

# POST endpoints with bodies
POST_ENDPOINTS = [
    ("/api/jobs", {"name": "test", "job_type": "generic", "params": {}}),
    ("/api/backtests/run", {"strategy": "t", "universe": "hs300"}),
    ("/api/portfolio/recommendation/run", {"strategy": "multi_factor"}),
    ("/api/live-readiness/run", {"mode": "quick"}),
    ("/api/benchmarks/build", {"name": "test_bm", "constituents": []}),
    ("/api/factors/validate", {"expression": "c>o", "name": "t"}),
    ("/api/feedback", {"title": "t", "content": "c", "category": "other"}),
    ("/api/backups", None),
    ("/api/auto-run", None),
    ("/api/ops/backup", None),
    ("/api/paper/reset", None),
]

# Maximum seconds per endpoint. /api/universe needs extra time
DEFAULT_TIMEOUT = 10
UNIVERSE_TIMEOUT = 210  # /api/universe can block for ~180s building universes


def test_endpoint(method: str, path: str, body=None, timeout_s=DEFAULT_TIMEOUT):
    """Test a single endpoint. Returns audit dict."""
    url = f"{BASE}{path}"
    result = {
        "endpoint": f"{method} {path}",
        "method": method,
        "path": path,
        "status_code": None,
        "response_time_ms": None,
        "ok_field": None,
        "has_data": None,
        "has_error": None,
        "has_meta": None,
        "has_as_of_date": None,
        "has_freshness": None,
        "has_lineage": None,
        "has_traceback": None,
        "is_mock": None,
        "error_message": None,
        "passed": False,
    }

    start = time.perf_counter()
    try:
        if body is not None:
            data = json.dumps(body).encode()
            req = Request(url, data=data, method=method)
            req.add_header("Content-Type", "application/json")
        else:
            req = Request(url, method=method)

        resp = urlopen(req, timeout=timeout_s)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        result["status_code"] = resp.status
        result["response_time_ms"] = elapsed

        raw = resp.read().decode("utf-8")
        j = json.loads(raw)

        result["ok_field"] = j.get("ok")
        result["has_data"] = "data" in j
        result["has_error"] = "error" in j
        result["has_meta"] = "meta" in j

        meta = j.get("meta", {}) or {}
        result["has_as_of_date"] = "as_of" in meta or "as_of_date" in meta
        result["has_freshness"] = "freshness" in meta or "as_of" in meta
        result["has_lineage"] = "lineage" in meta

        s = json.dumps(j).lower()
        result["has_traceback"] = "traceback" in s
        result["is_mock"] = any(kw in s for kw in ["mock", "sample", "示例数据"])

        err = j.get("error")
        if err and isinstance(err, dict):
            result["error_message"] = (err.get("message") or str(err))[:200]

        result["passed"] = (
            result["status_code"] in (200, 201, 202)
            and result["ok_field"] is not False
        )

    except HTTPError as e:
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        result["status_code"] = e.code
        result["response_time_ms"] = elapsed
        try:
            eb = json.loads(e.read().decode())
            result["ok_field"] = eb.get("ok")
            result["has_data"] = "data" in eb
            result["has_error"] = "error" in eb
            result["has_meta"] = "meta" in eb
            result["error_message"] = str(eb.get("error", {}).get("message", str(e)))[:200]
        except Exception:
            result["error_message"] = str(e)[:200]

    except (URLError, socket.timeout, OSError) as e:
        result["status_code"] = f"ERROR:{type(e).__name__}"
        result["response_time_ms"] = round((time.perf_counter() - start) * 1000, 1)
        result["error_message"] = str(e)[:200]

    except Exception as e:
        result["status_code"] = f"ERROR:{type(e).__name__}"
        result["error_message"] = str(e)[:200]

    return result


def main():
    total = len(GET_ENDPOINTS) + len(POST_ENDPOINTS)
    results = []
    passed = 0
    failed = 0

    print(f"\n{'='*70}")
    print(f"  V5 后端 API 全量审计测试 — {datetime.now(CST).isoformat()}")
    print(f"  服务器: {BASE}")
    print(f"  端点总数: {total}")
    print(f"{'='*70}\n")

    # Test GET endpoints
    for i, path in enumerate(GET_ENDPOINTS, 1):
        timeout_s = UNIVERSE_TIMEOUT if path == "/api/universe" else DEFAULT_TIMEOUT
        r = test_endpoint("GET", path, timeout_s=timeout_s)
        results.append(r)

        if r["passed"]:
            passed += 1
        else:
            failed += 1

        icon = "✅" if r["passed"] else "❌"
        em = f" — {r['error_message'][:80]}" if r["error_message"] else ""
        print(f"  ({i:2d}/{total}) {icon} GET {path} → {r['status_code']} ({r['response_time_ms']}ms){em}")

    # Test POST endpoints
    offset = len(GET_ENDPOINTS)
    for i, (path, body) in enumerate(POST_ENDPOINTS, offset + 1):
        r = test_endpoint("POST", path, body=body, timeout_s=DEFAULT_TIMEOUT)
        results.append(r)

        if r["passed"]:
            passed += 1
        else:
            failed += 1

        icon = "✅" if r["passed"] else "❌"
        em = f" — {r['error_message'][:80]}" if r["error_message"] else ""
        print(f"  ({i:2d}/{total}) {icon} POST {path} → {r['status_code']} ({r['response_time_ms']}ms){em}")

    # Summary
    rate = round(passed / total * 100, 1) if total else 0
    print(f"\n{'='*70}")
    print(f"  汇总: {passed}/{total} 通过, {failed}/{total} 失败 ({rate}%)")
    print(f"{'='*70}\n")

    # Performance stats
    times = [r["response_time_ms"] for r in results if r["response_time_ms"]]
    avg_t = round(sum(times) / len(times), 1) if times else 0
    slowest = max(results, key=lambda x: x["response_time_ms"] or 0) if results else {}

    # JSON schema compliance
    with_meta = sum(1 for r in results if r.get("has_meta"))
    with_asof = sum(1 for r in results if r.get("has_as_of_date"))

    report = {
        "report_type": "v5_api_audit",
        "generated_at": datetime.now(CST).isoformat(),
        "server_base": BASE,
        "summary": {
            "total_endpoints": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{rate}%",
        },
        "performance": {
            "avg_response_time_ms": avg_t,
            "slowest_endpoint": slowest.get("endpoint"),
            "slowest_time_ms": slowest.get("response_time_ms"),
        },
        "schema_compliance": {
            "endpoints_with_meta": with_meta,
            "endpoints_with_as_of_date": with_asof,
            "endpoints_with_freshness": sum(1 for r in results if r.get("has_freshness")),
            "endpoints_with_lineage": sum(1 for r in results if r.get("has_lineage")),
            "endpoints_with_traceback": sum(1 for r in results if r.get("has_traceback")),
            "endpoints_with_mock_data": sum(1 for r in results if r.get("is_mock")),
        },
        "endpoints": results,
    }

    os.makedirs(os.path.dirname(OUTFILE), exist_ok=True)
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  报告已写入: {OUTFILE}")


if __name__ == "__main__":
    main()
