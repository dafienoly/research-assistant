import { useQuery } from '@tanstack/react-query'
import { health } from '../api/endpoints'
import type { HealthData, ApiResult } from '../api/schemas'

export function useHealth() {
  return useQuery<ApiResult<HealthData>>({
    queryKey: ['health'],
    queryFn: health,
    refetchInterval: 5_000,
  })
}
