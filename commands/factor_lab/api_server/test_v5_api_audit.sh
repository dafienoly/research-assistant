#!/bin/bash
# V5 API audit test — robust per-endpoint testing with timeouts
# Tests all 60+ GET/POST endpoints, outputs JSON audit report

set -u

BASE="http://127.0.0.1:8766"
OUTFILE="/home/ly/.hermes/research-assistant/data/audit/health/v5_api_audit.json"
TMPDIR=$(mktemp -d)
TIMEOUT=8  # per-endpoint timeout (seconds)

results='[]'
passed=0
failed=0
total=0

# Cleanup on exit
trap "rm -rf $TMPDIR" EXIT

test_endpoint() {
    local method="$1"
    local path="$2"
    local body_file="$3"  # empty string means no body
    local total=$4
    local idx=$5

    local url="${BASE}${path}"
    local start=$(date +%s%N)

    local outfile="$TMPDIR/result_${idx}.json"
    local http_code=""
    local err_msg=""

    if [ -n "$body_file" ]; then
        http_code=$(timeout $TIMEOUT curl -s -X "$method" \
            -H "Content-Type: application/json" \
            -d @"$body_file" \
            -o "$outfile" -w '%{http_code}' "$url" 2>/dev/null || echo "TIMEOUT")
    else
        http_code=$(timeout $TIMEOUT curl -s -X "$method" \
            -o "$outfile" -w '%{http_code}' "$url" 2>/dev/null || echo "TIMEOUT")
    fi

    local end=$(date +%s%N)
    local elapsed_ms=$(( (end - start) / 1000000 ))

    # Read response
    local ok_field="null"
    local has_data="false"
    local has_error="false"
    local has_meta="false"
    local has_as_of="false"
    local has_freshness="false"
    local has_lineage="false"
    local has_traceback="false"
    local is_mock="false"
    local error_msg=""

    if [ -f "$outfile" ] && [ -s "$outfile" ]; then
        local raw=$(cat "$outfile")
        # Check for ok field
        ok_field=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    ok=d.get('ok')
    print('true' if ok is True else ('false' if ok is False else 'null'))
except: print('null')
" 2>/dev/null || echo "null")

        has_data=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('true' if 'data' in d else 'false')
except: print('false')
" 2>/dev/null || echo "false")

        has_error=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('true' if 'error' in d else 'false')
except: print('false')
" 2>/dev/null || echo "false")

        has_meta=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('true' if 'meta' in d else 'false')
except: print('false')
" 2>/dev/null || echo "false")

        has_as_of=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    m=d.get('meta',{})
    print('true' if ('as_of' in m or 'as_of_date' in m) else 'false')
except: print('false')
" 2>/dev/null || echo "false")

        has_freshness=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    m=d.get('meta',{})
    print('true' if ('freshness' in m or 'as_of' in m) else 'false')
except: print('false')
" 2>/dev/null || echo "false")

        has_lineage=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    m=d.get('meta',{})
    print('true' if 'lineage' in m else 'false')
except: print('false')
" 2>/dev/null || echo "false")

        lower_raw=$(echo "$raw" | tr '[:upper:]' '[:lower:]')
        if echo "$lower_raw" | grep -q "traceback"; then
            has_traceback="true"
        fi
        if echo "$lower_raw" | grep -qE "mock|sample|示例数据"; then
            is_mock="true"
        fi

        error_msg=$(echo "$raw" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    e=d.get('error')
    if e and isinstance(e,dict):
        print(json.dumps(e.get('message',''))[:200])
    else:
        print('')
except: print('')
" 2>/dev/null || echo "")
    fi

    if [ "$http_code" = "TIMEOUT" ]; then
        err_msg="连接超时 ($TIMEOUT秒)"
        http_code="TIMEOUT"
    fi

    # Determine pass/fail
    local passed_flag="false"
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "202" ]; then
        if [ "$ok_field" != "false" ]; then
            passed_flag="true"
        fi
    fi

    # Build JSON result
    local json_result=$(python3 -c "
import json
r = {
    'endpoint': '${method} ${path}',
    'method': '${method}',
    'path': '${path}',
    'status_code': '${http_code}',
    'response_time_ms': ${elapsed_ms},
    'ok_field': ${ok_field},
    'has_data': ${has_data},
    'has_error': ${has_error},
    'has_meta': ${has_meta},
    'has_as_of_date': ${has_as_of},
    'has_freshness': ${has_freshness},
    'has_lineage': ${has_lineage},
    'has_traceback': ${has_traceback},
    'is_mock': ${is_mock},
    'error_message': ${error_msg:-''},
    'passed': ${passed_flag}
}
print(json.dumps(r, ensure_ascii=False))
" 2>/dev/null || echo '{}')

    echo "$json_result" > "$TMPDIR/json_${idx}.txt"
    printf '%s' "$json_result"
}

# ============================================================
# All GET endpoints
# ============================================================
GET_ENDPOINTS=(
    "/api/health"
    "/api/status"
    "/api/data/health"
    "/api/data/sources"
    "/api/data/overview"
    "/api/data/providers"
    "/api/data/freshness"
    "/api/data/gaps"
    "/api/data/fetch-log"
    "/api/reports/health"
    "/api/reports/summary"
    "/api/reports"
    "/api/reports/recent"
    "/api/risk/overview"
    "/api/risk/alerts"
    "/api/risk/kill-switch"
    "/api/risk/history"
    "/api/risk/dimensions"
    "/api/paper/balance"
    "/api/paper/positions"
    "/api/paper/orders"
    "/api/paper/fills"
    "/api/paper/status"
    "/api/shadow/status"
    "/api/ops/health"
    "/api/ops/diagnostics"
    "/api/ops/ports"
    "/api/audit/events"
    "/api/audit/export"
    "/api/code-audits/runs"
    "/api/universe"
    "/api/benchmarks"
    "/api/factors"
    "/api/backtests"
    "/api/portfolio/recommendation/latest"
    "/api/qmt/health"
    "/api/qmt/account"
    "/api/qmt/positions"
    "/api/live-readiness/latest"
    "/api/theme/semiconductor/status"
    "/api/theme/semiconductor/subsectors"
    "/api/theme/semiconductor/history"
    "/api/events"
    "/api/settings"
)

# All POST endpoints with payloads
declare -A POST_PAYLOADS
POST_PAYLOADS["/api/backtests/run"]='{"strategy":"t","universe":"hs300"}'
POST_PAYLOADS["/api/portfolio/recommendation/run"]='{"strategy":"multi_factor"}'
POST_PAYLOADS["/api/live-readiness/run"]='{"mode":"quick"}'
POST_PAYLOADS["/api/benchmarks/build"]='{"name":"test_bm","constituents":[]}'
POST_PAYLOADS["/api/factors/validate"]='{"expression":"c>o","name":"t"}'
POST_PAYLOADS["/api/ops/backup"]=""
POST_PAYLOADS["/api/paper/reset"]=""

echo ""
echo "======================================================================"
echo "  V5 后端 API 全量审计测试 — $(date)"
echo "  服务器: $BASE"
echo "======================================================================"
echo ""

idx=0

# Test GET endpoints
total=${#GET_ENDPOINTS[@]}
for path in "${GET_ENDPOINTS[@]}"; do
    idx=$((idx + 1))
    result=$(test_endpoint "GET" "$path" "" $total $idx)
    passed_flag=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['passed'])" 2>/dev/null)
    sc=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['status_code'])" 2>/dev/null)
    ms=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['response_time_ms'])" 2>/dev/null)
    em=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error_message','') or '')" 2>/dev/null)

    if [ "$passed_flag" = "True" ] || [ "$passed_flag" = "true" ]; then
        echo "  ✅ ($idx/$total) GET $path → $sc (${ms}ms)"
        passed=$((passed + 1))
    else
        echo "  ❌ ($idx/$total) GET $path → $sc (${ms}ms)${em:+ — $em}"
        failed=$((failed + 1))
    fi
