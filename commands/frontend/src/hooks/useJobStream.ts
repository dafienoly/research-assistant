import { useEffect, useRef, useState } from 'react'
import { getJobStreamUrl } from '../api/endpoints'

interface JobStreamOptions {
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean
  /** Reconnection delay (ms, default: 3000) */
  reconnectDelay?: number
  /** Max retries (default: Infinity) */
  maxRetries?: number
}

interface JobStreamState {
  data: unknown
  error: Error | null
  isConnected: boolean
}

/**
 * Hook for consuming a job SSE stream.
 * Returns live job progress / result updates.
 */
export function useJobStream(runId: string | null, options: JobStreamOptions = {}) {
  const { autoConnect = true, reconnectDelay = 3000, maxRetries = Infinity } = options

  const [state, setState] = useState<JobStreamState>({
    data: null,
    error: null,
    isConnected: false,
  })

  const esRef = useRef<EventSource | null>(null)
  const retryCountRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = () => {
    if (!runId) return
    if (esRef.current) esRef.current.close()

    const url = getJobStreamUrl(runId)
    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => {
      setState((prev) => ({ ...prev, isConnected: true, error: null }))
      retryCountRef.current = 0
    }

    es.onmessage = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data)
        setState((prev) => ({ ...prev, data: parsed, error: null }))
      } catch {
        setState((prev) => ({ ...prev, data: e.data, error: null }))
      }
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      setState((prev) => ({ ...prev, isConnected: false }))

      if (retryCountRef.current < maxRetries) {
        retryCountRef.current += 1
        const delay = reconnectDelay * Math.min(retryCountRef.current, 5)
        retryTimerRef.current = setTimeout(connect, delay)
      } else {
        setState((prev) => ({
          ...prev,
          error: new Error('Max SSE reconnect attempts reached'),
        }))
      }
    }
  }

  const disconnect = () => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setState((prev) => ({ ...prev, isConnected: false }))
    retryCountRef.current = 0
  }

  useEffect(() => {
    if (autoConnect && runId) {
      connect()
    }
    return () => disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, autoConnect])

  return {
    ...state,
    connect,
    disconnect,
  }
}
