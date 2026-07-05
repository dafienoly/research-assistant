import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Custom SSE hook — connects to an EventSource endpoint and streams events.
 *
 * @param {string} url          SSE endpoint URL
 * @param {object} [options]
 * @param {string[]} [options.events]    Event types to listen for (default: ['message'])
 * @param {boolean}  [options.autoConnect]  Start connecting immediately (default: true)
 * @param {number}   [options.reconnectDelay]  Base reconnect delay in ms (default: 3000)
 * @param {number}   [options.maxRetries]  Max reconnect attempts (default: Infinity)
 * @param {object}  [options.withCredentials]  EventSource withCredentials flag (default: false)
 * @returns {{ data, error, isConnected, connect, disconnect }}
 */
export default function useSSE(url, options = {}) {
  const {
    events = ['message'],
    autoConnect = true,
    reconnectDelay = 3000,
    maxRetries = Infinity,
    withCredentials = false,
  } = options

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [isConnected, setIsConnected] = useState(false)

  const esRef = useRef(null)
  const retryCountRef = useRef(0)
  const retryTimerRef = useRef(null)
  const enabledRef = useRef(autoConnect)

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
      const handlerMap = {}
      events.forEach((eventName) => {
        const handler = (e) => {
          try {
            const parsed = JSON.parse(e.data)
            setData((prev) => ({
              event: eventName,
              data: parsed,
              raw: e.data,
              previous: prev,
            }))
          } catch {
            setData((prev) => ({
              event: eventName,
              data: e.data,
              raw: e.data,
              previous: prev,
            }))
          }
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
      setError(err)
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
