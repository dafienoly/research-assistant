import {
  get, post
} from './client'
import type {
  HealthData,
  Job,
  JobDetail,
  JobArtifact,
  DataHealthData,
  UniverseData,
  UniverseListResponse,
  UniverseDetailResponse,
  UniverseAuditResponse,
  BenchmarkData,
  FactorData,
  DataSourcesResponse,
  CoverageResponse,
  FreshnessResponse,
  ManifestsResponse,
  FactorLabResponse,
  FactorDetail,
  FactorRiskAttribution,
  FactorICResponse,
  FactorValidateResponse,
  QmtData,
  QmtAccount,
  QmtPosition,
  QmtOrder,
  QmtTrade,
  QmtPlanPosition,
  LiveData,
  PaperStatus,
  PaperDashboardData,
  ShadowStatus,
  ShadowDashboardData,
  LiveGateHistoryResponse,
  GateReport,
  EventsResponse,
  EventDetail,
} from './schemas'
// ─── Health ─────────────────────────────────────────────────────
export function health() {
  return get<HealthData>('/api/health')
}

// ─── Jobs ───────────────────────────────────────────────────────
export function getJobs() {
  return get<Job[]>('/api/jobs')
}

/** Trigger a job run */
export function postJobRun(type: string, params: Record<string, unknown> = {}) {
  return post<Job>('/api/jobs/run', { type, params })
}

/** SSE stream for a running job */
export function getJobStreamUrl(runId: string): string {
  const base = import.meta.env.VITE_API_BASE ?? ''
  return `${base}/api/jobs/${runId}/stream`
}

/** Get job detail */
export function getJobDetail(runId: string) {
  return get<JobDetail>(`/api/jobs/${runId}`)
}

/** Re-run a job */
export function postJobRerun(runId: string) {
  return post<Job>(`/api/jobs/${runId}/rerun`)
}

// ─── Data Health ────────────────────────────────────────────────
export function getDataHealth() {
  return get<DataHealthData>('/api/data-health')
}

// ─── Universe ───────────────────────────────────────────────────
export function getUniverseList() {
  return get<UniverseListResponse>('/api/universe')
}

export function getUniverseById(id: string) {
  return get<UniverseDetailResponse>(`/api/universe/${id}`)
}

export function getUniverseAudit(id: string) {
  return get<UniverseAuditResponse>(`/api/universe/${id}/audit`)
}

// ─── Data Sources (V5.6) ───────────────────────────────────────
export function getDataSources() {
  return get<DataSourcesResponse>('/api/data-sources')
}

export function getCoverage() {
  return get<CoverageResponse>('/api/coverage')
}

export function getFreshness() {
  return get<FreshnessResponse>('/api/freshness')
}

export function getManifests() {
  return get<ManifestsResponse>('/api/manifests')
}

// ─── Benchmark ──────────────────────────────────────────────────
export function getBenchmarkList() {
  return get<BenchmarkData>('/api/benchmarks')
}

// ─── Factor Ranking ─────────────────────────────────────────────
export function getFactorRanking() {
  return get<FactorData>('/api/factors/ranking')
}

// ─── Factor Lab (V5.7) ──────────────────────────────────────────
export function getFactorList(params?: { category?: string; status?: string; limit?: number }) {
  return get<FactorLabResponse>('/api/factors', params)
}

export function getFactorDetail(factorId: string) {
  return get<FactorDetail>(`/api/factors/${factorId}`)
}

export function getFactorRiskAttribution(factorId: string) {
  return get<FactorRiskAttribution>(`/api/factors/${factorId}/risk-attribution`)
}

export function getFactorIC(factorId: string) {
  return get<FactorICResponse>(`/api/factors/${factorId}/ic`)
}

export function postFactorValidate(body: { name?: string; expression: string }) {
  return post<FactorValidateResponse>('/api/factors/validate', body)
}

// ─── QMT ────────────────────────────────────────────────────────
export function getQmtHealth() {
  return get<QmtData>('/api/qmt/health')
}

export function getQmtAccount() {
  return get<QmtAccount>('/api/qmt/account')
}

export function getQmtPositions() {
  return get<QmtPosition[]>('/api/qmt/positions')
}

export function getQmtOrders() {
  return get<QmtOrder[]>('/api/qmt/orders')
}

export function getQmtTrades() {
  return get<QmtTrade[]>('/api/qmt/trades')
}

export function getQmtPlanPositions() {
  return get<QmtPlanPosition[]>('/api/qmt/plan-positions')
}

// ─── Paper Dashboard (V5.11) ─────────────────────────────────────
export function getPaperStatus() {
  return get<PaperStatus>('/api/paper/status')
}

export function getPaperDashboard(params?: { start_date?: string; end_date?: string; last_n?: number }) {
  return get<PaperDashboardData>('/api/paper/dashboard', params)
}

export function postPaperV4Run(params?: Record<string, unknown>) {
  return post<{ status: string; message: string }>('/api/paper/v4-run', params)
}

// ─── Shadow Dashboard (V5.11) ────────────────────────────────────
export function getShadowStatus() {
  return get<ShadowStatus>('/api/shadow/status')
}

export function getShadowDashboard(params?: { date?: string }) {
  return get<ShadowDashboardData>('/api/shadow/dashboard', params)
}

export function postShadowV4Run(params?: Record<string, unknown>) {
  return post<{ status: string; message: string }>('/api/shadow/v4-run', params)
}

// ─── Live Readiness ─────────────────────────────────────────────
export function getLiveReadiness() {
  return get<LiveData>('/api/live/readiness')
}

// ─── V5.12 Live Gate ─────────────────────────────────────────────
export function getLiveGateLatest() {
  return get<GateReport>('/api/live-readiness/latest')
}

export function postLiveGateRun() {
  return post<GateReport>('/api/live-readiness/run')
}

export function getLiveGateHistory() {
  return get<LiveGateHistoryResponse>('/api/live-readiness/history')
}

// ─── V5.4 Data Status ──────────────────────────────────────────

/** 数据源能力 */
export function getDataSourcesV54() {
  return get<DataSourcesResponse>('/api/data/sources')
}

/** 数据覆盖 */
export function getDataCoverage() {
  return get<CoverageResponse>('/api/data/coverage')
}

/** 数据新鲜度 */
export function getDataFreshness() {
  return get<FreshnessResponse>('/api/data/freshness')
}

/** 数据 Manifest */
export function getDataManifests() {
  return get<ManifestsResponse>('/api/data/manifests')
}

// ─── V5.15 Events (事件研报与语义增强) ─────────────────────────────

/** 获取事件列表 */
export function getEvents(params?: { event_type?: string; direction?: string; limit?: number; offset?: number }) {
  return get<EventsResponse>('/api/events', params)
}

/** 获取事件详情 */
export function getEventDetail(id: string) {
  return get<EventDetail>(`/api/events/${id}`)
}
