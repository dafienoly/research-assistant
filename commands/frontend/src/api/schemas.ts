// ─── Unified API response ──────────────────────────────────────
export interface ApiResult<T = unknown> {
  ok: boolean
  data?: T
  error?: string
  meta?: Record<string, unknown>
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ─── Health ─────────────────────────────────────────────────────
export interface HealthData {
  status: string
  version: string
  uptime: number
  timestamp: string
}

// ─── Data Health ────────────────────────────────────────────────
export interface DataHealthItem {
  name: string
  status: 'ok' | 'stale' | 'missing'
  last_updated?: string
  message?: string
}

export interface DataHealthData {
  overall: 'healthy' | 'degraded' | 'down'
  items: DataHealthItem[]
}

// ─── Universe ───────────────────────────────────────────────────
export interface UniverseItem {
  code: string
  name: string
  sector?: string
  market?: string
}

export interface UniverseData {
  total: number
  items: UniverseItem[]
}

// ─── V5.5 Stock Pool (Universe) Types ────────────────────────────

/** Universe summary (from list endpoint) */
export interface UniverseSummary {
  id: string
  name: string
  label: string
  count: number
  description: string
  built_at?: string
}

/** Response from GET /api/universe */
export interface UniverseListResponse {
  universes: UniverseSummary[]
  total: number
}

// ── Per-universe stock types ──

export interface UniverseStockBase {
  ts_code: string
  symbol: string
  name: string
}

export interface U0Stock extends UniverseStockBase {
  exchange: string
  board: string
  list_date: string
  delist_date: string
  is_listed: boolean
  industry: string
  concepts: string[]
  total_mv: number | null
  float_mv: number | null
}

export interface U1Stock extends UniverseStockBase {
  is_mainboard: boolean
  is_chinext: boolean
  is_star: boolean
  is_bse: boolean
  is_st: boolean
  is_suspended: boolean
  is_limit_up: boolean
  is_limit_down: boolean
  avg_amount_20d: number
  tradable_by_user: boolean
  trade_block_reason: string | null
}

export interface U2Stock extends UniverseStockBase {
  source_atlas: boolean
  source_concept: boolean
  source_confidence: string
  ai_chain_layer: string
  primary_type: string
  theme_tags: string[]
  is_broad_ai_semiconductor: boolean
}

export interface U3Stock extends UniverseStockBase {
  industry: string
  semiconductor_subsector: string[]
  core_score: number
  domestic_substitution_score: number
  supply_chain_position: string[]
  from_semiconductor_chain_tags: boolean
}

export interface U4MatchedStock {
  ts_code: string
  symbol: string
  name: string
  industry: string
  board: string
  float_mv: number
  avg_amount_20d: number
  volatility_60d: number
}

export interface U4Stock {
  u3_ts_code: string
  u3_symbol: string
  u3_name: string
  matched_stocks: U4MatchedStock[]
  match_count: number
  match_fail_reason: string | null
}

export interface ETFStock {
  ts_code: string
  name: string
  fund_type: string
  management_fee_pct: number
  track_index: string
}

export type AnyStock = U0Stock | U1Stock | U2Stock | U3Stock | U4Stock | ETFStock

/** Universe metadata + stocks */
export interface UniverseDetail {
  name: string
  label: string
  description: string
  built_at: string
  data_sources: string[]
  total_stocks: number
  stocks: AnyStock[]
  [key: string]: unknown
}

/** Response from GET /api/universe/{id} */
export interface UniverseDetailResponse {
  universe: UniverseDetail
}

/** Audit detail for one universe */
export interface UniverseAuditDetail {
  total: number
  label?: string
  name?: string
  [key: string]: unknown
}

/** Response from GET /api/universe/{id}/audit */
export interface UniverseAuditResponse {
  universe_id: string
  name: string
  total_stocks: number
  audited_at: string
  detail: UniverseAuditDetail
  summary: Record<string, unknown>
}

// ─── Benchmark ──────────────────────────────────────────────────
export interface BenchmarkItem {
  code: string
  name: string
  value: number
  change: number
  change_pct: number
}

export interface BenchmarkData {
  date: string
  items: BenchmarkItem[]
}

// ─── Factor Ranking ─────────────────────────────────────────────
export interface FactorItem {
  factor: string
  rank: number
  score: number
  direction: 'up' | 'down' | 'flat'
  ic: number
}

export interface FactorData {
  date: string
  items: FactorItem[]
}

// ─── Factor Lab (V5.7) ──────────────────────────────────────────
export interface FactorLabItem {
  factor_name: string
  family: string
  factor_expression?: string
  IC?: number
  RankIC?: number
  ICIR?: number
  TopBottom?: number
  excess_vs_semiconductor_ew?: number
  cost_adjusted_return?: number
  turnover?: number
  max_drawdown?: number
  risk_flags?: string[]
  status: 'active' | 'retired' | 'deprecated' | 'draft' | string
  failure_reason?: string
  created_at?: string
  updated_at?: string
}

export interface FactorLabResponse {
  date: string
  factors: FactorLabItem[]
  total: number
}

export interface FactorRiskAttribution {
  factor_id: string
  factor_name: string
  risk_decomposition: {
    market: number
    industry: number
    style: number
    idiosyncratic: number
  }
  risk_exposure: {
    beta: number
    specific_risk: number
  }
}

export interface FactorICDataPoint {
  date: string
  ic: number
  rank_ic: number
}

export interface FactorICResponse {
  factor_id: string
  ic_series: FactorICDataPoint[]
  ic_mean: number
  ic_std: number
  icir: number
}

export interface FactorDetail {
  factor_name: string
  family: string
  factor_expression: string
  IC: number
  RankIC: number
  ICIR: number
  TopBottom: number
  excess_vs_semiconductor_ew: number
  excess_vs_matched_control: number
  excess_vs_core_ew: number
  cost_adjusted_return: number
  one_way_turnover: number
  two_way_turnover: number
  max_drawdown: number
  win_rate: number
  cagr_pct: number
  calmar_ratio: number
  risk_flags: string[]
  risk_attribution?: FactorRiskAttribution
  status: string
  failure_reason?: string
  created_at: string
  updated_at: string
}

export interface FactorValidateResponse {
  name: string
  expression: string
  valid: boolean
  warnings: string[]
  errors: string[]
  estimated_compute_time_ms: number
  suggested_ic: number
}

// ─── QMT ──────────────────────────────────────────────────────────
export interface QmtStatus {
  connected: boolean
  last_heartbeat?: string
  latency_ms?: number
}

export interface QmtData {
  status: string
  connected: boolean
  mode: string
  last_heartbeat: string
  latency_ms: number
  version: string
}

export interface QmtAccount {
  total_assets: number
  available: number
  market_value: number
  pnl: number
  pnl_pct: number
  frozen: number
  currency: string
}

export interface QmtPosition {
  code: string
  name: string
  volume: number
  can_use: number
  cost_price: number
  current_price: number
  market_value: number
  pnl: number
  pnl_pct: number
  market: string
}

export interface QmtOrder {
  id: string
  code: string
  name: string
  direction: 'buy' | 'sell'
  price: number
  volume: number
  traded_volume: number
  status: string
  created_at: string
}

export interface QmtTrade {
  id: string
  code: string
  name: string
  direction: 'buy' | 'sell'
  price: number
  volume: number
  amount: number
  traded_at: string
}

export interface QmtPlanPosition {
  code: string
  name: string
  target_weight: number
  actual_weight: number
  diff: number
}

// ─── Live Readiness ─────────────────────────────────────────────
export interface LiveReadiness {
  ready: boolean
  checks: {
    name: string
    passed: boolean
    message?: string
  }[]
  timestamp: string
}

export interface LiveData {
  market_open: boolean
  trading_day: string
  remaining_time: string
  readiness: LiveReadiness
}

// ─── V5.12 Live Gate Rich Report ──────────────────────────────────
export interface GateCheckResult {
  gate_name: string
  passed: boolean
  severity: string  // 'blocker' | 'warning' | 'info'
  message: string
  evidence: string
  fix_suggestion: string
}

export interface GateBlocker {
  gate_name: string
  message: string
  evidence: string
  fix_suggestion: string
}

export interface GateReport {
  overall: string      // 'READY' | 'NOT_READY'
  run_id: string
  scanned_at: string
  gates: GateCheckResult[]
  blockers: GateBlocker[]
  warnings: GateBlocker[]
  infos: Pick<GateCheckResult, 'gate_name' | 'message' | 'evidence'>[]
}

export interface GateHistoryItem {
  run_id: string
  scanned_at: string
  overall: string
  passed_count: number
  total_count: number
  blocker_count: number
}

export interface LiveGateHistoryResponse {
  history: GateHistoryItem[]
}

// ─── V5.4 Data Status ──────────────────────────────────────────

/** 数据源能力 — GET /api/data/sources */
export interface DataSourceItem {
  source_id: string
  name: string
  type: string
  provider: string
  status: string
  last_refresh?: string
  record_count?: number
  /** Tushare 接口能力详情 */
  capabilities?: Record<string, {
    available: boolean
    earliest_date?: string
    latest_date?: string
    stock_count?: number
  }>
}

export interface DataSourcesResponse {
  sources: DataSourceItem[]
}

/** 数据覆盖 — GET /api/data/coverage */
export interface CoverageItem {
  stock_count: number
  trade_days: [string, string]  // [start, end]
  row_count: number
  latest_date: string
  missing_rate: number  // 0-100
  dataset?: string
}

export interface CoverageResponse {
  coverage: CoverageItem[]
  total_stocks: number
  total_rows: number
}

/** 数据新鲜度 — GET /api/data/freshness */
export interface FreshnessFile {
  code?: string
  stock_code?: string
  path?: string
  latest_date?: string
  lag_days?: number
  status: 'ok' | 'stale' | 'missing' | 'warning'
  actual_age_seconds?: number
  max_age_seconds?: number
  note?: string
}

export interface FreshnessResponse {
  check_time?: string
  overall_status: string
  blocking?: boolean
  files: FreshnessFile[]
  error?: string
}

/** 数据 Manifest — GET /api/data/manifests */
export interface ManifestItem {
  manifest_id: string
  source_id: string
  dataset?: string
  file?: string
  record_count: number
  file_size?: number
  file_hash?: string
  created_at: string
  lineage?: string[]
  children?: string[]
}

export interface ManifestsResponse {
  manifests: ManifestItem[]
}

// ─── Paper Dashboard (V5.11) ─────────────────────────────────────
export interface PaperStatus {
  running: boolean
  trading_days: number
  initial_capital: number
  current_capital: number
  total_return_pct: number
  updated_at: string
}

export interface PaperDashboardData {
  period: string
  n_trading_days: number
  n_pending: number
  n_completed: number
  paper_total_return_pct: number
  paper_annualized_return_pct: number
  paper_volatility_pct: number
  paper_sharpe: number
  paper_max_drawdown_pct: number
  paper_win_rate_pct: number
  execution_quality: {
    filled: number
    partial_filled: number
    blocked: number
    fill_rate: number
  }
  status: string
  no_real_trade: boolean
  /** 相对半导体同池等权 (if available) */
  vs_semiconductor_ew?: {
    excess_return_pct: number
    benchmark_return_pct: number
    vs_benchmark: '跑赢' | '跑输'
  }
}

export interface ShadowStatus {
  running: boolean
  last_run_date: string
  total_runs: number
  n_not_ready: number
}

export interface ShadowPlanTrade {
  symbol: string
  name?: string
  direction: 'buy' | 'sell'
  price: number
  shares: number
  status: 'planned' | 'filled' | 'partial' | 'blocked' | 'cancelled'
  block_reason?: string
  weight_pct?: number
  estimated_amount?: number
}

export interface ShadowFilledTrade {
  trade_id: string
  symbol: string
  name?: string
  direction: 'buy' | 'sell'
  fill_price: number
  fill_shares: number
  fill_amount: number
  fee: number
  created_at: string
}

export interface ShadowDailyReview {
  date: string
  strategy_return_pct: number
  benchmark_return_pct: number
  excess_return_pct: number
  vs_benchmark: '跑赢' | '跑输'
  not_ready: boolean
  n_blocked: number
  n_filled: number
  summary: string
}

export interface ShadowRiskInterception {
  id?: string
  symbol: string
  name?: string
  reason: string
  stage: string
  timestamp: string
}

export interface ShadowPerformance {
  date: string
  strategy_return_pct: number
  benchmark_name: string
  benchmark_label: string
  benchmark_return_pct: number
  excess_return_pct: number
  vs_benchmark: '跑赢' | '跑输'
}

export interface ShadowDashboardData {
  date: string
  plan: {
    signal_date: string
    n_stocks: number
    n_tradable: number
    n_blocked: number
    stocks: ShadowPlanTrade[]
  }
  execution: {
    n_filled: number
    n_partial: number
    n_blocked: number
    trades: ShadowFilledTrade[]
  }
  pnl: {
    daily_return_pct: number
    total_return_pct: number
    total_value: number
  }
  tradability: {
    n_total: number
    n_tradable_planned: number
    n_non_tradable_planned: number
    n_check_plannable: number
    n_check_blocked: number
    blocked_by_reason: Record<string, number>
    details: Array<{
      symbol: string
      name: string
      is_tradable: boolean
      weight_pct: number
      block_reasons: string[]
    }>
  }
  risk_interceptions: {
    total_interceptions: number
    distinct_symbols_blocked: number
    by_reason: Record<string, number>
    by_stage: Record<string, number>
    details: ShadowRiskInterception[]
  }
  market_context: {
    date: string
    n_stocks_available?: number
    avg_close?: number
    median_close?: number
    close_std?: number
    total_volume?: number
    n_up?: number
    n_down?: number
  }
  performance: ShadowPerformance
  not_ready: boolean
  summary: string
}

export interface ShadowDashboardMulti {
  status: string
  n_days: number
  date_range: string
  strategy_name: string
  benchmark_name: string
  benchmark_label: string
  avg_strategy_return_pct: number | null
  avg_benchmark_return_pct: number | null
  avg_excess_return_pct: number | null
  cumulative_strategy_return_pct: number | null
  cumulative_benchmark_return_pct: number | null
  excess_cumulative_pct: number | null
  win_rate_pct: number | null
  total_risk_interceptions: number
  avg_risk_interceptions_per_day: number
  risk_interception_reasons: Record<string, number>
  avg_blocked_per_day: number
  total_planned_stocks: number
  total_filled_stocks: number
  overall_fill_rate_pct: number
  not_ready_days: number
  daily_summaries: ShadowDailyReview[]
}

// ─── V5.15 Events (事件研报与语义增强) ────────────────────────────

/** 事件方向 */
export type EventDirection = 'positive' | 'negative' | 'neutral'

/** 事件列表项 */
export interface EventItem {
  id: string
  event_date: string
  ts_code: string
  name: string
  event_type: string
  event_direction: EventDirection
  event_strength: number
  event_source: string
  title: string
}

/** 事件列表响应 */
export interface EventsResponse {
  events: EventItem[]
  total: number
  stats?: EventStats
  factor_performance?: EventFactorPerformance[]
}

/** 事件详情 */
export interface EventDetail {
  id: string
  event_date: string
  ts_code: string
  name: string
  event_type: string
  event_direction: EventDirection
  event_strength: number
  event_source: string
  title: string
  detail: string
  products?: string[]
  customers?: string[]
  capacity?: string
  risk_flags?: string[]
  llm_summary?: string
  source_ref: string
}

/** 事件频率统计 */
export interface EventStats {
  total: number
  by_type_30d: Record<string, number>
  by_type_90d: Record<string, number>
}

/** 事件因子表现 — 事件后 N 日收益 vs 同池等权 */
export interface EventFactorPerformance {
  event_type: string
  return_1d: number
  return_5d: number
  return_20d: number
  benchmark_return_1d: number
  benchmark_return_5d: number
  benchmark_return_20d: number
}
