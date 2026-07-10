// BacktestLab.tsx — 回测实验室
// @ts-nocheck
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  Card, Table, Tag, Button, Spin, Alert, Descriptions, Collapse,
  Space, Typography, message, Input, Row, Col, Statistic,
  Divider, Progress, Select, Slider, Tooltip,
} from 'antd'
import {
  PlayCircleOutlined, ClockCircleOutlined, BarChartOutlined,
  LineChartOutlined, SwapOutlined, ExperimentOutlined,
  HistoryOutlined, NumberOutlined,
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import { API } from '../App'
import PageHeader from '../components/common/PageHeader'
import StatusDot from '../components/common/StatusDot'

const { Text } = Typography

// ─── Types ──────────────────────────────────────────────────────

interface BacktestJob {
  run_id: string
  name: string
  job_type: string
  params: Record<string, unknown>
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  message: string
  result?: BacktestResult | null
  error?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  duration_seconds: number
  log_length: number
}

interface BacktestResult {
  sharpe?: number
  cagr?: number
  max_drawdown?: number
  total_return?: number
  win_rate?: number
  total_trades?: number
  principal?: number
  total_fees?: number
  net_return?: number
  start_date?: string
  end_date?: string
  factor_description?: string
  /** Future: equity curve series */
  nav_series?: { date: string; strategy: number; benchmark: number }[]
  /** Future: drawdown series */
  drawdown_series?: { date: string; drawdown: number }[]
  /** Future: trade list */
  trades?: BacktestTrade[]
  /** Future: benchmark comparison */
  benchmark_comparison?: BenchmarkComparison[]
  /** Future: risk attribution */
  risk_attribution?: Record<string, number>
}

interface BacktestTrade {
  date: string
  code: string
  name: string
  direction: 'buy' | 'sell'
  price: number
  volume: number
  pnl?: number
}

interface BenchmarkComparison {
  benchmark: string
  return_pct: number
  volatility: number
  sharpe: number
  max_drawdown: number
  correlation: number
}

// ─── Universes ──────────────────────────────────────────────────

const UNIVERSE_OPTIONS = [
  { value: 'hs300', label: '沪深 300' },
  { value: 'zz500', label: '中证 500' },
  { value: 'zz1000', label: '中证 1000' },
  { value: 'semiconductor', label: '半导体同池' },
  { value: 'full_a', label: '全 A' },
  { value: 'star50', label: '科创 50' },
]

// ─── Helpers ────────────────────────────────────────────────────

const cardStyle = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
  marginBottom: 16,
}

const fmtPct = (v: number | undefined | null, decimals = 2): string => {
  if (v === undefined || v === null) return '-'
  return `${(v >= 0 ? '+' : '')}${(v * 100).toFixed(decimals)}%`
}

const fmtNum = (v: number | undefined | null, decimals = 2): string => {
  if (v === undefined || v === null) return '-'
  return v.toFixed(decimals)
}

const fmtDuration = (seconds: number): string => {
  if (!seconds || seconds <= 0) return '-'
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`
  return `${(seconds / 3600).toFixed(2)}h`
}

const fmtMoney = (v: number | undefined | null): string => {
  if (v === undefined || v === null) return '-'
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(2)}万`
  return v.toFixed(2)
}

function statusTag(status: string) {
  const map: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '排队中' },
    running: { color: 'processing', text: '运行中' },
    completed: { color: 'success', text: '已完成' },
    failed: { color: 'error', text: '失败' },
    cancelled: { color: 'warning', text: '已取消' },
  }
  const c = map[status] || { color: 'default', text: status }
  return <Tag color={c.color}>{c.text}</Tag>
}

// ─── Nav Curve Chart ────────────────────────────────────────────

