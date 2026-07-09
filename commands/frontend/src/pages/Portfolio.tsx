import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Card, Table, Tag, Button, Alert, Typography, Space, Row, Col,
  Tooltip, message,
} from 'antd'
import {
  ThunderboltOutlined, WarningOutlined,
  CheckCircleOutlined, InfoCircleOutlined,
  RiseOutlined, FallOutlined, ExclamationCircleOutlined,
  StopOutlined, MinusCircleOutlined,
} from '@ant-design/icons'
import PageHeader from '../components/common/PageHeader'
import MetricCard from '../components/common/MetricCard'
import LoadingState from '../components/common/LoadingState'
import ErrorState from '../components/common/ErrorState'
import EmptyState from '../components/common/EmptyState'

const { Text } = Typography

// ─── Types ──────────────────────────────────────────────────────

interface PortfolioHolding {
  ticker: string
  name: string
  weight: number
  reason: string
  is_core?: boolean
  risk_status?: RiskStatus
  is_tradable?: boolean
  block_reasons?: string[]
  etf_replacement?: ETFAlternative | null
}

interface RiskStatus {
  is_st: boolean
  is_suspended: boolean
  is_limit_up: boolean
  is_limit_down: boolean
  is_low_liquidity: boolean
  is_non_tradable_board: boolean
  is_blocked: boolean
  block_reasons: string[]
}

interface ETFAlternative {
  ticker: string
  name: string
  track_index: string
  fee_rate?: number
}

interface RecommendationData {
  generated_at: string
  strategy: string
  holdings: PortfolioHolding[]
  expected_annual_return: number
  expected_volatility: number
  expected_sharpe: number
  risk_level: string
  status: string
  forbidden_list?: PortfolioHolding[]
  reduce_watch_list?: PortfolioHolding[]
  etf_alternatives?: ETFAlternative[]
}

interface PortfolioRiskExposure {
  total_exposure: number
  concentration_risk: string
  industry_exposure: { industry: string; weight: number }[]
  factor_exposure: { factor: string; value: number; direction: string }[]
  var_95: number
  max_drawdown_30d: number
  beta: number
  sharpe_ttm: number
}

interface ApprovalRecord {
  id: string
  action: string
  status: 'pending' | 'approved' | 'rejected'
  operator: string
  created_at: string
  updated_at?: string
  detail: string
}

// ─── Helpers ──────────────────────────────────────────────────────

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const body = await r.json()
  if (!body.ok) throw new Error(body.error?.message || body.error || '请求失败')
  return body.data as T
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const json = await r.json()
  if (!json.ok) throw new Error(json.error?.message || json.error || '请求失败')
  return json.data as T
}

