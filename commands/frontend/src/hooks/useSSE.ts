import { useState, useEffect, useRef, useCallback } from 'react'

interface SSEOptions {
  events?: string[]
  autoConnect?: boolean
  reconnectDelay?: number
  maxRetries?: number
  withCredentials?: boolean
}

interface SSEData {
  event: string
  data: unknown
  raw: string
  previous: SSEData | null
}

interface UseSSEReturn {
  data: SSEData | null
  error: Error | null
  isConnected: boolean
  connect: () => void
  disconnect: () => void
}

/**
 * Custom SSE hook — connects to an EventSource endpoint and streams events.
 */
export default function useSSE(url: string, options: SSEOptions = {}): UseSSEReturn {
  const {
    events = ['message'],
    autoConnect = true,
    reconnectDelay = 3000,
    maxRetries = Infinity,
    withCredentials = false,
  } = options

  const [data, setData] = useState<SSEData | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  const esRef = useRef<EventSource | null>(null)
  const retryCountRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const enabledRef = useRef(autoConnect)

  /** Safely update data state with proper typing */
  const updateData = (eventName: string, rawData: string) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(rawData)
    } catch {
      parsed = rawData
    }
    setData((prev) => ({
      event: eventName,
      data: parsed,
      raw: rawData,
      previous: prev,
    }))
  }

  const clearRetryTimer = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }, [])

  const disconnect = useCallback(() => {
    clearRetryTimer()
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setIsConnected(false)
    retryCountRef.current = 0
  }, [clearRetryTimer])

  const connect = useCallback(() => {
    if (!url || !enabledRef.current) return
    if (esRef.current) esRef.current.close()

    try {
      const es = new EventSource(url, { withCredentials })
      esRef.current = es

      es.onopen = () => {
        setIsConnected(true)
        retryCountRef.current = 0
      }

      // Register listeners for each event type
      const handlerMap: Record<string, (e: MessageEvent) => void> = {}
      events.forEach((eventName) => {
        const handler = (e: MessageEvent) => {
          updateData(eventName, e.data)
        }
        handlerMap[eventName] = handler

        if (eventName === 'message') {
          es.onmessage = handler
        } else {
          es.addEventListener(eventName, handler)
        }
      })

      es.onerror = () => {
        setIsConnected(false)
        setError(new Error('SSE connection error'))

        // Clean up current connection
        es.close()
        esRef.current = null

        // Auto-reconnect
        if (enabledRef.current && retryCountRef.current < maxRetries) {
          retryCountRef.current += 1
          const delay = reconnectDelay * Math.min(retryCountRef.current, 5) // cap backoff
          retryTimerRef.current = setTimeout(() => {
            connect()
          }, delay)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
      setIsConnected(false)
    }
  }, [url, events, withCredentials, reconnectDelay, maxRetries, clearRetryTimer])

  // Handle auto-connect lifecycle
  useEffect(() => {
    enabledRef.current = autoConnect
  }, [autoConnect])

  useEffect(() => {
    if (autoConnect && url) {
      connect()
    }
    return () => {
      disconnect()
    }
  }, [url, connect, disconnect, autoConnect])

  return { data, error, isConnected, connect, disconnect }
}
