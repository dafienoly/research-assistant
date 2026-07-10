// @ts-nocheck
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Tag, Button, Spin, Modal, Descriptions, Alert,
  Space, Typography, message, Tooltip, Input, Row, Col, Statistic,
  Divider, Progress,
} from 'antd'
import {
  WarningOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ExperimentOutlined, ReloadOutlined, FundOutlined,
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import { API } from '../App'
import PageHeader from '../components/common/PageHeader'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import StatusDot from '../components/common/StatusDot'

const { Text, Title } = Typography

// ─── Types ──────────────────────────────────────────────────────
interface FactorRow {
  id: string
  factor_name: string
  family: string
  factor_expression?: string
  IC?: number
  RankIC?: number
  ICIR?: number
  TopBottom?: number
  excess_vs_semiconductor_ew?: number
  cost_adjusted_return?: number
  turnover?: number
  max_drawdown?: number
  risk_flags?: string[]
  status: string
  failure_reason?: string
}

interface FactorDetail {
  factor_name: string
  family: string
  factor_expression: string
  IC: number
  RankIC: number
  ICIR: number
  TopBottom: number
  cost_adjusted_return: number
  turnover: number
  max_drawdown: number
  risk_flags: string[]
  risk_attribution?: {
    risk_decomposition: Record<string, number>
    risk_exposure: { beta: number; specific_risk: number }
  }
  status: string
  failure_reason?: string
  ic_series?: { date: string; ic: number; rank_ic: number }[]
  layered_returns?: { layer: string; value: number }[]
}

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

function statusTag(status: string) {
  const map: Record<string, { color: string; text: string }> = {
    active: { color: 'success', text: '活跃' },
    retired: { color: 'error', text: '已退役' },
    deprecated: { color: 'warning', text: '已弃用' },
    draft: { color: 'default', text: '草稿' },
  }
  const c = map[status] || { color: 'default', text: status }
  return <Tag color={c.color}>{c.text}</Tag>
}

function riskFlagTags(flags: string[] | undefined) {
  if (!flags || flags.length === 0) return <Text type="secondary">无</Text>
  return (
    <Space size={4} wrap>
      {flags.map(f => {
        const isHighRisk = f === 'size_exposure' || f === 'beta_exposure'
        return (
          <Tag key={f} color={isHighRisk ? 'red' : 'orange'} style={{ fontSize: 11 }}>
            {f}
          </Tag>
        )
      })}
    </Space>
  )
}

// ─── IC Chart ───────────────────────────────────────────────────
function ICChart({ data }: { data?: { date: string; ic: number; rank_ic: number }[] }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 32, color: '#94A3B8' }}>
        暂无 IC 时序数据 — 请运行因子验证或等待数据刷新
      </div>
    )
  }
  const option = {
    tooltip: { trigger: 'axis' as const },
    legend: { data: ['IC', 'RankIC'], bottom: 0 },
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category' as const,
      data: data.map(d => d.date),
      axisLabel: { fontSize: 10, rotate: 45 },
    },
    yAxis: { type: 'value' as const, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: 'IC',
        type: 'line' as const,
        data: data.map(d => +(d.ic * 100).toFixed(2)),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#2563EB', width: 2 },
      },
      {
        name: 'RankIC',
        type: 'line' as const,
        data: data.map(d => +(d.rank_ic * 100).toFixed(2)),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#7C3AED', width: 2, type: 'dashed' },
      },
    ],
  }
  return <ReactEChartsCore option={option} style={{ height: 250 }} />
}

// ─── Layered Returns Chart ──────────────────────────────────────
function LayeredReturnsChart({ data }: { data?: { layer: string; value: number }[] }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 32, color: '#94A3B8' }}>
        暂无分层收益数据 — 请运行因子验证或等待数据刷新
      </div>
    )
  }
  const colors = data.map(d => (d.value >= 0 ? '#059669' : '#DC2626'))
  const option = {
    tooltip: { trigger: 'axis' as const, formatter: (p: { name: string; value: number }[]) => `${p[0].name}: ${p[0].value.toFixed(2)}%` },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: data.map(d => d.layer),
    },
    yAxis: { type: 'value' as const, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        type: 'bar' as const,
        data: data.map((d, i) => ({ value: d.value, itemStyle: { color: colors[i] } })),
        barWidth: '60%',
      },
    ],
  }
  return <ReactEChartsCore option={option} style={{ height: 220 }} />
}

