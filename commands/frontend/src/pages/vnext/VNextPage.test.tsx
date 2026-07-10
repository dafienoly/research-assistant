import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import VNextPage, { type VNextPageKind } from './VNextPage'

const pages: Array<[VNextPageKind, string]> = [
  ['home', 'Hermes 投研交易控制台'],
  ['regime', 'Regime & Policy Put'],
  ['semi', 'Semiconductor Mainline'],
  ['candidates', 'Signal / Candidates'],
  ['portfolio', 'Portfolio & Risk'],
  ['ml', 'ML Factor / Ranker Lab'],
  ['backtests', 'Backtest / Validation'],
  ['trading', 'Paper / Shadow Trading'],
  ['approvals', 'Telegram Approval Queue'],
  ['execution', 'Execution / miniQMT'],
  ['review', 'Antifragile Review'],
  ['data-health', 'Data Health'],
]

const missing = {
  status: 'MISSING',
  as_of: '2026-07-10',
  confidence: 0,
  evidence: [],
  missing_evidence: ['real source unavailable in UI integration test'],
  data_sources: [],
  updated_at: '2026-07-10T00:00:00+08:00',
  payload: {},
  trading_mode: 'READ_ONLY',
  no_live_trade: true,
  live_enabled: false,
  data_freshness: 'MISSING',
}

describe('VNext console pages', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.includes('/approvals') && !url.match(/approvals\/[^/?]+/)
        ? { items: [], total: 0 }
        : missing
      return new Response(JSON.stringify({ ok: true, data, error: null, meta: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it.each(pages)('renders %s without a blank root and exposes degraded state', async (kind, title) => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <VNextPage kind={kind} />
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('heading', { name: title })).toBeTruthy()
    await waitFor(() => expect(container.querySelector('.vnext-page')?.children.length).toBeGreaterThan(0))
    if (kind !== 'approvals') {
      expect(await screen.findAllByText(/MISSING/)).not.toHaveLength(0)
    }
  })
})
