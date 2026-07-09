import { useQuery } from '@tanstack/react-query'
import { getShadowStatus, getShadowDashboard } from '../api/endpoints'
import type { ShadowStatus, ShadowDashboardData, ApiResult } from '../api/schemas'

export function useShadowStatus() {
  return useQuery<ApiResult<ShadowStatus>>({
    queryKey: ['shadow', 'status'],
    queryFn: getShadowStatus,
    refetchInterval: 30_000,
  })
}

export function useShadowDashboard(params?: { date?: string }) {
  return useQuery<ApiResult<ShadowDashboardData>>({
    queryKey: ['shadow', 'dashboard', params],
    queryFn: () => getShadowDashboard(params),
    refetchInterval: 60_000,
  })
}
