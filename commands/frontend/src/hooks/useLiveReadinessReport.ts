/** V5.12 Live Gate — hooks for report, run, and history */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getLiveGateLatest, postLiveGateRun, getLiveGateHistory } from '../api/endpoints'
import type { GateReport, LiveGateHistoryResponse, ApiResult } from '../api/schemas'

export function useLiveGateLatest() {
  return useQuery<ApiResult<GateReport>>({
    queryKey: ['live-gate', 'latest'],
    queryFn: getLiveGateLatest,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}

export function useLiveGateHistory() {
  return useQuery<ApiResult<LiveGateHistoryResponse>>({
    queryKey: ['live-gate', 'history'],
    queryFn: getLiveGateHistory,
    staleTime: 60_000,
  })
}

export function useRunLiveGate() {
  const qc = useQueryClient()
  return useMutation<ApiResult<GateReport>, Error, void>({
    mutationFn: () => postLiveGateRun(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['live-gate', 'latest'] })
      qc.invalidateQueries({ queryKey: ['live-gate', 'history'] })
    },
  })
}
