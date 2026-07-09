import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { ApiResult } from '../api/schemas'

export interface SemiThemeStatus {
  theme: string
  name: string
  updated_at: string
  theme_state: '极弱' | '偏弱' | '中性' | '偏强' | '极强'
  theme_weight: number
  sentiment: string
  sentiment_score: number
  metrics: {
    semi_ew_return: number
    all_a_ew_return: number
    relative_strength: number
    turnover_share: number
    advance_ratio: number
    core_pool_return: number
    broad_pool_return: number
  }
  etf: {
    ticker: string
    name: string
    price: number
    change_pct: number
    volume: number
  }
  etf_basket: Array<{
    ticker: string
    name: string
    price: number
    change_pct: number
    volume: number
    amount: number
  }>
  key_events: Array<{ date: string; title: string; impact: string }>
  top_holdings: Array<{ ticker: string; name: string; weight: number; change_pct: number }>
  metrics_fundamental: {
    pe_ttm: number
    pb: number
    dividend_yield: number
    yoy_revenue_growth: number
    yoy_profit_growth: number
  }
}

export function useSemiThemeStatus() {
  return useQuery<ApiResult<SemiThemeStatus>>({
    queryKey: ['semi-theme-status'],
    queryFn: () => get<SemiThemeStatus>('/api/theme/semiconductor/status'),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}