// ─── Risk Attribution Pie ───────────────────────────────────────
function RiskPieChart({ data }: { data?: Record<string, number> }) {
  if (!data || Object.keys(data).length === 0) {
    return <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 24 }}>暂无风险归因数据</Text>
  }
  const option = {
    tooltip: { trigger: 'item' as const, formatter: '{b}: {d}%' },
    series: [
      {
        type: 'pie' as const,
        radius: ['40%', '70%'],
        center: ['50%', '50%'],
        data: Object.entries(data).map(([k, v]) => ({
          name: k,
          value: +(v * 100).toFixed(1),
        })),
        label: { formatter: '{b}\n{d}%' },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' },
        },
      },
    ],
  }
  return <ReactEChartsCore option={option} style={{ height: 240 }} />
}

// ═════════════════════════════════════════════════════════════════
//  FactorLab Page Component
// ═════════════════════════════════════════════════════════════════
export default function FactorLab() {
  // ─── State ────────────────────────────────────────────────────
  const [factors, setFactors] = useState<FactorRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Detail modal
  const [detail, setDetail] = useState<FactorDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Validate modal
  const [validateOpen, setValidateOpen] = useState(false)
  const [validateName, setValidateName] = useState('')
  const [validateExpr, setValidateExpr] = useState('')
  const [validating, setValidating] = useState(false)
  const [validateResult, setValidateResult] = useState<any>(null)

  // ─── Batch Compute ──────────────────────────────────────────
  const [computing, setComputing] = useState(false)
  const handleComputeAll = useCallback(async () => {
    setComputing(true)
    try {
      const r = await fetch(`${API}/api/factors/compute-all`, { method: 'POST' })
      const json = await r.json()
      if (json?.ok) {
        message.success(`批量计算完成: ${json.data?.computed || 0} 个因子`)
        fetchFactors() // 自动刷新
      } else {
        message.error(json?.error?.message || '批量计算失败')
      }
    } catch (e: any) {
      message.error('批量计算请求失败: ' + (e.message || ''))
    } finally {
      setComputing(false)
    }
  }, [])

  // ─── Data Fetching ────────────────────────────────────────────
  const fetchFactors = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${API}/api/factors`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      const rawList = json?.data?.factors || json?.factors || []
      // Normalize data: map backend fields to FactorRow
      const mapped: FactorRow[] = rawList.map((f: any, i: number) => ({
        id: f.id || f.factor_name || `factor_${i}`,
        factor_name: f.factor_name || f.name || f.id || `因子 ${i}`,
        family: f.family || f.category || '未分类',
        factor_expression: f.factor_expression || f.expression || '',
        IC: f.IC ?? f.ic ?? undefined,
        RankIC: f.RankIC ?? f.rank_ic ?? undefined,
        ICIR: f.ICIR ?? f.icir ?? undefined,
        TopBottom: f.TopBottom ?? f.top_bottom ?? undefined,
        excess_vs_semiconductor_ew: f.excess_vs_semiconductor_ew ?? undefined,
        cost_adjusted_return: f.cost_adjusted_return ?? f.cost_adjusted_return_pct ?? undefined,
        turnover: f.turnover ?? f.two_way_turnover ?? undefined,
        max_drawdown: f.max_drawdown ?? f.max_drawdown_pct ?? undefined,
        risk_flags: f.risk_flags ?? (f.risk_exposure?.exposure_type ? [f.risk_exposure.exposure_type] : undefined),
        status: f.status || 'active',
        failure_reason: f.failure_reason ?? undefined,
      }))
      setFactors(mapped)
    } catch (e: any) {
      setError(e.message || '加载因子数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchFactors()
  }, [fetchFactors])

  // ─── Detail Modal ─────────────────────────────────────────────
  const showDetail = useCallback(async (row: FactorRow) => {
    setDetailLoading(true)
    setDetail(null)
    try {
      // Fetch detail + risk attribution in parallel
      const [detailRes, riskRes] = await Promise.allSettled([
        fetch(`${API}/api/factors/${row.id}`).then(r => r.json()),
        fetch(`${API}/api/factors/${row.id}/risk-attribution`).then(r => r.json()),
      ])

      const detailData = detailRes.status === 'fulfilled'
        ? detailRes.value?.data?.factor || detailRes.value?.data || detailRes.value
        : {}
      const riskData = riskRes.status === 'fulfilled'
        ? riskRes.value?.data || riskRes.value
        : null

      // Fetch IC series from API — no synthetic data
      let icSeries: { date: string; ic: number; rank_ic: number }[] | undefined
      try {
        const icRes = await fetch(`${API}/api/factors/${row.id}/ic`)
        if (icRes.ok) {
          const icJson = await icRes.json()
          icSeries = icJson?.data?.ic_series || icJson?.ic_series
        }
      } catch {
        // IC series API not available — leave as undefined (shows empty state)
      }

      // Fetch layered returns from API — no synthetic data
      let layeredReturns: { layer: string; value: number }[] | undefined
      try {
        const lrRes = await fetch(`${API}/api/factors/${row.id}/layered-returns`)
        if (lrRes.ok) {
          const lrJson = await lrRes.json()
          layeredReturns = lrJson?.data?.layered_returns || lrJson?.layered_returns
        }
      } catch {
        // Layered returns API not available — leave as undefined (shows empty state)
      }

      setDetail({
        factor_name: detailData.factor_name || row.factor_name,
        family: detailData.family || row.family,
        factor_expression: detailData.factor_expression || row.factor_expression || row.factor_name || '',
        IC: detailData.IC ?? row.IC ?? 0,
        RankIC: detailData.RankIC ?? row.RankIC ?? 0,
        ICIR: detailData.ICIR ?? row.ICIR ?? 0,
        TopBottom: detailData.TopBottom ?? row.TopBottom ?? 0,
        cost_adjusted_return: detailData.cost_adjusted_return ?? row.cost_adjusted_return ?? 0,
        turnover: detailData.turnover ?? row.turnover ?? 0,
        max_drawdown: detailData.max_drawdown ?? row.max_drawdown ?? 0,
        risk_flags: detailData.risk_flags || row.risk_flags || [],
        risk_attribution: riskData?.risk_decomposition
          ? {
              risk_decomposition: riskData.risk_decomposition,
              risk_exposure: riskData.risk_exposure || { beta: 0, specific_risk: 0 },
            }
          : undefined,
        status: detailData.status || row.status,
        failure_reason: detailData.failure_reason || row.failure_reason,
        ic_series: icSeries,
        layered_returns: layeredReturns,
      })
    } catch (e: any) {
      message.error('加载因子详情失败: ' + (e.message || '未知错误'))
    } finally {
      setDetailLoading(false)
    }
  }, [])

  // ─── Validate Factor ──────────────────────────────────────────
  const handleValidate = useCallback(async () => {
    if (!validateExpr.trim()) {
      message.warning('请输入因子表达式')
      return
    }
    setValidating(true)
    setValidateResult(null)
    try {
      const r = await fetch(`${API}/api/factors/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: validateName || undefined, expression: validateExpr }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      const data = json?.data || json
      setValidateResult(data)
      if (data?.valid) {
        message.success('因子验证通过!')
      } else {
        message.warning('因子验证发现警告或错误')
      }
    } catch (e: any) {
      message.error('验证失败: ' + (e.message || '未知错误'))
      setValidateResult({ valid: false, errors: [e.message || '验证请求失败'] })
    } finally {
      setValidating(false)
    }
  }, [validateName, validateExpr])

  // ─── Columns ──────────────────────────────────────────────────
  const columns = [
    {
      title: '因子名称',
      dataIndex: 'factor_name',
      key: 'factor_name',
      width: 160,
      fixed: 'left' as const,
      render: (v: string, r: FactorRow) => (
        <Space>
          <ExperimentOutlined style={{ color: '#64748B' }} />
          <Text strong style={{ color: '#0F172A' }}>{v}</Text>
          {r.status === 'retired' && (
            <Tooltip title={r.failure_reason || '无失败原因'}>
              <CloseCircleOutlined style={{ color: '#DC2626' }} />
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '族',
      dataIndex: 'family',
      key: 'family',
      width: 90,
      render: (v: string) => <Tag style={{ fontSize: 11 }}>{v}</Tag>,
    },
    {
      title: 'IC',
      dataIndex: 'IC',
      key: 'IC',
      width: 80,
      align: 'right' as const,
      sorter: (a: FactorRow, b: FactorRow) => (a.IC ?? 0) - (b.IC ?? 0),
      render: (v: number | undefined) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        const color = v > 0 ? '#059669' : v < 0 ? '#DC2626' : '#64748B'
        return <Text style={{ color, fontWeight: 600 }}>{fmtPct(v)}</Text>
      },
    },
    {
      title: 'RankIC',
      dataIndex: 'RankIC',
      key: 'RankIC',
      width: 80,
      align: 'right' as const,
      sorter: (a: FactorRow, b: FactorRow) => (a.RankIC ?? 0) - (b.RankIC ?? 0),
      render: (v: number | undefined) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        return <Text style={{ color: v > 0 ? '#059669' : '#64748B', fontWeight: 600 }}>{fmtPct(v)}</Text>
      },
    },
    {
      title: 'ICIR',
      dataIndex: 'ICIR',
      key: 'ICIR',
      width: 70,
      align: 'right' as const,
      sorter: (a: FactorRow, b: FactorRow) => (a.ICIR ?? 0) - (b.ICIR ?? 0),
      render: (v: number | undefined) => fmtNum(v, 2),
    },
    {
      title: 'Top-Bottom',
      dataIndex: 'TopBottom',
      key: 'TopBottom',
      width: 100,
      align: 'right' as const,
      sorter: (a: FactorRow, b: FactorRow) => (a.TopBottom ?? 0) - (b.TopBottom ?? 0),
      render: (v: number | undefined) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        return <Text style={{ color: v > 0 ? '#059669' : '#DC2626', fontWeight: 600 }}>{fmtPct(v)}</Text>
      },
    },
    {
      title: '超额(半导体等权)',
      dataIndex: 'excess_vs_semiconductor_ew',
      key: 'excess_vs_semiconductor_ew',
      width: 120,
      align: 'right' as const,
      sorter: (a: FactorRow, b: FactorRow) =>
        (a.excess_vs_semiconductor_ew ?? 0) - (b.excess_vs_semiconductor_ew ?? 0),
      render: (v: number | undefined, r: FactorRow) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        const isNegative = v < 0
        return (
          <Space>
            <Text
              style={{
                color: isNegative ? '#DC2626' : '#059669',
                fontWeight: 700,
              }}
            >
              {fmtPct(v)}
            </Text>
            {isNegative && <WarningOutlined style={{ color: '#DC2626' }} />}
          </Space>
        )
      },
    },
    {
      title: '成本后收益',
      dataIndex: 'cost_adjusted_return',
      key: 'cost_adjusted_return',
      width: 100,
      align: 'right' as const,
      sorter: (a: FactorRow, b: FactorRow) =>
        (a.cost_adjusted_return ?? 0) - (b.cost_adjusted_return ?? 0),
      render: (v: number | undefined) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        return (
          <Text
            strong
            style={{ color: v > 0 ? '#059669' : v < 0 ? '#DC2626' : '#0F172A' }}
          >
            {fmtPct(v)}
          </Text>
        )
      },
    },
    {
      title: '换手率',
      dataIndex: 'turnover',
      key: 'turnover',
      width: 80,
      align: 'right' as const,
      render: (v: number | undefined) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        return <Text>{fmtPct(v)}</Text>
      },
    },
    {
      title: '最大回撤',
      dataIndex: 'max_drawdown',
      key: 'max_drawdown',
      width: 90,
      align: 'right' as const,
      render: (v: number | undefined) => {
        if (v === undefined) return <Text type="secondary">-</Text>
        return <Text style={{ color: '#DC2626' }}>{fmtPct(v)}</Text>
      },
    },
    {
      title: '风险暴露',
      dataIndex: 'risk_flags',
      key: 'risk_flags',
      width: 160,
      render: (v: string[] | undefined) => riskFlagTags(v),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      filters: [
        { text: '活跃', value: 'active' },
        { text: '已退役', value: 'retired' },
        { text: '已弃用', value: 'deprecated' },
        { text: '草稿', value: 'draft' },
      ],
      onFilter: (value: any, record: FactorRow) => record.status === value,
      render: (v: string, r: FactorRow) => (
        <Space>
          {statusTag(v)}
          {v === 'retired' && r.failure_reason && (
            <Tooltip title={r.failure_reason}>
              <CloseCircleOutlined style={{ color: '#DC2626', cursor: 'pointer' }} />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  // ─── Row Class Name for Highlight ─────────────────────────────
  const rowClassName = (record: FactorRow) => {
    const classes: string[] = []
    if (record.excess_vs_semiconductor_ew !== undefined && record.excess_vs_semiconductor_ew < 0) {
      classes.push('row-danger-benchmark')
    }
    if (record.risk_flags) {
      const hasHighRisk = record.risk_flags.some(
        f => f === 'size_exposure' || f === 'beta_exposure',
      )
      if (hasHighRisk) {
        classes.push('row-danger-risk')
      }
    }
    return classes.join(' ')
  }

  // ─── Initial Loading ─────────────────────────────────────────
  if (loading && factors.length === 0) {
    return (
      <div>
        <PageHeader title="因子实验室" />
        <LoadingState tip="加载因子列表..." size="large" />
      </div>
    )
  }

  // ─── Error ──────────────────────────────────────────────────────
  if (error && factors.length === 0) {
    return (
      <div>
        <PageHeader title="因子实验室" />
        <ErrorState
          message="加载失败"
          description={error}
          onRetry={fetchFactors}
        />
      </div>
    )
  }

  // ─── Render ───────────────────────────────────────────────────
  return (
    <div className="animate-fade-in">
      {/* Page Header */}
      <PageHeader
        title="因子实验室"
        dataSource="Factor Lab V5.7"
        runId={factors.length > 0 ? `${factors.length} 个因子` : undefined}
      />

      {/* Summary Cards */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card style={cardStyle} styles={{ body: { padding: '16px 20px' } }}>
            <Statistic
              title="因子总数"
              value={factors.length}
              valueStyle={{ color: '#0F172A', fontSize: 28, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={cardStyle} styles={{ body: { padding: '16px 20px' } }}>
            <Statistic
              title="活跃因子"
              value={factors.filter(f => f.status === 'active').length}
              valueStyle={{ color: '#059669', fontSize: 28, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={cardStyle} styles={{ body: { padding: '16px 20px' } }}>
            <Statistic
              title="已退役"
              value={factors.filter(f => f.status === 'retired').length}
              valueStyle={{
                color: factors.filter(f => f.status === 'retired').length > 0 ? '#DC2626' : '#0F172A',
                fontSize: 28,
                fontWeight: 700,
              }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={cardStyle} styles={{ body: { padding: '16px 20px' } }}>
            <Statistic
              title="风险暴露"
              value={factors.filter(f => {
                if (!f.risk_flags) return false
                return f.risk_flags.some(rf => rf === 'size_exposure' || rf === 'beta_exposure')
              }).length}
              valueStyle={{ color: '#D97706', fontSize: 28, fontWeight: 700 }}
              suffix="个"
            />
          </Card>
        </Col>
      </Row>

      {/* Controls */}
      <Card style={cardStyle} styles={{ body: { padding: '12px 20px' } }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <StatusDot status={factors.length > 0 ? 'running' : 'idle'} size={6} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              点击行查看因子详情 · 红色行表示跑输基准或高风险暴露
            </Text>
          </Space>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchFactors} loading={loading}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              onClick={() => {
                setValidateOpen(true)
                setValidateResult(null)
                setValidateName('')
                setValidateExpr('')
              }}
            >
              运行验证
            </Button>
            <Button
              icon={<ExperimentOutlined />}
              onClick={handleComputeAll}
              loading={computing}
            >
              批量计算
            </Button>
          </Space>
        </Space>
      </Card>

      {/* Factor Table */}
      <Card style={cardStyle} styles={{ body: { padding: 0 } }}>
        <Table
          dataSource={factors}
          columns={columns}
          rowKey="id"
          loading={loading && factors.length === 0}
          size="small"
          scroll={{ x: 1400 }}
          pagination={{ pageSize: 25, showSizeChanger: true, pageSizeOptions: ['10', '25', '50'] }}
          rowClassName={rowClassName}
          onRow={(record) => ({
            onClick: () => showDetail(record),
            style: { cursor: 'pointer' },
          })}
          locale={{ emptyText: '暂无因子数据' }}
        />
      </Card>

      {/* ─── Detail Modal ─── */}
      <Modal
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={null}
        width={900}
        title={
          <Space>
            <FundOutlined />
            <span>{detail?.factor_name || '因子详情'}</span>
            {detail?.status && statusTag(detail.status)}
          </Space>
        }
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
            <div style={{ marginTop: 12, color: '#64748B' }}>加载因子详情...</div>
          </div>
        ) : detail ? (
          <div>
            {/* Basic Info */}
            <Descriptions
              column={3}
              size="small"
              bordered
              styles={{
                label: { background: '#F8FAFC', color: '#64748B' },
                content: { color: '#0F172A' },
              }}
            >
              <Descriptions.Item label="因子族">{detail.family}</Descriptions.Item>
              <Descriptions.Item label="状态">{statusTag(detail.status)}</Descriptions.Item>
              <Descriptions.Item label="成本后收益">
                <Text
                  strong
                  style={{ color: detail.cost_adjusted_return > 0 ? '#059669' : '#DC2626' }}
                >
                  {fmtPct(detail.cost_adjusted_return)}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="IC">{fmtPct(detail.IC)}</Descriptions.Item>
              <Descriptions.Item label="RankIC">{fmtPct(detail.RankIC)}</Descriptions.Item>
              <Descriptions.Item label="ICIR">{fmtNum(detail.ICIR)}</Descriptions.Item>
              <Descriptions.Item label="Top-Bottom">{fmtPct(detail.TopBottom)}</Descriptions.Item>
              <Descriptions.Item label="换手率">{fmtPct(detail.turnover)}</Descriptions.Item>
              <Descriptions.Item label="最大回撤">
                <Text style={{ color: '#DC2626' }}>{fmtPct(detail.max_drawdown)}</Text>
              </Descriptions.Item>
            </Descriptions>

            {/* Factor Expression */}
            {detail.factor_expression && (
              <div style={{ marginTop: 16 }}>
                <Text strong style={{ color: '#0F172A' }}>因子公式</Text>
                <div
                  style={{
                    marginTop: 6,
                    background: '#1E293B',
                    color: '#E2E8F0',
                    padding: '12px 16px',
                    borderRadius: 8,
                    fontFamily: 'monospace',
                    fontSize: 13,
                    overflowX: 'auto',
                  }}
                >
                  {detail.factor_expression}
                </div>
              </div>
            )}

            {/* Failure Reason (retired) */}
            {detail.status === 'retired' && detail.failure_reason && (
              <Alert
                type="error"
                message="因子退役原因"
                description={detail.failure_reason}
                showIcon
                style={{ marginTop: 16 }}
                icon={<CloseCircleOutlined />}
              />
            )}

            {/* IC Time Series Chart */}
            <Divider orientation="left" plain>
              <Text strong style={{ color: '#0F172A' }}>IC 时序</Text>
            </Divider>
            <ICChart data={detail.ic_series} />

            {/* Layered Returns Chart */}
            <Divider orientation="left" plain>
              <Text strong style={{ color: '#0F172A' }}>分层收益</Text>
            </Divider>
            <LayeredReturnsChart data={detail.layered_returns} />

            {/* Risk Attribution */}
            {detail.risk_attribution && (
              <>
                <Divider orientation="left" plain>
                  <Text strong style={{ color: '#0F172A' }}>风险归因</Text>
                </Divider>
                <Row gutter={24}>
                  <Col span={12}>
                    <Text strong style={{ color: '#0F172A', fontSize: 13 }}>风险分解</Text>
                    <RiskPieChart data={detail.risk_attribution.risk_decomposition} />
                  </Col>
                  <Col span={12}>
                    <Text strong style={{ color: '#0F172A', fontSize: 13 }}>风险暴露</Text>
                    {detail.risk_flags && detail.risk_flags.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <Space wrap>
                          {detail.risk_flags.map(f => (
                            <Tag
                              key={f}
                              color={f === 'size_exposure' || f === 'beta_exposure' ? 'red' : 'orange'}
                            >
                              {f}
                            </Tag>
                          ))}
                        </Space>
                      </div>
                    )}
                    <Descriptions
                      column={1}
                      size="small"
                      style={{ marginTop: 12 }}
                      styles={{
                        label: { background: '#F8FAFC', color: '#64748B' },
                        content: { color: '#0F172A' },
                      }}
                    >
                      <Descriptions.Item label="Beta">
                        {detail.risk_attribution.risk_exposure.beta.toFixed(2)}
                      </Descriptions.Item>
                      <Descriptions.Item label="特质风险">
                        {detail.risk_attribution.risk_exposure.specific_risk.toFixed(2)}
                      </Descriptions.Item>
                    </Descriptions>
                  </Col>
                </Row>
              </>
            )}
          </div>
        ) : null}
      </Modal>

      {/* ─── Validate Modal ─── */}
      <Modal
        open={validateOpen}
        onCancel={() => setValidateOpen(false)}
        footer={null}
        width={600}
        title={
          <Space>
            <ExperimentOutlined />
            <span>运行因子验证</span>
          </Space>
        }
      >
        <div style={{ padding: '8px 0' }}>
          <div style={{ marginBottom: 16 }}>
            <Text strong>因子名称</Text>
            <Input
              placeholder="可选，输入因子名称"
              value={validateName}
              onChange={e => setValidateName(e.target.value)}
              style={{ marginTop: 6 }}
              allowClear
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <Text strong>因子表达式</Text>
            <Input.TextArea
              placeholder="输入因子表达式，如: close / MA(close, 20) - 1"
              value={validateExpr}
              onChange={e => setValidateExpr(e.target.value)}
              rows={4}
              style={{ marginTop: 6, fontFamily: 'monospace' }}
            />
          </div>
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            onClick={handleValidate}
            loading={validating}
            style={{ width: '100%' }}
          >
            提交验证
          </Button>

          {/* Validate Result */}
          {validating && (
            <div style={{ textAlign: 'center', marginTop: 24 }}>
              <Progress
                type="circle"
                percent={50}
                status="active"
                format={() => '验证中...'}
              />
            </div>
          )}
          {validateResult && !validating && (
            <div style={{ marginTop: 24 }}>
              <Divider plain>
                <Text strong style={{ color: '#0F172A' }}>验证结果</Text>
              </Divider>

              {validateResult.valid ? (
                <Alert
                  type="success"
                  message="✅ 验证通过"
                  description={
                    <div>
                      <Text>建议 IC: {fmtPct(validateResult.suggested_ic)}</Text>
                      <br />
                      <Text>预估计算时间: {validateResult.estimated_compute_time_ms}ms</Text>
                    </div>
                  }
                  showIcon
                />
              ) : (
                <Alert
                  type="error"
                  message="❌ 验证失败"
                  description={
                    <div>
                      {(validateResult.errors || []).length > 0 && (
                        <ul style={{ margin: 0, paddingLeft: 20 }}>
                          {(validateResult.errors as string[]).map((e: string, i: number) => (
                            <li key={i}><Text style={{ color: '#DC2626' }}>{e}</Text></li>
                          ))}
                        </ul>
                      )}
                      {(validateResult.warnings || []).length > 0 && (
                        <>
                          <Text strong style={{ fontSize: 12 }}>警告:</Text>
                          <ul style={{ margin: 0, paddingLeft: 20 }}>
                            {(validateResult.warnings as string[]).map((w: string, i: number) => (
                              <li key={i}><Text style={{ color: '#D97706' }}>{w}</Text></li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  }
                  showIcon
                />
              )}
            </div>
          )}
        </div>
      </Modal>

      {/* ─── Styles ─── */}
      <style>{`
        .row-danger-benchmark {
          background-color: #FEF2F2 !important;
        }
        .row-danger-benchmark:hover td {
          background-color: #FEE2E2 !important;
        }
        .row-danger-risk {
          background-color: #FFF7ED !important;
        }
        .row-danger-risk:hover td {
          background-color: #FFEDD5 !important;
        }
        .row-danger-benchmark.row-danger-risk {
          background: linear-gradient(90deg, #FEF2F2 0%, #FFF7ED 100%) !important;
        }
        .row-danger-benchmark.row-danger-risk:hover td {
          background: linear-gradient(90deg, #FEE2E2 0%, #FFEDD5 100%) !important;
        }
      `}</style>
    </div>
  )
}
