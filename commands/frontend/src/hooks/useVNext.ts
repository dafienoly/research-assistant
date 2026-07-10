import { useQuery, useQueryClient } from '@tanstack/react-query'
import { vnextApi } from '../api/vnext'

export type VNextResource =
  | 'status'
  | 'dataHealth'
  | 'regime'
  | 'policyPut'
  | 'semiMainline'
  | 'candidates'
  | 'portfolioRisk'
  | 'mlRanker'
  | 'backtests'
  | 'paper'
  | 'shadow'
  | 'approvals'
  | 'executionStatus'
  | 'antifragileReview'
  | 'reports'

export function useVNextResource(resource: VNextResource, date?: string) {
  const query = useQuery({
    queryKey: ['vnext', resource, date ?? 'latest'],
    queryFn: async () => {
      if (resource === 'approvals') return (await vnextApi.approvals()).data
      if (resource === 'backtests') return (await vnextApi.backtests()).data
      const fn = vnextApi[resource] as (date?: string) => ReturnType<typeof vnextApi.status>
      return (await fn(date)).data
    },
    staleTime: 30_000,
    refetchInterval: resource === 'status' || resource === 'executionStatus' ? 60_000 : false,
  })
  return query
}

export function useInvalidateVNext() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: ['vnext'] })
}
