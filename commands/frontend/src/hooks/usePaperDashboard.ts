import { useQuery } from '@tanstack/react-query'
import { getPaperStatus, getPaperDashboard } from '../api/endpoints'
import type { PaperStatus, PaperDashboardData, ApiResult } from '../api/schemas'

export function usePaperStatus() {
  return useQuery<ApiResult<PaperStatus>>({
    queryKey: ['paper', 'status'],
    queryFn: getPaperStatus,
    refetchInterval: 30_000,
  })
}

export function usePaperDashboard(params?: { start_date?: string; end_date?: string; last_n?: number }) {
  return useQuery<ApiResult<PaperDashboardData>>({
    queryKey: ['paper', 'dashboard', params],
    queryFn: () => getPaperDashboard(params),
    refetchInterval: 60_000,
  })
}
