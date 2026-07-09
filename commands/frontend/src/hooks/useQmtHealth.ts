import { useQuery } from '@tanstack/react-query'
import { getQmtHealth } from '../api/endpoints'
import type { QmtData, ApiResult } from '../api/schemas'

export function useQmtHealth() {
  return useQuery<ApiResult<QmtData>>({
    queryKey: ['qmt', 'health'],
    queryFn: getQmtHealth,
    refetchInterval: 30_000,
  })
}
