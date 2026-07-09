import { useQuery } from '@tanstack/react-query'
import { getDataHealth } from '../api/endpoints'
import type { DataHealthData, ApiResult } from '../api/schemas'

export function useDataHealth() {
  return useQuery<ApiResult<DataHealthData>>({
    queryKey: ['data-health'],
    queryFn: getDataHealth,
    refetchInterval: 30_000,
  })
}
