import { useQuery } from '@tanstack/react-query'
import { getQmtOrders, getQmtTrades } from '../api/endpoints'
import type { QmtOrder, QmtTrade, ApiResult } from '../api/schemas'

export function useQmtOrders() {
  return useQuery<ApiResult<QmtOrder[]>>({
    queryKey: ['qmt', 'orders'],
    queryFn: getQmtOrders,
    refetchInterval: 15_000,
  })
}

export function useQmtTrades() {
  return useQuery<ApiResult<QmtTrade[]>>({
    queryKey: ['qmt', 'trades'],
    queryFn: getQmtTrades,
    refetchInterval: 15_000,
  })
}