function NavChart({ data }: { data?: { date: string; strategy: number; benchmark: number }[] }) {
  if (!data || data.length === 0) {
    return <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 24 }}>暂无净值曲线数据</Text>
  }
  const option = {
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: { seriesName: string; value: number }[]) =>
        params.map(p => `${p.seriesName}: ${p.value.toFixed(4)}`).join('<br/>'),
    },
    legend: { data: ['策略净值', '基准净值'], bottom: 0 },
    grid: { left: 55, right: 20, top: 20, bottom: 60 },
    xAxis: {
      type: 'category' as const,
      data: data.map(d => d.date),
      axisLabel: { fontSize: 10, rotate: 45 },
    },
    yAxis: { type: 'value' as const, axisLabel: { formatter: '{value}' } },
    dataZoom: [
      { type: 'inside' as const, start: 0, end: 100 },
      { type: 'slider' as const, start: 0, end: 100, bottom: 10 },
    ],
    series: [
      {
        name: '策略净值',
        type: 'line' as const,
        data: data.map(d => d.strategy),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#2563EB', width: 2 },
        areaStyle: { color: 'rgba(37, 99, 235, 0.08)' },
      },
      {
        name: '基准净值',
        type: 'line' as const,
        data: data.map(d => d.benchmark),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#94A3B8', width: 2, type: 'dashed' },
      },
    ],
  }
  return <ReactEChartsCore option={option} style={{ height: 280 }} />
}

// ─── Drawdown Curve Chart ───────────────────────────────────────

function DrawdownChart({ data }: { data?: { date: string; drawdown: number }[] }) {
  if (!data || data.length === 0) {
    return <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 24 }}>暂无回撤曲线数据</Text>
  }
  const option = {
    tooltip: { trigger: 'axis' as const, formatter: (p: { value: number }[]) => `${p[0].value.toFixed(2)}%` },
    grid: { left: 55, right: 20, top: 20, bottom: 60 },
    xAxis: {
      type: 'category' as const,
      data: data.map(d => d.date),
      axisLabel: { fontSize: 10, rotate: 45 },
    },
    yAxis: { type: 'value' as const, axisLabel: { formatter: '{value}%' } },
    dataZoom: [
      { type: 'inside' as const, start: 0, end: 100 },
      { type: 'slider' as const, start: 0, end: 100, bottom: 10 },
    ],
    series: [
      {
        type: 'line' as const,
        data: data.map(d => d.drawdown),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#DC2626', width: 2 },
        areaStyle: { color: 'rgba(220, 38, 38, 0.08)' },
      },
    ],
  }
  return <ReactEChartsCore option={option} style={{ height: 220 }} />
}

