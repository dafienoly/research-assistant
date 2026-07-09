/** TanStack Query hooks for the Dashboard — 投研驾驶舱 */
import { useQuery } from '@tanstack/react-query'
import { API } from '../App'

// ---------------------------------------------------------------------------
// 通用 API fetch helper — 兼容 wrapped ({ok, data}) 和 raw 响应
// ---------------------------------------------------------------------------
async function apiFetch<T>(url: string): Promise<T> {
  const res = await fetch(`${API}${url}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  // 统一响应格式 {ok, data, error, meta}
  if (json && typeof json === 'object' && 'ok' in json) {
    if (!json.ok) throw new Error(json.error?.message || 'API Error')
    return json.data as T
  }
  return json as T
}

// ---------------------------------------------------------------------------
// Type definitions
// ---------------------------------------------------------------------------

export interface SystemStatus {
  status: string
  version: string
  timestamp: string
}

export interface DataOverview {
  checked_at: string
  summary: {
    total_sources: number
    active: number
    degraded: number
    inactive: number
    unchecked: number
    blocking_issues: number
    freshness_status: string
    total_gaps: number
  }
}

export interface ProviderInfo {
  source_id: string
  name: string
  category: string
  status: string
  health: {
    success_rate: number
    total_calls: number
    error_count: number
    avg_latency_ms: number
    last_check: string
    recent_errors: string[]
  }
}

export interface DataProviders {
  checked_at: string
  total: number
  sources: ProviderInfo[]
}

export interface QmtHealth {
  status: string
  connected: boolean
  mode: string
  last_heartbeat: string
  latency_ms: number
  version: string
}

export interface SemiThemeStatus {
  theme: string
  name: string
  updated_at: string
  hot_rank: number
  sentiment: string
  sentiment_score: number
  etf: {
    ticker: string
    name: string
    price: number
    change_pct: number
    volume: number
  }
  key_events: Array<{ date: string; title: string; impact: string }>
  top_holdings: Array<{ ticker: string; name: string; weight: number; change_pct: number }>
  metrics: {
    pe_ttm: number
    pb: number
    dividend_yield: number
    yoy_revenue_growth: number
    yoy_profit_growth: number
  }
}

export interface PortfolioRecommendation {
  generated_at: string
  strategy: string
  holdings: Array<{ ticker: string; name: string; weight: number; reason: string }>
  expected_annual_return: number
  expected_volatility: number
  expected_sharpe: number
  risk_level: string
  status: string
}

export interface LiveReadiness {
  checked_at: string
  overall_status: string
  checks: Record<string, { status: string; message: string; latency_ms?: number }>
  summary: string
  blocking_issues: string[]
  warnings: string[]
}

export interface AuditEvent {
  id: string
  event_type: string
  action: string
  resource: string
  outcome: string
  run_id: string
  detail: string
  created_at: string
}

export interface AuditEventsResponse {
  events: AuditEvent[]
  total: number
  stats: Record<string, number>
}

export interface RiskAlert {
  id: string
  severity: string
  status: string
  rule: string
  message: string
  triggered_at: string
  acknowledged_at?: string
}

export interface RiskAlertsResponse {
  total: number
  count: number
  alerts: RiskAlert[]
}

export interface PaperBalance {
  cash: number
  total_asset: number
  unrealized_pnl: number
  realized_pnl: number
  daily_pnl: number
  updated_at: string
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** 1. 系统状态总览 — 系统时间 + API 版本 + 运行时长 */
export function useSystemStatus() {
  return useQuery<SystemStatus>({
    queryKey: ['system-status'],
    queryFn: () => apiFetch<SystemStatus>('/api/health'),
    refetchInterval: 60_000, // 每分钟刷新
    staleTime: 30_000,
  })
}

/** 2. 数据健康 — 覆盖率 / 最新交易日 / 缺失状态 */
export function useDataOverview() {
  return useQuery<DataOverview>({
    queryKey: ['data-overview'],
    queryFn: () => apiFetch<DataOverview>('/api/data/overview'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

/** 3. Tushare 状态 — 取 providers 中的 tushare 条目信息 */
export function useTushareStatus() {
  return useQuery<DataProviders>({
    queryKey: ['tushare-status'],
    queryFn: () => apiFetch<DataProviders>('/api/data/providers'),
    refetchInterval: 120_000,
    staleTime: 60_000,
    select: (data) => {
      // 从 providers 中筛选 Tushare 相关信息
      const tushareSources = (data.sources || []).filter(
        (s) => s.source_id?.toLowerCase().includes('tushare') || s.category?.toLowerCase().includes('tushare')
      )
      return { ...data, sources: tushareSources }
    },
  })
}

/** 4. QMT 连接状态 */
export function useQmtHealth() {
  return useQuery<QmtHealth>({
    queryKey: ['qmt-health'],
    queryFn: () => apiFetch<QmtHealth>('/api/qmt/health'),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}

/** 5. 半导体主题状态 */
export function useSemiThemeStatus() {
  return useQuery<SemiThemeStatus>({
    queryKey: ['semi-theme-status'],
    queryFn: () => apiFetch<SemiThemeStatus>('/api/theme/semiconductor/status'),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

/** 6. 最新组合建议 */
export function useLatestRecommendation() {
  return useQuery<PortfolioRecommendation>({
    queryKey: ['portfolio-recommendation-latest'],
    queryFn: () => apiFetch<PortfolioRecommendation>('/api/portfolio/recommendation/latest'),
    refetchInterval: 300_000,
    staleTime: 120_000,
  })
}

/** 7. Paper/Shadow 账户余额 */
export function usePaperBalance() {
  return useQuery<PaperBalance>({
    queryKey: ['paper-balance'],
    queryFn: () => apiFetch<PaperBalance>('/api/paper/balance'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

/** 8. Live Readiness */
export function useLiveReadiness() {
  return useQuery<LiveReadiness>({
    queryKey: ['live-readiness-latest'],
    queryFn: () => apiFetch<LiveReadiness>('/api/live-readiness/latest'),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}

/** 9. 最新任务 — 最近 5 条审计事件 */
export function useRecentTasks() {
  return useQuery<AuditEventsResponse>({
    queryKey: ['recent-tasks'],
    queryFn: () => apiFetch<AuditEventsResponse>('/api/audit/events?limit=5'),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}

/** 10. 最新风险预警 — 最近 5 条 */
export function useRiskAlerts() {
  return useQuery<RiskAlertsResponse>({
    queryKey: ['risk-alerts'],
    queryFn: () => apiFetch<RiskAlertsResponse>('/api/risk/alerts?limit=5'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

/** 聚合所有 dashboard 查询 — 用于判断整体加载状态 */
export function useAllDashboardQueries() {
  const system = useSystemStatus()
  const dataOv = useDataOverview()
  const tushare = useTushareStatus()
  const qmt = useQmtHealth()
  const semi = useSemiThemeStatus()
  const portfolio = useLatestRecommendation()
  const paper = usePaperBalance()
  const live = useLiveReadiness()
  const tasks = useRecentTasks()
  const alerts = useRiskAlerts()

  const isLoading =
    system.isLoading ||
    dataOv.isLoading ||
    tushare.isLoading ||
    qmt.isLoading ||
    semi.isLoading ||
    portfolio.isLoading ||
    paper.isLoading ||
    live.isLoading ||
    tasks.isLoading ||
    alerts.isLoading

  const isError =
    system.isError ||
    dataOv.isError ||
    tushare.isError ||
    qmt.isError ||
    semi.isError ||
    portfolio.isError ||
    paper.isError ||
    live.isError ||
    tasks.isError ||
    alerts.isError

  return { isLoading, isError, queries: { system, dataOv, tushare, qmt, semi, portfolio, paper, live, tasks, alerts } }
}