done

# Test POST endpoints
total=$(( ${#GET_ENDPOINTS[@]} + ${#POST_PAYLOADS[@]} ))
for path in "${!POST_PAYLOADS[@]}"; do
    idx=$((idx + 1))
    body="${POST_PAYLOADS[$path]}"
    body_file=""
    if [ -n "$body" ]; then
        body_file="$TMPDIR/body_${idx}.json"
        echo "$body" > "$body_file"
    fi

    result=$(test_endpoint "POST" "$path" "$body_file" $total $idx)
    passed_flag=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['passed'])" 2>/dev/null)
    sc=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['status_code'])" 2>/dev/null)
    ms=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['response_time_ms'])" 2>/dev/null)
    em=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error_message','') or '')" 2>/dev/null)

    if [ "$passed_flag" = "True" ] || [ "$passed_flag" = "true" ]; then
        echo "  ✅ ($idx/$total) POST $path → $sc (${ms}ms)"
        passed=$((passed + 1))
    else
        echo "  ❌ ($idx/$total) POST $path → $sc (${ms}ms)${em:+ — $em}"
        failed=$((failed + 1))
    fi
done

# ============================================================
# Assemble report
# ============================================================
echo ""
echo "======================================================================"
echo "  汇总: $passed/$total 通过, $failed/$total 失败"
echo "======================================================================"
echo ""

# Collect all JSON results into a Python array
python3 -c "
import json, os, sys

results = []
tmpdir = '$TMPDIR'
for f in sorted(os.listdir(tmpdir)):
    if f.startswith('json_') and f.endswith('.txt'):
        with open(os.path.join(tmpdir, f)) as fh:
            results.append(json.load(fh))

times = [r['response_time_ms'] for r in results if r.get('response_time_ms')]
avg_t = round(sum(times)/len(times), 1) if times else 0
slowest = max(results, key=lambda r: r.get('response_time_ms') or 0) if results else {}

passed = sum(1 for r in results if r.get('passed'))
failed = sum(1 for r in results if not r.get('passed'))
total = len(results)

report = {
    'report_type': 'v5_api_audit',
    'generated_at': '$(date -Iseconds)',
    'server_base': '$BASE',
    'summary': {
        'total_endpoints': total,
        'passed': passed,
        'failed': failed,
        'pass_rate': f'{round(passed/total*100,1) if total else 0}%',
    },
    'performance': {
        'avg_response_time_ms': avg_t,
        'slowest_endpoint': slowest.get('endpoint'),
        'slowest_time_ms': slowest.get('response_time_ms'),
    },
    'endpoints': results,
}

os.makedirs(os.path.dirname('$OUTFILE'), exist_ok=True)
with open('$OUTFILE', 'w') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'报告已写入: $OUTFILE')
"
