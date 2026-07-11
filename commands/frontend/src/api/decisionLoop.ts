import { get, post } from './client'

export interface DecisionPosition {
  symbol: string
  name: string
  quantity: number
  available_quantity: number
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
    plan: { strategy_summary: string; max_order_amount: number; max_total_amount: number; plan_hash: string }
  }
  recent_events: DecisionEvent[]
  capabilities: {
    position_sources: string[]
    notification_channels: string[]
    miniqmt_execution: string
  }
}

export interface PositionPreview {
  preview_id: string
  additions: DecisionPosition[]
  removals: DecisionPosition[]
  changes: Array<{ symbol: string; book: string; fields: Record<string, { old: unknown; new: unknown }> }>
  unchanged: number
  proposed_snapshot: { content_hash: string; positions: DecisionPosition[] }
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

export function acknowledgeDecisionEvent(eventId: string) {
  return post(`/api/decision-loop/events/${eventId}/acknowledge`, { actor: 'web-console' })
}
