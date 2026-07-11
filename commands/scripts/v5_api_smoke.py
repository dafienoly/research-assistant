#!/usr/bin/env python3
"""V5 API Smoke Test — 修复后快速验证核心端点"""
import json, sys, time, os
import urllib.request, urllib.error

BASE = "http://127.0.0.1:8766"
OUTPUT = None
_skip = False
for i, a in enumerate(sys.argv[1:]):
    if _skip:
        _skip = False
        continue
    if a == "--output" and i+2 < len(sys.argv):
        OUTPUT = sys.argv[i+2]
        _skip = True
    elif a.startswith("--base="):
        BASE = a.split("=", 1)[1]
    elif a.startswith("http"):
        BASE = a

ENDPOINTS = [
    ("GET", "/api/health"),
    ("GET", "/api/status"),
    ("GET", "/api/factors"),
    ("GET", "/api/factors/ret5"),
    ("GET", "/api/factors/ret10"),
    ("GET", "/api/factors/max_high60"),
    ("GET", "/api/universe"),
    ("GET", "/api/universe/U0"),
    ("GET", "/api/universe/U1"),
    ("GET", "/api/data/health"),
    ("GET", "/api/reports"),
    ("GET", "/api/reports/summary"),
    ("GET", "/api/versions/report/detail"),
]

def smoke_test():
    results = []
    failures = 0
    for method, path in ENDPOINTS:
        url = BASE + path
        t0 = time.time()
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                latency = round((time.time() - t0) * 1000, 1)
                body = json.loads(resp.read())
                status = resp.status
                has_traceback = "Traceback" in json.dumps(body)
                has_mock = any(k in json.dumps(body).lower() for k in ["_sample_factors", "mock", "demo", "fake"])
                results.append({
                    "endpoint": path, "method": method, "status_code": status,
                    "latency_ms": latency, "ok": body.get("ok", None),
                    "has_data": body.get("data") is not None,
                    "has_meta": body.get("meta") is not None,
                    "has_traceback": has_traceback,
                    "is_mock": has_mock,
                    "error": body.get("error"),
                    "passed": status == 200 and not has_traceback and not has_mock,
                })
                if status != 200:
                    failures += 1
        except Exception as e:
            latency = round((time.time() - t0) * 1000, 1)
            results.append({
                "endpoint": path, "method": method, "status_code": 0,
                "latency_ms": latency, "ok": False, "has_data": False,
                "has_meta": False, "has_traceback": False, "is_mock": False,
                "error": str(e), "passed": False,
            })
            failures += 1

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "server_base": BASE,
        "summary": {
            "total": len(results), "passed": len(results) - failures,
            "failed": failures, "pass_rate": f"{(len(results)-failures)/len(results)*100:.1f}%",
        },
        "results": results,
    }
    
    # Factor count check
    factor_result = next((r for r in results if r["endpoint"] == "/api/factors"), None)
    if factor_result and factor_result.get("ok"):
        # will be checked in detail by the test
        pass
    
    print(json.dumps(report, indent=2, ensure_ascii=False))
    
    if OUTPUT:
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved to: {OUTPUT}")
    
    return failures == 0

if __name__ == "__main__":
    ok = smoke_test()
    sys.exit(0 if ok else 1)
