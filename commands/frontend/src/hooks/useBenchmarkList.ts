import { useQuery } from '@tanstack/react-query'
import { getBenchmarkList } from '../api/endpoints'
import type { BenchmarkData, ApiResult } from '../api/schemas'

export function useBenchmarkList() {
  return useQuery<ApiResult<BenchmarkData>>({
    queryKey: ['benchmarks'],
    queryFn: getBenchmarkList,
    refetchInterval: 60_000,
  })
}
