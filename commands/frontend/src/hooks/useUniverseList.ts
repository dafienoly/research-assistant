import { useQuery } from '@tanstack/react-query'
import { getUniverseList } from '../api/endpoints'
import type { UniverseListResponse, ApiResult } from '../api/schemas'

export function useUniverseList() {
  return useQuery<ApiResult<UniverseListResponse>>({
    queryKey: ['universe'],
    queryFn: getUniverseList,
    staleTime: 60_000,
  })
}
