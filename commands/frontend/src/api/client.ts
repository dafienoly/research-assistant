import type { ApiResult } from './schemas'
import { ApiError } from './schemas'

/**
 * Base URL for API requests.
 * In dev mode, Vite proxies /api → backend (see vite.config.js).
 * In production, same-origin is used.
 */
const BASE_URL = import.meta.env.VITE_API_BASE ?? ''

/** Default request timeout (ms) */
const TIMEOUT_MS = 15_000

/** Get auth token from localStorage */
function getToken(): string | null {
  try {
    return localStorage.getItem('token')
  } catch {
    return null
  }
}

/**
 * Build full request URL.
 */
function buildUrl(path: string, params?: Record<string, string | number | boolean | undefined>): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value))
      }
    }
  }

  return url.toString()
}

/**
 * Unified fetch wrapper.
 *
 * - Automatically attaches Authorization header from localStorage.
 * - Parses unified response format `{ok, data, error, meta}`.
 * - Throws `ApiError` on network / HTTP / business-logic errors.
 * - Supports request timeout.
 */
export async function request<T = unknown>(
  path: string,
  options: RequestInit & {
    params?: Record<string, string | number | boolean | undefined>
    timeout?: number
  } = {},
): Promise<ApiResult<T>> {
  const { params, timeout = TIMEOUT_MS, ...fetchOptions } = options
  const url = buildUrl(path, params)

  // Build headers
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(fetchOptions.headers as Record<string, string> | undefined),
  }

  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  // Set Content-Type if body is present and not FormData
  if (
    fetchOptions.body &&
    typeof fetchOptions.body === 'string' &&
    !headers['Content-Type']
  ) {
    headers['Content-Type'] = 'application/json'
  }

  // AbortController for timeout
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    })

    clearTimeout(timeoutId)

    // Try to parse JSON
    let body: ApiResult<T>
    try {
      body = (await response.json()) as ApiResult<T>
    } catch {
      throw new ApiError(
        `Invalid JSON response (HTTP ${response.status})`,
        response.status,
      )
    }

    // HTTP error without our format
    if (!response.ok && body.ok === undefined) {
      throw new ApiError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status,
      )
    }

    // Business-logic error
    if (!body.ok) {
      throw new ApiError(
        body.error ?? `Request failed (HTTP ${response.status})`,
        response.status,
      )
    }

    return body
  } catch (err) {
    clearTimeout(timeoutId)

    if (err instanceof ApiError) throw err
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError('Request timed out', 408)
    }
    throw new ApiError(
      err instanceof Error ? err.message : 'Network error',
      0,
    )
  }
}

// ─── Convenience shorthands ─────────────────────────────────────

export function get<T = unknown>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  timeout?: number,
): Promise<ApiResult<T>> {
  return request<T>(path, { method: 'GET', params, timeout })
}

export function post<T = unknown>(
  path: string,
  body?: unknown,
  timeout?: number,
): Promise<ApiResult<T>> {
  return request<T>(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
    timeout,
  })
}
