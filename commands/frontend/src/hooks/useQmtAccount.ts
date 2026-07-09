import { useQuery } from '@tanstack/react-query'
import { getQmtAccount } from '../api/endpoints'
import type { QmtAccount, ApiResult } from '../api/schemas'

export function useQmtAccount() {
  return useQuery<ApiResult<QmtAccount>>({
    queryKey: ['qmt', 'account'],
    queryFn: getQmtAccount,
    refetchInterval: 30_000,
  })
}
