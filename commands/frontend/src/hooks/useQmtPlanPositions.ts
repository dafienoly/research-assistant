import { useQuery } from '@tanstack/react-query'
import { getQmtPlanPositions } from '../api/endpoints'
import type { QmtPlanPosition, ApiResult } from '../api/schemas'

export function useQmtPlanPositions() {
  return useQuery<ApiResult<QmtPlanPosition[]>>({
    queryKey: ['qmt', 'plan-positions'],
    queryFn: getQmtPlanPositions,
    refetchInterval: 60_000,
  })
}
