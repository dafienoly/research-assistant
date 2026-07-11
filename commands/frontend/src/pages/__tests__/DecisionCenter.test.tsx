import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import DecisionCenter from '../DecisionCenter'
import {
  acknowledgeDecisionEvent,
  confirmDecisionPositions,
  getDecisionLoopStatus,
  previewDecisionPositions,
} from '../../api/decisionLoop'

vi.mock('../../api/decisionLoop', () => ({
  getDecisionLoopStatus: vi.fn(),
  previewDecisionPositions: vi.fn(),
  confirmDecisionPositions: vi.fn(),
  acknowledgeDecisionEvent: vi.fn(),
}))

const status = {
  status: 'ready',
  current_position_snapshot: {
    snapshot_id: 'pos1', as_of: '2026-07-11T10:00:00+08:00', source: 'clipboard', confirmed: true,
    positions: [{ symbol: '588200.SH', name: '设备ETF', quantity: 1000, available_quantity: 1000, cost_price: 1.2, market_price: 1.25, instrument_type: 'etf', book: 'catalyst', theme: 'semi' }],
  },
  daily_authorization: null,
  recent_events: [{ event_id: 'evt1', severity: 'L3', symbol: '588200.SH', book: 'catalyst', action: 'reduce_half', quantity: 500, reason: '最高浮盈回撤达到3个百分点', advice_mode: 'executable', generated_at: '2026-07-11T10:30:00+08:00' }],
  capabilities: { position_sources: ['csv', 'clipboard', 'ocr'], notification_channels: ['telegram', 'enterprise_wechat'], miniqmt_execution: 'fail_closed_until_configured_and_authorized' },
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><DecisionCenter /></QueryClientProvider>)
}

describe('DecisionCenter page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getDecisionLoopStatus).mockResolvedValue({ ok: true, data: status } as never)
    vi.mocked(previewDecisionPositions).mockResolvedValue({
      ok: true,
      data: {
        preview_id: 'preview1', additions: [], removals: [], changes: [], unchanged: 1,
        proposed_snapshot: { content_hash: 'hash1', positions: status.current_position_snapshot.positions },
      },
    } as never)
    vi.mocked(confirmDecisionPositions).mockResolvedValue({ ok: true, data: {} } as never)
    vi.mocked(acknowledgeDecisionEvent).mockResolvedValue({ ok: true, data: {} } as never)
  })

  it('renders status, non-empty rule tables, positions, and dual-channel events', async () => {
    const { container } = renderPage()
    expect(await screen.findByText('量化决策中心')).toBeInTheDocument()
    expect(screen.getByText('催化交易仓')).toBeInTheDocument()
    expect(screen.getByText('权益日内高点回撤 3%')).toBeInTheDocument()
    expect(screen.getAllByText('588200.SH').length).toBeGreaterThan(0)
    expect(screen.getByText('Telegram')).toBeInTheDocument()
    expect(screen.getByText('企业微信')).toBeInTheDocument()
    expect(container.children.length).toBeGreaterThan(0)
  })

  it('executes preview then hash-confirm interaction', async () => {
    renderPage()
    await screen.findByText('量化决策中心')
    fireEvent.change(screen.getByLabelText('持仓CSV或剪贴板内容'), { target: { value: '证券代码\t持仓数量\t成本价\n588200.SH\t1000\t1.2' } })
    fireEvent.click(screen.getByRole('button', { name: /生成差异预览/ }))
    expect(await screen.findByText(/待确认：新增 0，删除 0，变更 0，不变 1/)).toBeInTheDocument()
    expect(previewDecisionPositions).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /确认覆盖当前组合/ }))
    await waitFor(() => expect(confirmDecisionPositions).toHaveBeenCalledWith('preview1', 'hash1'))
  })

  it('acknowledges one event across both notification channels', async () => {
    renderPage()
    await screen.findByText('量化决策中心')
    fireEvent.click(screen.getByRole('button', { name: '双通道确认' }))
    await waitFor(() => expect(acknowledgeDecisionEvent).toHaveBeenCalledWith('evt1', expect.anything()))
  })
})
