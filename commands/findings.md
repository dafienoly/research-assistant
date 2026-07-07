# Findings: V7.1 Data Status / Provider Failure UI

## Architecture

### New Backend Module: `factor_lab/api_server/routes_data.py`
- 5 FastAPI endpoints under `/api` prefix:
  - `GET /data/overview` — aggregated summary (total/active/degraded/inactive/unchecked + blocking issues)
  - `GET /data/providers` — per-source health (success_rate, avg_latency_ms, recent_errors)
  - `GET /data/freshness` — file-by-file freshness via FreshnessChecker
  - `GET /data/gaps` — data gap report via DataGapReporter
  - `GET /data/fetch-log` — recent fetch attempts with failure details
- Reuses existing V5.0 `DataRegistry` + `HealthTracker` for provider health
- Reuses existing `FreshnessChecker` + `DataGapReporter` for data quality
- Follows same router pattern as routes_status/routes_backup/routes_console

### New Frontend Module: `frontend/src/pages/DataStatus.jsx`
- 6 visual sections:
  1. **Alert banner** — red banner when blocking issues exist
  2. **Summary cards** — 6 card row (total sources, healthy, degraded, failed, unchecked, blocking)
  3. **Provider Health Table** — status dot + success rate Progress bar + latency + expandable errors
  4. **Data Freshness Table** — per-file age vs threshold with progress bars
  5. **Data Gaps Table** — blocking/partial/minor tagged rows
  6. **Fetch Log Table** — recent fetch attempts with error details
- Auto-refresh every 30s + manual refresh button
- Uses existing cardStyle and DESIGN.md color tokens

### No Silent Fallback Implementation
- Provider health status visible at a glance via color-coded status dots
- Degraded/deactivated providers show clearly with yellow/red badges
- Blocking freshness/gap issues trigger top-of-page red alert
- Provider row expandable to show recent errors
- Fetch log shows every failed attempt with error message

## Integration Points
1. ✅ `factor_lab/api_server/main.py` — `data_router` registered at `/api`
2. ✅ `frontend/src/App.jsx` — sidebar route `/data` → DataStatus component
3. ✅ Reuses V5.0 DataRegistry (`factor_lab/data_source/registry.py`)
4. ✅ Reuses V5.0 HealthTracker (`factor_lab/data_source/health.py`)
5. ✅ Reuses `data_quality.FreshnessChecker` + `DataGapReporter`
6. ✅ Follows DESIGN.md design tokens and card patterns

## Test Results
- 11/11 V7.1 new tests: PASSED
- 432/432 regression tests: PASSED (zero regressions)