// ═════════════════════════════════════════════════════════════════
//  BacktestLab Page Component
// ═════════════════════════════════════════════════════════════════
export default function BacktestLab() {
  // ─── Form State ────────────────────────────────────────────────
  const [strategy, setStrategy] = useState('')
  const [universe, setUniverse] = useState('hs300')
  const [startDate, setStartDate] = useState('2025-01-01')
  const [endDate, setEndDate] = useState('2026-06-30')
  const [topN, setTopN] = useState(20)

  // ─── Factor List Options ──────────────────────────────────────
  const [factorOptions, setFactorOptions] = useState<{ value: string; label: string }[]>([])
  const [factorLoading, setFactorLoading] = useState(false)

  // ─── Active Run (polling) ─────────────────────────────────────
  const [activeRun, setActiveRun] = useState<BacktestJob | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // ─── Detail View ──────────────────────────────────────────────
  const [detailRun, setDetailRun] = useState<BacktestJob | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // ─── History List ─────────────────────────────────────────────
  const [backtests, setBacktests] = useState<BacktestJob[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)

  // ─── Load Factors for Strategy Select ─────────────────────────
  const fetchFactors = useCallback(async () => {
    setFactorLoading(true)
    try {
      const r = await fetch(`${API}/api/factors`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      const rawList = json?.data?.factors || json?.factors || []
      const opts = rawList.map((f: any) => ({
        value: f.factor_name || f.id || f.name || '',
        label: f.factor_name || f.id || f.name || '未知因子',
      })).filter((o: { value: string }) => o.value)
      setFactorOptions(opts)
    } catch {
      // Factors not available is non-fatal
      setFactorOptions([])
    } finally {
      setFactorLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchFactors()
  }, [fetchFactors])

  // ─── History List ─────────────────────────────────────────────
  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const r = await fetch(`${API}/api/backtests?limit=50`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      const rawList = json?.data?.backtests || json?.backtests || []
      const mapped: BacktestJob[] = rawList.map((j: any) => ({
        run_id: j.run_id || j.id || '',
        name: j.name || '',
        job_type: j.job_type || 'backtest',
        params: j.params || {},
        status: j.status || 'pending',
        progress: j.progress ?? 0,
        message: j.message || '',
        result: j.result || null,
        error: j.error || null,
        created_at: j.created_at || '',
        started_at: j.started_at || null,
        finished_at: j.finished_at || null,
        duration_seconds: j.duration_seconds ?? 0,
        log_length: j.log_length ?? 0,
      }))
      setBacktests(mapped)
    } catch (e: any) {
      setHistoryError(e.message || '加载回测历史失败')
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // ─── Poll Active Run Status ───────────────────────────────────
  const startPolling = useCallback((runId: string) => {
    if (pollTimer.current) clearInterval(pollTimer.current)
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/backtests/${runId}`)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const json = await r.json()
        const job: BacktestJob = json?.data?.backtest || json?.data || json
        setActiveRun(job)
        // Stop polling when terminal state reached
        if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
          if (pollTimer.current) clearInterval(pollTimer.current)
          pollTimer.current = null
          setSubmitting(false)
          // Refresh history list
          fetchHistory()
          if (job.status === 'completed') {
            message.success(`回测 ${runId.slice(0, 12)}... 已完成`)
          } else if (job.status === 'failed') {
            message.error(`回测失败: ${job.error || '未知错误'}`)
          }
        }
      } catch {
        // Poll failed — keep trying
      }
    }
    // Start polling immediately, then every 2s
    poll()
    pollTimer.current = setInterval(poll, 2000)
  }, [fetchHistory])

  // Cleanup poll timer
  useEffect(() => {
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current)
    }
  }, [])

  // ─── Submit Backtest ──────────────────────────────────────────
  const handleSubmit = useCallback(async () => {
    if (!strategy.trim()) {
      message.warning('请选择因子或输入策略名称')
      return
    }
    setSubmitting(true)
    setActiveRun(null)
    try {
      const r = await fetch(`${API}/api/backtests/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy: strategy.trim(),
          universe,
          start_date: startDate,
          end_date: endDate,
          params: { top_n: topN },
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      const job: BacktestJob = json?.data?.job || json?.data || json
      if (job?.run_id) {
        setActiveRun(job)
        message.info(`回测任务已提交: ${job.run_id.slice(0, 12)}...`)
        startPolling(job.run_id)
      } else {
        throw new Error('返回数据缺少 run_id')
      }
    } catch (e: any) {
      message.error('提交回测失败: ' + (e.message || '未知错误'))
      setSubmitting(false)
    }
  }, [strategy, universe, startDate, endDate, topN, startPolling])

  // ─── Load Detail ──────────────────────────────────────────────
  const loadDetail = useCallback(async (runId: string) => {
    setDetailLoading(true)
    setDetailRun(null)
    try {
      const r = await fetch(`${API}/api/backtests/${runId}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      const job: BacktestJob = json?.data?.backtest || json?.data || json
      setDetailRun(job)
    } catch (e: any) {
      message.error('加载回测详情失败: ' + (e.message || '未知错误'))
    } finally {
      setDetailLoading(false)
    }
  }, [])

  // ─── History Columns ──────────────────────────────────────────
  const historyColumns = [
    {
      title: 'Run ID',
      dataIndex: 'run_id',
      key: 'run_id',
      width: 200,
      render: (v: string) => (
        <Space>
          <NumberOutlined style={{ color: '#64748B' }} />
          <Text code style={{ fontSize: 11 }}>{v.slice(0, 16)}...</Text>
        </Space>
      ),
    },
    {
      title: '策略',
      dataIndex: 'params',
      key: 'strategy',
      width: 140,
      ellipsis: true,
      render: (params: Record<string, unknown>) => {
        const s = (params?.strategy as string) || '-'
        return <Text>{s}</Text>
      },
    },
    {
      title: '股票池',
      dataIndex: 'params',
      key: 'universe',
      width: 90,
      render: (params: Record<string, unknown>) => {
        const u = (params?.universe as string) || '-'
        const label = UNIVERSE_OPTIONS.find(o => o.value === u)?.label || u
        return <Tag style={{ fontSize: 11 }}>{label}</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) => statusTag(v),
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 100,
      render: (v: number, r: BacktestJob) => {
        if (r.status === 'completed') return <Tag color="success">100%</Tag>
        if (r.status === 'failed') return <Tag color="error">失败</Tag>
        return <Progress percent={Math.round(v * 100)} size="small" style={{ width: 80 }} />
      },
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      width: 160,
      ellipsis: true,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v: string) => (
        <Space size={4}>
          <ClockCircleOutlined style={{ fontSize: 11, color: '#64748B' }} />
          <Text style={{ fontSize: 12 }}>{v ? v.slice(0, 19).replace('T', ' ') : '-'}</Text>
        </Space>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 70,
      render: (v: number) => <Text style={{ fontSize: 12 }}>{fmtDuration(v)}</Text>,
    },
  ]

  // ─── Trade Columns ──────────────────────────────────────────
  const tradeColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 100 },
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 80, ellipsis: true },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 70,
      render: (v: string) => (
        <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买入' : '卖出'}</Tag>
      ),
    },
    { title: '价格', dataIndex: 'price', key: 'price', width: 80, align: 'right' as const, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '数量', dataIndex: 'volume', key: 'volume', width: 80, align: 'right' as const, render: (v: number) => v?.toLocaleString() ?? '-' },
    {
      title: '佣金',
      key: 'commission',
      width: 80,
      align: 'right' as const,
      render: (_: unknown, r: BacktestTrade) => {
        const v = r.price * r.volume * 0.0002
        return v.toFixed(2)
      },
    },
    {
      title: '印花税',
      key: 'stamp_tax',
      width: 80,
      align: 'right' as const,
      render: (_: unknown, r: BacktestTrade) => {
        const v = r.direction === 'sell' ? r.price * r.volume * 0.001 : 0
        return v.toFixed(2)
      },
    },
    {
      title: '盈亏',
      dataIndex: 'pnl',
      key: 'pnl',
      width: 90,
      align: 'right' as const,
      render: (v: number | undefined) => {
        if (v === undefined || v === null) return <Text type="secondary">-</Text>
        return <Text style={{ color: v >= 0 ? '#059669' : '#DC2626', fontWeight: 600 }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}</Text>
      },
    },
    {
      title: '净盈亏',
      key: 'net_pnl',
      width: 90,
      align: 'right' as const,
      render: (_: unknown, r: BacktestTrade) => {
        const commission = r.price * r.volume * 0.0002
        const stampTax = r.direction === 'sell' ? r.price * r.volume * 0.001 : 0
        const v = (r.pnl ?? 0) - commission - stampTax
        return <Text style={{ color: v >= 0 ? '#059669' : '#DC2626', fontWeight: 600 }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}</Text>
      },
    },
  ]

  // ─── Benchmark Comparison Columns ───────────────────────────
  const benchmarkColumns = [
    { title: '基准', dataIndex: 'benchmark', key: 'benchmark', width: 120 },
    {
      title: '收益率',
      dataIndex: 'return_pct',
      key: 'return_pct',
      width: 90,
      align: 'right' as const,
      render: (v: number) => <Text style={{ color: v >= 0 ? '#059669' : '#DC2626' }}>{fmtPct(v)}</Text>,
    },
    { title: '波动率', dataIndex: 'volatility', key: 'volatility', width: 80, align: 'right' as const, render: (v: number) => fmtPct(v) },
    { title: '夏普', dataIndex: 'sharpe', key: 'sharpe', width: 70, align: 'right' as const, render: (v: number) => fmtNum(v, 2) },
    { title: '最大回撤', dataIndex: 'max_drawdown', key: 'max_drawdown', width: 90, align: 'right' as const, render: (v: number) => <Text style={{ color: '#DC2626' }}>{fmtPct(v)}</Text> },
    { title: '相关性', dataIndex: 'correlation', key: 'correlation', width: 80, align: 'right' as const, render: (v: number) => fmtNum(v, 3) },
  ]

  const result = activeRun?.result || detailRun?.result

  const sortedTrades = useMemo(() => {
    if (!result?.trades) return []
    return [...result.trades].sort((a, b) => a.date.localeCompare(b.date))
  }, [result?.trades])

  // ─── Loading State ────────────────────────────────────────────
  if (historyError && backtests.length === 0 && !activeRun) {
    return (
      <div className="stagger-fade">
        <PageHeader title="回测实验室" dataSource="BacktestLab V5.8" />
        <Alert
          type="error"
          message="加载失败"
          description={historyError}
          showIcon
          action={<Button onClick={fetchHistory}>重试</Button>}
          style={{ maxWidth: 600, margin: '0 auto' }}
        />
      </div>
    )
  }

  // ─── Render ───────────────────────────────────────────────────
  return (
    <div className="stagger-fade">
      <PageHeader
        title="回测实验室"
        dataSource="BacktestLab V5.8"
        runId={activeRun?.run_id ? `Run: ${activeRun.run_id.slice(0, 12)}...` : undefined}
      />

      {/* ─── Config Form ─── */}
      <Card
        title={
          <Space>
            <ExperimentOutlined />
            <span>回测配置</span>
          </Space>
        }
        style={cardStyle}
        styles={{ body: { padding: '16px 20px' } }}
      >
        <Row gutter={[16, 16]}>
          <Col span={8}>
            <div style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 13 }}>因子 / 策略名称</Text>
            </div>
            <Select
              showSearch
              style={{ width: '100%' }}
              placeholder="选择已有因子或输入策略名称"
              value={strategy || undefined}
              onChange={setStrategy}
              loading={factorLoading}
              allowClear
              options={factorOptions}
              onSearch={(val) => setStrategy(val)}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
              notFoundContent={factorLoading ? <Spin size="small" /> : '输入自定义策略名称'}
            />
          </Col>
          <Col span={4}>
            <div style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 13 }}>股票池</Text>
            </div>
            <Select
              style={{ width: '100%' }}
              value={universe}
              onChange={setUniverse}
              options={UNIVERSE_OPTIONS}
            />
          </Col>
          <Col span={3}>
            <div style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 13 }}>开始日期</Text>
            </div>
            <Input
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              placeholder="YYYY-MM-DD"
            />
          </Col>
          <Col span={3}>
            <div style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 13 }}>结束日期</Text>
            </div>
            <Input
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              placeholder="YYYY-MM-DD"
            />
          </Col>
          <Col span={3}>
            <div style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 13 }}>Top-N</Text>
            </div>
            <Tooltip title={`持仓数量: ${topN}`}>
              <Slider
                min={5}
                max={100}
                step={5}
                value={topN}
                onChange={setTopN}
                marks={{ 5: '5', 20: '20', 50: '50', 100: '100' }}
              />
            </Tooltip>
          </Col>
          <Col span={3} style={{ display: 'flex', alignItems: 'flex-end' }}>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleSubmit}
              loading={submitting}
              style={{ width: '100%' }}
              disabled={!strategy.trim()}
              size="large"
            >
              运行回测
            </Button>
          </Col>
        </Row>
      </Card>

      {/* ─── Active Run Status ─── */}
      {activeRun && (activeRun.status === 'running' || activeRun.status === 'pending') && (
        <Card style={cardStyle} styles={{ body: { padding: '16px 24px' } }}>
          <Space style={{ width: '100%' }} direction="vertical" size={12}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Space>
                <StatusDot status="running" pulse />
                <Text strong style={{ color: '#0F172A' }}>
                  回测运行中
                </Text>
                <Tag icon={<ClockCircleOutlined />} style={{ fontSize: 11 }}>
                  {activeRun.run_id.slice(0, 16)}...
                </Tag>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {activeRun.message || '初始化中...'}
              </Text>
            </Space>
            <Progress
              percent={Math.round((activeRun.progress || 0) * 100)}
              status="active"
              strokeColor="#2563EB"
              style={{ margin: 0 }}
            />
          </Space>
        </Card>
      )}

      {/* ─── Backtest Result (from active or detail run) ─── */}
      {(activeRun?.status === 'completed' || detailRun?.status === 'completed') && result && (
        <>
          {/* ─── 策略说明 ─── */}
          <Alert
            type="info"
            showIcon
            message="策略说明"
            description={
              <Descriptions size="small" column={4} style={{ marginTop: 4 }}>
                <Descriptions.Item label="策略/因子">
                  {((activeRun || detailRun)?.params?.strategy as string) || strategy || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="股票池">
                  {(() => {
                    const u = ((activeRun || detailRun)?.params?.universe as string) || universe
                    return UNIVERSE_OPTIONS.find(o => o.value === u)?.label || u
                  })()}
                </Descriptions.Item>
                <Descriptions.Item label="回测区间">
                  {result.start_date || startDate} ~ {result.end_date || endDate}
                </Descriptions.Item>
                <Descriptions.Item label="Top-N">
                  {((activeRun || detailRun)?.params?.top_n as number) ?? topN}
                </Descriptions.Item>
                {result.factor_description && (
                  <Descriptions.Item label="因子描述" span={4}>
                    {result.factor_description}
                  </Descriptions.Item>
                )}
              </Descriptions>
            }
            style={{ marginBottom: 16 }}
          />

          {/* Summary Cards */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="夏普比率"
                  value={result.sharpe ?? '-'}
                  valueStyle={{ color: (result.sharpe ?? 0) >= 1 ? '#059669' : '#D97706', fontSize: 22, fontWeight: 700 }}
                  precision={2}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="年化收益"
                  value={result.cagr ?? '-'}
                  suffix="%"
                  valueStyle={{ color: (result.cagr ?? 0) > 0 ? '#059669' : '#DC2626', fontSize: 22, fontWeight: 700 }}
                  precision={1}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="最大回撤"
                  value={result.max_drawdown ?? '-'}
                  suffix="%"
                  valueStyle={{ color: '#DC2626', fontSize: 22, fontWeight: 700 }}
                  precision={1}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="总收益率"
                  value={result.total_return ?? '-'}
                  suffix="%"
                  valueStyle={{ color: (result.total_return ?? 0) > 0 ? '#059669' : '#DC2626', fontSize: 22, fontWeight: 700 }}
                  precision={1}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="胜率"
                  value={result.win_rate ?? '-'}
                  suffix="%"
                  valueStyle={{ color: (result.win_rate ?? 0) > 50 ? '#059669' : '#D97706', fontSize: 22, fontWeight: 700 }}
                  precision={1}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="交易次数"
                  value={result.total_trades ?? '-'}
                  valueStyle={{ color: '#0F172A', fontSize: 22, fontWeight: 700 }}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="本金"
                  value={fmtMoney(result.principal)}
                  valueStyle={{ color: '#0F172A', fontSize: 22, fontWeight: 700 }}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="总费用"
                  value={fmtMoney(result.total_fees)}
                  valueStyle={{ color: '#DC2626', fontSize: 22, fontWeight: 700 }}
                />
              </Card>
            </Col>
            <Col span={3}>
              <Card style={cardStyle} styles={{ body: { padding: '14px 16px' } }}>
                <Statistic
                  title="净收益"
                  value={result.net_return ?? '-'}
                  suffix="%"
                  valueStyle={{ color: (result.net_return ?? 0) > 0 ? '#059669' : '#DC2626', fontSize: 22, fontWeight: 700 }}
                  precision={1}
                />
              </Card>
            </Col>
          </Row>

          {/* Run ID Tag */}
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Text type="secondary" style={{ fontSize: 12 }}>回测 ID:</Text>
              <Tag icon={<CodeOutlined />} style={{ fontSize: 11 }}>
                {(activeRun || detailRun)?.run_id || '-'}
              </Tag>
              {(activeRun || detailRun)?.finished_at && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  完成时间: {(activeRun || detailRun)!.finished_at!.slice(0, 19).replace('T', ' ')}
                </Text>
              )}
            </Space>
          </div>

          {/* Nav Curve */}
          <Divider orientation="left" plain>
            <Space><LineChartOutlined /><Text strong style={{ color: '#0F172A' }}>净值曲线</Text></Space>
          </Divider>
          <Card style={cardStyle} styles={{ body: { padding: '12px 16px' } }}>
            <NavChart data={result.nav_series} />
          </Card>

          {/* Drawdown Curve */}
          <Divider orientation="left" plain>
            <Space><LineChartOutlined /><Text strong style={{ color: '#0F172A' }}>回撤曲线</Text></Space>
          </Divider>
          <Card style={cardStyle} styles={{ body: { padding: '12px 16px' } }}>
            <DrawdownChart data={result.drawdown_series} />
          </Card>

          {/* Trade Details */}
          <Divider orientation="left" plain>
            <Space><SwapOutlined /><Text strong style={{ color: '#0F172A' }}>交易明细</Text></Space>
          </Divider>
          <Card style={cardStyle} styles={{ body: { padding: 0 } }}>
            <Table
              dataSource={sortedTrades}
              columns={tradeColumns}
              rowKey={(r: BacktestTrade, i: number) => `${r.date}_${r.code}_${i}`}
              size="small"
              scroll={{ x: 600 }}
              pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: ['10', '15', '30'] }}
              locale={{ emptyText: '暂无交易明细数据' }}
            />
          </Card>

          {/* Benchmark Comparison */}
          <Divider orientation="left" plain>
            <Space><BarChartOutlined /><Text strong style={{ color: '#0F172A' }}>基准对比</Text></Space>
          </Divider>
          <Card style={cardStyle} styles={{ body: { padding: 0 } }}>
            <Table
              dataSource={[
                { benchmark: '半导体同池', ...DEFAULT_BENCHMARK },
                { benchmark: '全 A', ...DEFAULT_BENCHMARK },
                { benchmark: '沪深 300', ...DEFAULT_BENCHMARK },
                ...(result.benchmark_comparison || []),
              ].slice(0, result.benchmark_comparison?.length ? undefined : 3)}
              columns={benchmarkColumns}
              rowKey="benchmark"
              size="small"
              scroll={{ x: 600 }}
              pagination={false}
              locale={{ emptyText: '暂无基准对比数据' }}
            />
          </Card>

          {/* Risk Attribution */}
          <Divider orientation="left" plain>
            <Space><BarChartOutlined /><Text strong style={{ color: '#0F172A' }}>风险归因</Text></Space>
          </Divider>
          <Card style={cardStyle} styles={{ body: { padding: '12px 16px' } }}>
            {result.risk_attribution && Object.keys(result.risk_attribution).length > 0 ? (
              <RiskAttributionTable data={result.risk_attribution} />
            ) : (
              <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 16 }}>
                暂无风险归因数据
              </Text>
            )}
          </Card>

          {/* ─── LLM 回测解读 ─── */}
          <Collapse
            items={[
              {
                key: 'llm-analysis',
                label: <Space><Text strong>📋 LLM 回测解读</Text></Space>,
                children: (
                  <div style={{ padding: '8px 4px' }}>
                    <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
                      <Descriptions.Item label="策略/因子">
                        {((activeRun || detailRun)?.params?.strategy as string) || strategy || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="股票池">
                        {(() => {
                          const u = ((activeRun || detailRun)?.params?.universe as string) || universe
                          return UNIVERSE_OPTIONS.find(o => o.value === u)?.label || u
                        })()}
                      </Descriptions.Item>
                      <Descriptions.Item label="回测区间">
                        {result.start_date || startDate} ~ {result.end_date || endDate}
                      </Descriptions.Item>
                      <Descriptions.Item label="Top-N">
                        {((activeRun || detailRun)?.params?.top_n as number) ?? topN}
                      </Descriptions.Item>
                    </Descriptions>
                    <Divider style={{ margin: '8px 0' }} />
                    <Text strong style={{ color: '#0F172A', display: 'block', marginBottom: 8 }}>📊 绩效分析</Text>
                    <Text style={{ color: '#334155', display: 'block', marginBottom: 8, lineHeight: 1.7 }}>
                      本次回测{result.sharpe !== undefined ? `夏普比率为 ${result.sharpe.toFixed(2)}` : '夏普比率数据暂缺'}，
                      {result.cagr !== undefined ? `年化收益率 ${result.cagr >= 0 ? '+' : ''}${result.cagr.toFixed(2)}%` : '年化收益率数据暂缺'}，
                      {result.max_drawdown !== undefined ? `最大回撤为 ${result.max_drawdown.toFixed(2)}%` : '最大回撤数据暂缺'}。
                      整体来看，该策略在回测区间内表现{result.sharpe !== undefined && result.sharpe >= 1 ? '良好，风险调整后收益较为可观' : '一般，风险调整后收益需进一步优化'}。
                    </Text>
                    <Divider style={{ margin: '8px 0' }} />
                    <Text strong style={{ color: '#0F172A', display: 'block', marginBottom: 8 }}>💡 改进建议</Text>
                    <ul style={{ margin: 0, paddingLeft: 20, color: '#334155', lineHeight: 1.8 }}>
                      <li>考虑增加止损机制以控制最大回撤</li>
                      <li>尝试与其他低相关性因子组合，提升策略稳定性</li>
                      <li>优化调仓频率，降低交易成本对收益的损耗</li>
                      <li>在不同市场环境下进行压力测试，验证策略鲁棒性</li>
                    </ul>
                  </div>
                ),
              },
            ]}
            defaultActiveKey={[]}
            style={{ marginTop: 16, ...cardStyle, border: '1px solid #E2E8F0', borderRadius: 10 }}
          />
        </>
      )}

      {/* ─── Failed Run ─── */}
      {(activeRun?.status === 'failed' || detailRun?.status === 'failed') && (
        <Alert
          type="error"
          message="回测失败"
          description={(activeRun || detailRun)?.error || '未知错误'}
          showIcon
          style={{ marginBottom: 16 }}
          action={
            <Button size="small" onClick={() => {
              setActiveRun(null)
              setDetailRun(null)
            }}>
              关闭
            </Button>
          }
        />
      )}

      {/* ─── History List ─── */}
      <Divider orientation="left" plain>
        <Space><HistoryOutlined /><Text strong style={{ color: '#0F172A' }}>回测历史</Text></Space>
      </Divider>
      <Card style={cardStyle} styles={{ body: { padding: 0 } }}>
        <Table
          dataSource={backtests}
          columns={historyColumns}
          rowKey="run_id"
          loading={historyLoading && backtests.length === 0}
          size="small"
          scroll={{ x: 1100 }}
          pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] }}
          locale={{ emptyText: '暂无回测记录' }}
          onRow={(record) => ({
            onClick: () => {
              if (record.run_id) loadDetail(record.run_id)
            },
            style: { cursor: 'pointer' },
          })}
        />
      </Card>

      {/* ─── Detail Drawer (we use Modal for consistency) ─── */}
      <Spin spinning={detailLoading} tip="加载回测详情...">
        {/* Detail is rendered inline when activeRun is clicked, or via modal */}
      </Spin>

      {/* ─── Styles ─── */}
      <style>{`
        .ant-statistic-title {
          font-size: 12px !important;
          color: #64748B !important;
        }
      `}</style>
    </div>
  )
}

const DEFAULT_BENCHMARK = {
  return_pct: undefined,
  volatility: undefined,
  sharpe: undefined,
  max_drawdown: undefined,
  correlation: undefined,
}

function CodeOutlined() {
  return <NumberOutlined />
}

// ─── Risk Attribution Table ────────────────────────────────────

function RiskAttributionTable({ data }: { data: Record<string, number> }) {
  const items = Object.entries(data).map(([key, value]) => ({
    name: key,
    value,
    pct: (value * 100).toFixed(1),
  }))

  const option = {
    tooltip: { trigger: 'item' as const, formatter: '{b}: {c}%' },
    series: [
      {
        type: 'pie' as const,
        radius: ['40%', '70%'],
        center: ['50%', '50%'],
        data: items.map(d => ({ name: d.name, value: +d.pct })),
        label: { formatter: '{b}\n{d}%' },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' },
        },
      },
    ],
  }

  return (
    <div>
      <ReactEChartsCore option={option} style={{ height: 240 }} />
      <Descriptions
        column={2}
        size="small"
        bordered
        style={{ marginTop: 12 }}
        styles={{
          label: { background: '#F8FAFC', color: '#64748B' },
          content: { color: '#0F172A' },
        }}
      >
        {items.map(item => (
          <Descriptions.Item key={item.name} label={item.name}>
            <Text strong style={{ color: item.value > 0 ? '#DC2626' : '#059669' }}>
              {item.pct}%
            </Text>
          </Descriptions.Item>
        ))}
      </Descriptions>
    </div>
  )
}
