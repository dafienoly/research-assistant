## Claude Code (缓冲模式)

> ⚠️ Claude Code --print 模式在命令完成后才输出完整回答，非逐 token 实时流。

任务: Auto execute V7.1: Data Status/Provider Failure UI

I've submitted all the implementation files for your approval. Here's a summary of what's being created:

## V7.1 Implementation Plan

### Backend (3 files)

1. **`factor_lab/data_health_service.py`** (new) — Aggregation service that combines:
   - `DataRegistry` — source specs & index entries
   - `HealthTracker` — per-source success rates, latency, recent errors
   - `fetch_log.jsonl` — provider failure events from audit log
   - `quality_reports/` — data quality gate check results

2. **`factor_lab/api_server/routes_data_health.py`** (new) — 5 API endpoints:
   - `GET /api/data-health` — full overview: summary stats + sources + failures + quality
   - `GET /api/data-health/sources` — all source health list
   - `GET /api/data-health/sources/{source_id}` — per-source detail w/ health history + fallback chains
   - `GET /api/data-health/failures` — provider failure events (paginated, filterable)
   - `GET /api/data-health/quality` — quality gate reports

3. **`factor_lab/api_server/main.py`** (edit) — register new router

### Frontend (2 files)

4. **`frontend/src/pages/DataHealth.jsx`** (new) — Full-page UI with:
   - **Stat cards**: total sources, healthy (green), degraded (yellow), inactive (red)
   - **Tabs**: Data Source Overview, Failure Records, Quality Gate
   - **Source table**: status tags, progress bar for success rate, latency, call/error counts
   - **Filters**: by status (active/degraded/inactive) and category
   - **Source detail modal**: health gauge, recent errors, capabilities, fallback chains
   - **Failure log**: provider failure timeline with error details
   - **Auto-refresh** every 10s, proper loading/empty/error states
   - Follows `DESIGN.md` design system exactly

5. **`frontend/src/App.jsx`** (edit) — add `DatabaseOutlined` icon, sidebar entry "数据状态", route `/data`

Please approve the pending file operations to proceed with the implementation.
[?1006l[?1003l[?1002l[?1000l(B[>4m[<u[?1004l[?2031l[?2004l[?25h7[r8]0;[?25h## ✅ 版本 V7.1 完成

- **版本**: V7.1
- **名称**: Data Status/Provider Failure UI
- **状态**: 完成
- **提交**: 2730f7d41bfe40f587d570fe171e698bd4a65596
- **下一个**: continue with V7.2
