import { useQuery } from '@tanstack/react-query'
import { getJobs } from '../api/endpoints'
import type { Job, ApiResult } from '../api/schemas'

export function useJobs() {
  return useQuery<ApiResult<Job[]>>({
    queryKey: ['jobs'],
    queryFn: getJobs,
    refetchInterval: 10_000,
  })
}
