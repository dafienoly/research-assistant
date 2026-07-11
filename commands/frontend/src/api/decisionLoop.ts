import { get, post, request } from './client'

export interface DecisionPosition {
  symbol: string
  name: string
  quantity: number
  available_quantity: number
  frozen_quantity?: number
  cost_price: number
  market_price: number | null
  instrument_type: 'stock' | 'etf'
  book: 'catalyst' | 'swing' | 'core'
  theme: string
}

export interface DecisionEvent {
  event_id: string
  severity: 'L2' | 'L3' | 'L4'
  symbol?: string
  book?: string
  action: string
  quantity?: number
  reason: string
  advice_mode: 'executable' | 'watch_only' | 'blocked'
  generated_at: string
  acknowledged?: boolean
  acknowledged_at?: string
}

export interface DecisionLoopStatus {
  status: string
  current_position_snapshot: null | {
    snapshot_id: string
    as_of: string
    source: string
    confirmed: boolean
    positions: DecisionPosition[]
  }
  daily_authorization: null | {
    authorization_id: string
    status: 'pending' | 'active' | 'revoked' | 'expired'
    expires_at: string
    revoke_reason?: string
    plan: {
      trading_date: string
      strategy_summary: string
      risk_budget: Record<string, number>
      max_order_amount: number
      max_total_amount: number
      plan_hash: string
      parameter_version: string
      orders: PlannedOrder[]
    }
  }
  recent_events: DecisionEvent[]
  account_risk_mode: { mode?: string; actions?: string[] }
  data_gate: { mode?: string; reasons?: string[] }
  execution_readiness: { ready: boolean; live_enabled: boolean; reasons: string[] }
  unacknowledged_event_count: number
  latest_reconciliation: Record<string, unknown>
  capabilities: {
    position_sources: string[]
    notification_channels: string[]
    miniqmt_execution: string
  }
}

export interface PlannedOrder {
  order_id: string
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: number
  limit_price: number
  book: 'catalyst' | 'swing' | 'core'
  strategy: string
  reason: string
}

export interface AuthorizationCreatePayload {
  trading_date: string
  strategy_summary: string
  risk_budget: Record<string, number>
  max_order_amount: number
  max_total_amount: number
  orders: PlannedOrder[]
  parameter_version: string
}

export interface PositionPreview {
  preview_id: string
  additions: DecisionPosition[]
  removals: DecisionPosition[]
  changes: Array<{ symbol: string; book: string; fields: Record<string, { old: unknown; new: unknown }> }>
  unchanged: number
  proposed_snapshot: { content_hash: string; positions: DecisionPosition[] }
  quality_issues?: Array<{ text: string; confidence: number; requires_manual_correction: boolean }>
  requires_correction?: boolean
}

export interface PositionSnapshot {
  snapshot_id: string
  as_of: string
  source: string
  confirmed: boolean
  positions: DecisionPosition[]
}

export function getDecisionLoopStatus() {
  return get<DecisionLoopStatus>('/api/decision-loop/status')
}

export function previewDecisionPositions(source: 'csv' | 'clipboard', content: string) {
  return post<PositionPreview>('/api/decision-loop/positions/preview', { source, content })
}

export function confirmDecisionPositions(previewId: string, expectedHash: string) {
  return post('/api/decision-loop/positions/confirm', { preview_id: previewId, expected_hash: expectedHash })
}

export function previewMiniQmtPositions() {
  return post<PositionPreview>('/api/decision-loop/positions/miniqmt/preview', {})
}

export function confirmMiniQmtPositions(previewId: string, expectedHash: string) {
  return post('/api/decision-loop/positions/miniqmt/confirm', { preview_id: previewId, expected_hash: expectedHash })
}

export function previewOcrPositions(file: File) {
  const body = new FormData()
  body.append('image', file)
  return request<PositionPreview>('/api/decision-loop/positions/ocr-preview', { method: 'POST', body, timeout: 45_000 })
}

export function getPositionImportTemplate() {
  return get<{ columns: string[]; csv: string }>('/api/decision-loop/positions/template')
}

export function getPositionHistory(limit = 20) {
  return get<PositionSnapshot[]>('/api/decision-loop/positions/history', { limit })
}

export function rollbackPositionSnapshot(snapshotId: string) {
  return post<PositionSnapshot>('/api/decision-loop/positions/rollback', { snapshot_id: snapshotId })
}

export function createDailyAuthorization(payload: AuthorizationCreatePayload) {
  return post<{ authorization: DecisionLoopStatus['daily_authorization']; confirmation_nonce: string }>('/api/decision-loop/authorizations', payload)
}

export function activateDailyAuthorization(tradingDate: string, nonce: string, displayedPlanHash: string) {
  return post(`/api/decision-loop/authorizations/${tradingDate}/activate`, { nonce, displayed_plan_hash: displayedPlanHash })
}

export function revokeDailyAuthorization(tradingDate: string, reason: string) {
  return post(`/api/decision-loop/authorizations/${tradingDate}/revoke`, { reason })
}

export function acknowledgeDecisionEvent(eventId: string) {
  return post(`/api/decision-loop/events/${eventId}/acknowledge`, { actor: 'web-console' })
}
