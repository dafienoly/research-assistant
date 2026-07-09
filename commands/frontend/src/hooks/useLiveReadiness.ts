import { useQuery } from '@tanstack/react-query'
import { getLiveReadiness } from '../api/endpoints'
import type { LiveData, ApiResult } from '../api/schemas'

export function useLiveReadiness() {
  return useQuery<ApiResult<LiveData>>({
    queryKey: ['live', 'readiness'],
    queryFn: getLiveReadiness,
    refetchInterval: 15_000,
  })
}
