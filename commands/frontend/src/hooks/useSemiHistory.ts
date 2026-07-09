import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { ApiResult } from '../api/schemas'

export interface HistoryPoint {
  date: string
  semi_ew: number
  all_a_ew: number
  core_pool_ew: number
}

export interface SemiHistoryData {
  updated_at: string
  series: HistoryPoint[]
}

export function useSemiHistory(days: number = 60) {
  return useQuery<ApiResult<SemiHistoryData>>({
    queryKey: ['semi-history', days],
    queryFn: () => get<SemiHistoryData>(`/api/theme/semiconductor/history?days=${days}`),
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
}
