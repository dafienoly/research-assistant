import { useQuery } from '@tanstack/react-query'
import { getEvents, getEventDetail } from '../api/endpoints'
import type { EventsResponse, EventDetail, ApiResult } from '../api/schemas'

export function useEvents(params?: { event_type?: string; direction?: string; limit?: number; offset?: number }) {
  return useQuery<ApiResult<EventsResponse>>({
    queryKey: ['events', params],
    queryFn: () => getEvents(params),
    refetchInterval: 60_000,
  })
}

export function useEventDetail(id: string | null) {
  return useQuery<ApiResult<EventDetail>>({
    queryKey: ['event', id],
    queryFn: () => getEventDetail(id!),
    enabled: !!id,
  })
}
