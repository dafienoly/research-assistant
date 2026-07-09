import { useQuery } from '@tanstack/react-query'
import { getQmtPositions } from '../api/endpoints'
import type { QmtPosition, ApiResult } from '../api/schemas'

export function useQmtPositions() {
  return useQuery<ApiResult<QmtPosition[]>>({
    queryKey: ['qmt', 'positions'],
    queryFn: getQmtPositions,
    refetchInterval: 30_000,
  })
}
