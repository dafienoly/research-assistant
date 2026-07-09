import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { ApiResult } from '../api/schemas'

export interface SubsectorItem {
  subsector: string
  total_stocks: number
  advance_count: number
  advance_ratio: number
  avg_change_pct: number
  turnover: number
}

export interface SemiSubsectorsData {
  updated_at: string
  items: SubsectorItem[]
}

export function useSemiSubsectors() {
  return useQuery<ApiResult<SemiSubsectorsData>>({
    queryKey: ['semi-subsectors'],
    queryFn: () => get<SemiSubsectorsData>('/api/theme/semiconductor/subsectors'),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}
