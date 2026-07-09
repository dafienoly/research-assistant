import { useQuery } from '@tanstack/react-query'
import { getFactorRanking } from '../api/endpoints'
import type { FactorData, ApiResult } from '../api/schemas'

export function useFactorRanking() {
  return useQuery<ApiResult<FactorData>>({
    queryKey: ['factors', 'ranking'],
    queryFn: getFactorRanking,
    refetchInterval: 60_000,
  })
}