function fmtPct(v: number | undefined | null, decimals = 2): string {
  if (v === undefined || v === null) return '-'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(decimals)}%`
}

function fmtNum(v: number | undefined | null, decimals = 2): string {
  if (v === undefined || v === null) return '-'
  return v.toFixed(decimals)
}

function generateBlockReasonTags(risk: RiskStatus | undefined): React.ReactNode {
  if (!risk) return null
  const reasons: React.ReactNode[] = []
  if (risk.is_st) reasons.push(<Tag key="st" color="error">ST</Tag>)
  if (risk.is_suspended) reasons.push(<Tag key="sus" color="warning">停牌</Tag>)
  if (risk.is_limit_up) reasons.push(<Tag key="lu" color="warning">涨停</Tag>)
  if (risk.is_limit_down) reasons.push(<Tag key="ld" color="error">跌停</Tag>)
  if (risk.is_low_liquidity) reasons.push(<Tag key="liq" color="orange">低流动性</Tag>)
  if (risk.is_non_tradable_board) reasons.push(<Tag key="board" color="orange">权限受限</Tag>)
  if (risk.is_blocked) {
    risk.block_reasons.forEach((r, i) => reasons.push(<Tag key={`b${i}`} color="red">{r}</Tag>))
  }
  if (reasons.length === 0) {
    return <Tag color="success" icon={<CheckCircleOutlined />}>正常</Tag>
  }
  return <Space size={4} wrap>{reasons}</Space>
}

const cardStyle = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
  marginBottom: 16,
}

const sectionTitleStyle = {
  fontSize: 15,
  fontWeight: 600,
  color: '#0F172A',
  marginBottom: 12,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}

// ═════════════════════════════════════════════════════════════════
//  Portfolio Page Component
// ═════════════════════════════════════════════════════════════════

export default function Portfolio() {
  // ─── State: Recommendation ──────────────────────────────────
  const [recommendation, setRecommendation] = useState<RecommendationData | null>(null)
  const [recLoading, setRecLoading] = useState(true)
  const [recError, setRecError] = useState<string | null>(null)

  // ─── State: Risk Exposure ───────────────────────────────────
  const [riskExposure, setRiskExposure] = useState<PortfolioRiskExposure | null>(null)
  const [riskLoading, setRiskLoading] = useState(true)
  const [riskError, setRiskError] = useState<string | null>(null)

  // ─── State: Approval History ────────────────────────────────
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([])
  const [approvalLoading, setApprovalLoading] = useState(true)
  const [approvalError, setApprovalError] = useState<string | null>(null)

  // ─── State: Run Button ──────────────────────────────────────
  const [running, setRunning] = useState(false)

  // ─── Derived data ─────────────────────────────────────────────
  const coreHoldings = useMemo(() => {
    if (!recommendation?.holdings) return []
    return recommendation.holdings.filter(h => h.is_core !== false)
  }, [recommendation])

  const satelliteHoldings = useMemo(() => {
    if (!recommendation?.holdings) return []
    return recommendation.holdings.filter(h => h.is_core === false)
  }, [recommendation])

  const forbiddenList = useMemo(() => {
    if (!recommendation?.holdings) return []
    return recommendation.holdings.filter(h => h.is_tradable === false || h.risk_status?.is_blocked)
  }, [recommendation])

  const reduceWatchList = useMemo(() => {
    if (recommendation?.reduce_watch_list) return recommendation.reduce_watch_list
    return recommendation?.forbidden_list ?? []
  }, [recommendation])

  const etfAlternatives = useMemo(() => {
    if (recommendation?.etf_alternatives) return recommendation.etf_alternatives
    // Extract from holdings that have etf_replacement
    if (!recommendation?.holdings) return []
    const etfs: ETFAlternative[] = []
    for (const h of recommendation.holdings) {
      if (h.etf_replacement) {
        etfs.push(h.etf_replacement)
      }
    }
    return etfs
  }, [recommendation])

  // ─── Data Fetching ─────────────────────────────────────────────

  const fetchRecommendation = useCallback(async (silent = false) => {
    if (!silent) setRecLoading(true)
    setRecError(null)
    try {
      const data = await apiGet<RecommendationData>('/api/portfolio/recommendation/latest')
      setRecommendation(data)
    } catch (e: any) {
      if (!silent) setRecError(e.message || '加载组合推荐失败')
    } finally {
      if (!silent) setRecLoading(false)
    }
  }, [])

  const fetchRiskExposure = useCallback(async (silent = false) => {
    if (!silent) setRiskLoading(true)
    setRiskError(null)
    try {
      const data = await apiGet<PortfolioRiskExposure>('/api/portfolio/risk')
      setRiskExposure(data)
    } catch (e: any) {
      if (!silent) setRiskError(e.message || '加载风险暴露失败')
      // Non-critical - page still works
    } finally {
      if (!silent) setRiskLoading(false)
    }
  }, [])

  const fetchApprovals = useCallback(async (silent = false) => {
    if (!silent) setApprovalLoading(true)
    setApprovalError(null)
    try {
      const data = await apiGet<ApprovalRecord[]>('/api/portfolio/approval-history')
      setApprovals(Array.isArray(data) ? data : [])
    } catch (e: any) {
      if (!silent) setApprovalError(e.message || '加载审批记录失败')
      // Non-critical - page still works
    } finally {
      if (!silent) setApprovalLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchRecommendation()
    fetchRiskExposure()
    fetchApprovals()
  }, [fetchRecommendation, fetchRiskExposure, fetchApprovals])

  // ─── Run Recommendation ────────────────────────────────────────
  const handleRunRecommendation = useCallback(async () => {
    setRunning(true)
    try {
      await apiPost('/api/portfolio/recommendation/run', {
        strategy: 'multi_factor',
        universe: 'all',
        risk_tolerance: 'moderate',
      })
      message.success('组合推荐任务已提交，正在计算中...')
      // Refresh after a short delay
      setTimeout(() => {
        fetchRecommendation()
        fetchRiskExposure()
        fetchApprovals()
      }, 3000)
    } catch (e: any) {
      message.error('运行组合推荐失败: ' + (e.message || '未知错误'))
    } finally {
      setRunning(false)
    }
  }, [fetchRecommendation, fetchRiskExposure, fetchApprovals])

  // ─── Table columns ─────────────────────────────────────────────

  const coreColumns = [
    {
      title: '代码',
      dataIndex: 'ticker',
      key: 'ticker',
      width: 110,
      render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      ellipsis: true,
    },
    {
      title: '权重',
      dataIndex: 'weight',
      key: 'weight',
      width: 80,
      align: 'right' as const,
      sorter: (a: PortfolioHolding, b: PortfolioHolding) => (a.weight ?? 0) - (b.weight ?? 0),
      render: (v: number) => (
        <Text strong style={{ color: '#0F172A' }}>{fmtPct(v / 100)}</Text>
      ),
    },
    {
      title: '入选原因',
      dataIndex: 'reason',
      key: 'reason',
      width: 280,
      ellipsis: true,
      render: (v: string) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '风控状态',
      key: 'risk_status',
      width: 200,
      render: (_: unknown, r: PortfolioHolding) => generateBlockReasonTags(r.risk_status),
    },
  ]

  const satelliteColumns = [
    {
      title: '代码',
      dataIndex: 'ticker',
      key: 'ticker',
      width: 110,
      render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      ellipsis: true,
    },
    {
      title: '权重',
      dataIndex: 'weight',
      key: 'weight',
      width: 80,
      align: 'right' as const,
      render: (v: number) => (
        <Text strong style={{ color: '#7C3AED' }}>{fmtPct(v / 100)}</Text>
      ),
    },
    {
      title: '入选原因',
      dataIndex: 'reason',
      key: 'reason',
      width: 280,
      ellipsis: true,
      render: (v: string) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '风控状态',
      key: 'risk_status',
      width: 200,
      render: (_: unknown, r: PortfolioHolding) => generateBlockReasonTags(r.risk_status),
    },
  ]

  const etfColumns = [
    {
      title: '代码',
      dataIndex: 'ticker',
      key: 'ticker',
      width: 110,
      render: (v: string) => <code style={{ color: '#2563EB' }}>{v}</code>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      ellipsis: true,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '跟踪指数',
      dataIndex: 'track_index',
      key: 'track_index',
      width: 260,
      ellipsis: true,
      render: (v: string) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '费率',
      dataIndex: 'fee_rate',
      key: 'fee_rate',
      width: 80,
      align: 'right' as const,
      render: (v: number | undefined) => v != null ? `${v}%` : '-',
    },
  ]

  const forbiddenColumns = [
    {
      title: '代码',
      dataIndex: 'ticker',
      key: 'ticker',
      width: 110,
      render: (v: string) => <code style={{ color: '#DC2626' }}>{v}</code>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      ellipsis: true,
      render: (v: string) => <Text style={{ color: '#DC2626' }}>{v}</Text>,
    },
    {
      title: '禁止原因',
      key: 'reason',
      width: 250,
      render: (_: unknown, r: PortfolioHolding) => {
        const reasons = r.risk_status?.block_reasons
        if (reasons && reasons.length > 0) {
          return reasons.map((br, i) => <Tag key={i} color="red">{br}</Tag>)
        }
        return r.reason || '风控拦截'
      },
    },
    {
      title: 'ETF替代',
      key: 'etf_replace',
      width: 200,
      render: (_: unknown, r: PortfolioHolding) => {
        if (!r.etf_replacement) return <Text type="secondary">无</Text>
        return (
          <Tooltip title={r.etf_replacement.track_index}>
            <Tag color="blue" style={{ cursor: 'pointer' }}>
              {r.etf_replacement.name} ({r.etf_replacement.ticker})
            </Tag>
          </Tooltip>
        )
      },
    },
  ]

  const reduceWatchColumns = [
    {
      title: '代码',
      dataIndex: 'ticker',
      key: 'ticker',
      width: 110,
      render: (v: string) => <code style={{ color: '#D97706' }}>{v}</code>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      ellipsis: true,
      render: (v: string) => <Text style={{ color: '#D97706' }}>{v}</Text>,
    },
    {
      title: '减仓原因',
      key: 'reason',
      width: 300,
      render: (_: unknown, r: PortfolioHolding) => r.reason || '列入观察',
    },
    {
      title: '风控提示',
      key: 'risk_status',
      width: 180,
      render: (_: unknown, r: PortfolioHolding) => generateBlockReasonTags(r.risk_status),
    },
  ]

  const approvalColumns = [
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      width: 120,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => {
        const map: Record<string, { color: string; text: string }> = {
          pending: { color: 'processing', text: '待审批' },
          approved: { color: 'success', text: '已通过' },
          rejected: { color: 'error', text: '已驳回' },
        }
        const c = map[v] || { color: 'default', text: v }
        return <Tag color={c.color}>{c.text}</Tag>
      },
    },
    {
      title: '操作人',
      dataIndex: 'operator',
      key: 'operator',
      width: 120,
    },
    {
      title: '说明',
      dataIndex: 'detail',
      key: 'detail',
      width: 250,
      ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string) => v?.slice(0, 19) ?? '-',
    },
  ]

  // ─── Section: Risk Exposure ────────────────────────────────────

  const renderRiskExposure = () => {
    if (riskLoading) return <LoadingState tip="加载风险暴露..." />
    if (riskError) return <ErrorState message="风险暴露数据不可用" description={riskError} onRetry={() => fetchRiskExposure()} />
    if (!riskExposure) return <EmptyState description="暂无风险暴露数据" />

    return (
      <div>
        <Row gutter={[16, 16]}>
          <Col span={4}>
            <MetricCard
              title="总暴露"
              value={fmtPct(riskExposure.total_exposure)}
              color={riskExposure.total_exposure > 1 ? 'error' : 'primary'}
            />
          </Col>
          <Col span={4}>
            <MetricCard
              title="集中度风险"
              value={riskExposure.concentration_risk || '-'}
              color={riskExposure.concentration_risk === 'high' ? 'error' : riskExposure.concentration_risk === 'medium' ? 'warning' : 'success'}
            />
          </Col>
          <Col span={4}>
            <MetricCard
              title="VaR (95%)"
              value={fmtPct(riskExposure.var_95)}
              color="warning"
            />
          </Col>
          <Col span={4}>
            <MetricCard
              title="30日最大回撤"
              value={fmtPct(riskExposure.max_drawdown_30d)}
              color="error"
            />
          </Col>
          <Col span={4}>
            <MetricCard
              title="Beta"
              value={fmtNum(riskExposure.beta, 2)}
              color={Math.abs(riskExposure.beta) > 1.2 ? 'error' : 'primary'}
            />
          </Col>
          <Col span={4}>
            <MetricCard
              title="Sharpe (TTM)"
              value={fmtNum(riskExposure.sharpe_ttm, 2)}
              color={riskExposure.sharpe_ttm > 1 ? 'success' : riskExposure.sharpe_ttm > 0 ? 'warning' : 'error'}
            />
          </Col>
        </Row>

        {riskExposure.industry_exposure?.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Text strong style={{ fontSize: 13 }}>行业暴露</Text>
            <div style={{ marginTop: 8 }}>
              <Space wrap>
                {riskExposure.industry_exposure.map((ind) => {
                  const isHigh = ind.weight > 0.25
                  return (
                    <Tooltip key={ind.industry} title={`${ind.industry}: ${(ind.weight * 100).toFixed(1)}%`}>
                      <Tag color={isHigh ? 'red' : 'blue'} style={{ fontSize: 12, padding: '2px 8px' }}>
                        {ind.industry} {(ind.weight * 100).toFixed(0)}%
                      </Tag>
                    </Tooltip>
                  )
                })}
              </Space>
            </div>
          </div>
        )}

        {riskExposure.factor_exposure?.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Text strong style={{ fontSize: 13 }}>因子暴露</Text>
            <div style={{ marginTop: 8 }}>
              <Space wrap>
                {riskExposure.factor_exposure.map((f) => {
                  const icon = f.direction === 'positive' ? <RiseOutlined /> : f.direction === 'negative' ? <FallOutlined /> : <MinusCircleOutlined />
                  return (
                    <Tag key={f.factor} icon={icon} color={f.direction === 'positive' ? 'green' : f.direction === 'negative' ? 'red' : 'default'}>
                      {f.factor}: {fmtNum(f.value, 2)}
                    </Tag>
                  )
                })}
              </Space>
            </div>
          </div>
        )}
      </div>
    )
  }

  // ─── Loading state (initial) ──────────────────────────────────
  if (recLoading && !recommendation) {
    return (
      <div>
        <PageHeader title="组合推荐" />
        <LoadingState tip="加载组合推荐数据..." />
      </div>
    )
  }

  // ─── Error state (no data) ─────────────────────────────────────
  if (recError && !recommendation) {
    return (
      <div>
        <PageHeader title="组合推荐" />
        <Alert
          type="error"
          message="加载组合推荐数据失败"
          description={recError}
          showIcon
          closable
          action={<Button size="small" onClick={() => fetchRecommendation()}>重试</Button>}
          style={{ marginBottom: 16 }}
        />
      </div>
    )
  }

  // ══════════════════════════════════════════════════════════════
  //  Normal Render
  // ══════════════════════════════════════════════════════════════
  return (
    <div>
      <PageHeader
        title="组合推荐"
        dataSource={recommendation?.generated_at
          ? `生成: ${recommendation.generated_at.slice(0, 19)}`
          : undefined}
      />

      {/* Action bar */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <MetricCard
            title="策略"
            value={recommendation?.strategy || '-'}
            color="primary"
          />
        </Col>
        <Col span={6}>
          <MetricCard
            title="预期年化收益"
            value={recommendation?.expected_annual_return != null
              ? fmtPct(recommendation.expected_annual_return)
              : '-'}
            color="success"
          />
        </Col>
        <Col span={6}>
          <MetricCard
            title="预期波动率"
            value={recommendation?.expected_volatility != null
              ? fmtPct(recommendation.expected_volatility)
              : '-'}
            color="warning"
          />
        </Col>
        <Col span={6}>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleRunRecommendation}
            loading={running}
            style={{ width: '100%', height: 80, fontSize: 16, borderRadius: 10 }}
          >
            运行推荐
          </Button>
        </Col>
      </Row>

      {/* ── 1. Core Portfolio Table ──────────────────────────────── */}
      <Card style={cardStyle}>
        <div style={sectionTitleStyle}>
          <CheckCircleOutlined style={{ color: '#059669' }} />
          核心组合
          {!recLoading && <Tag color="success">{coreHoldings.length} 只</Tag>}
        </div>
        {recLoading ? (
          <LoadingState size="small" tip="加载核心组合..." />
        ) : coreHoldings.length > 0 ? (
          <Table
            dataSource={coreHoldings}
            columns={coreColumns}
            rowKey={(r) => r.ticker}
            scroll={{ x: 'max-content' }}
            size="small"
            pagination={false}
          />
        ) : (
          <EmptyState description="暂无核心组合" />
        )}
      </Card>

      {/* ── 2. Satellite Portfolio Table ─────────────────────────── */}
      <Card style={cardStyle}>
        <div style={sectionTitleStyle}>
          <RiseOutlined style={{ color: '#7C3AED' }} />
          卫星组合
          {!recLoading && <Tag color="purple">{satelliteHoldings.length} 只</Tag>}
        </div>
        {recLoading ? (
          <LoadingState size="small" tip="加载卫星组合..." />
        ) : satelliteHoldings.length > 0 ? (
          <Table
            dataSource={satelliteHoldings}
            columns={satelliteColumns}
            rowKey={(r) => r.ticker}
            scroll={{ x: 'max-content' }}
            size="small"
            pagination={false}
          />
        ) : (
          <EmptyState description="暂无卫星组合" />
        )}
      </Card>

      {/* ── 3. ETF Alternatives Table ────────────────────────────── */}
      <Card style={cardStyle}>
        <div style={sectionTitleStyle}>
          <InfoCircleOutlined style={{ color: '#2563EB' }} />
          ETF 替代方案
          {!recLoading && <Tag color="blue">{etfAlternatives.length} 只</Tag>}
        </div>
        {recLoading ? (
          <LoadingState size="small" tip="加载 ETF 替代方案..." />
        ) : etfAlternatives.length > 0 ? (
          <Table
            dataSource={etfAlternatives}
            columns={etfColumns}
            rowKey={(r) => r.ticker}
            scroll={{ x: 'max-content' }}
            size="small"
            pagination={false}
          />
        ) : (
          <EmptyState description="暂无 ETF 替代方案" />
        )}
      </Card>

      {/* ── 4. Forbidden Buy List ──────────────────────────────── */}
      <Card style={{ ...cardStyle, borderLeft: '4px solid #DC2626' }}>
        <div style={sectionTitleStyle}>
          <StopOutlined style={{ color: '#DC2626' }} />
          <span style={{ color: '#DC2626' }}>禁止买入清单</span>
          {!recLoading && <Tag color="error">{forbiddenList.length} 只</Tag>}
        </div>
        {recLoading ? (
          <LoadingState size="small" tip="加载禁止买入清单..." />
        ) : forbiddenList.length > 0 ? (
          <Table
            dataSource={forbiddenList}
            columns={forbiddenColumns}
            rowKey={(r) => r.ticker}
            scroll={{ x: 'max-content' }}
            size="small"
            pagination={false}
          />
        ) : (
          <Alert
            type="success"
            message="当前无禁止买入股票"
            showIcon
            icon={<CheckCircleOutlined />}
            style={{ margin: 0 }}
          />
        )}
      </Card>

      {/* ── 5. Reduce Position Watch List ────────────────────────── */}
      <Card style={{ ...cardStyle, borderLeft: '4px solid #D97706' }}>
        <div style={sectionTitleStyle}>
          <WarningOutlined style={{ color: '#D97706' }} />
          <span style={{ color: '#D97706' }}>减仓观察清单</span>
          {!recLoading && <Tag color="warning">{reduceWatchList.length} 只</Tag>}
        </div>
        {recLoading ? (
          <LoadingState size="small" tip="加载减仓观察清单..." />
        ) : reduceWatchList.length > 0 ? (
          <Table
            dataSource={reduceWatchList}
            columns={reduceWatchColumns}
            rowKey={(r) => r.ticker}
            scroll={{ x: 'max-content' }}
            size="small"
            pagination={false}
          />
        ) : (
          <Alert
            type="info"
            message="当前无减仓观察标的"
            showIcon
            icon={<CheckCircleOutlined />}
            style={{ margin: 0 }}
          />
        )}
      </Card>

      {/* ── 6. Portfolio Risk Exposure ──────────────────────────── */}
      <Card style={{ ...cardStyle, borderLeft: '4px solid #7C3AED' }}>
        <div style={sectionTitleStyle}>
          <ExclamationCircleOutlined style={{ color: '#7C3AED' }} />
          组合风险暴露
        </div>
        {renderRiskExposure()}
      </Card>

      {/* ── 7. Approval History ────────────────────────────────── */}
      <Card style={cardStyle}>
        <div style={sectionTitleStyle}>
          <InfoCircleOutlined style={{ color: '#64748B' }} />
          审批记录
          {!approvalLoading && <Tag>{approvals.length} 条</Tag>}
        </div>
        {approvalLoading ? (
          <LoadingState size="small" tip="加载审批记录..." />
        ) : approvalError ? (
          <ErrorState
            message="审批记录加载失败"
            description={approvalError}
            onRetry={() => fetchApprovals()}
          />
        ) : approvals.length > 0 ? (
          <Table
            dataSource={approvals}
            columns={approvalColumns}
            rowKey={(r) => r.id}
            scroll={{ x: 'max-content' }}
            size="small"
            pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: ['5', '10', '20'] }}
          />
        ) : (
          <EmptyState description="暂无审批记录" />
        )}
      </Card>
    </div>
  )
}
