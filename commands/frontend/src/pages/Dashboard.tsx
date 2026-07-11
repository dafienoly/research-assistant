/** V5.3 首页投研驾驶舱 Dashboard — 视觉优化版 */
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Table, Tag, Typography, Space, Spin, Tooltip } from 'antd'
import {
  ClockCircleOutlined,
  DatabaseOutlined,
  WarningOutlined,
  ThunderboltOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  ExperimentOutlined,
  ApiOutlined,
  FieldNumberOutlined,
  FileTextOutlined,
  BugOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import MetricCard from '../components/common/MetricCard'
import StatusBadge from '../components/common/StatusBadge'
import StatusDot from '../components/common/StatusDot'
import LoadingState from '../components/common/LoadingState'
import PageHeader from '../components/common/PageHeader'
import type { StatusType } from '../types'
import {
  useSystemStatus,
  useDataOverview,
  useTushareStatus,
  useQmtHealth,
  useSemiThemeStatus,
  useLatestRecommendation,
  usePaperBalance,
  useLiveReadiness,
  useRecentTasks,
  useRiskAlerts,
} from '../hooks/useDashboardQueries'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

// ─── Styles ────────────────────────────────────────────────────────────────
const CARD: React.CSSProperties = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 10,
  marginBottom: 16,
}

const CARD_HOVER: React.CSSProperties = {
  ...CARD,
  cursor: 'pointer',
  transition: 'box-shadow 0.2s ease, transform 0.15s ease',
}

const META_LABEL: React.CSSProperties = { fontSize: 12, color: '#64748B' }

// ─── Helpers ────────────────────────────────────────────────────────────────
function fmtTime(iso?: string): string {
  if (!iso) return '—'
  return dayjs(iso).format('MM-DD HH:mm')
}

function fromNow(iso?: string): string {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}

function statusToBadge(s?: string): StatusType {
  if (!s) return 'idle'
  const m: Record<string, StatusType> = {
    healthy: 'completed',
    active: 'completed',
    connected: 'completed',
    ready: 'completed',
    pass: 'completed',
    ok: 'completed',
    degraded: 'pending',
    warning: 'pending',
    stale: 'pending',
    failed: 'failed',
    error: 'failed',
    inactive: 'failed',
    missing: 'failed',
    not_ready: 'failed',
    disconnected: 'failed',
    running: 'running',
    processing: 'running',
  }
  return m[s.toLowerCase()] || 'idle'
}

// ═══════════════════════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════════════════════
export default function Dashboard() {
  const navigate = useNavigate()

  // ─── All hooks ──────────────────────────────────────────────────────
  const { data: system, isLoading: loadingSystem } = useSystemStatus()
  const { data: dataOv, isLoading: loadingData } = useDataOverview()
  const { data: tushare, isLoading: loadingTushare } = useTushareStatus()
  const { data: qmt, isLoading: loadingQmt } = useQmtHealth()
  const { data: semi, isLoading: loadingSemi } = useSemiThemeStatus()
  const { data: portfolio, isLoading: loadingPortfolio } = useLatestRecommendation()
  const { data: paper, isLoading: loadingPaper } = usePaperBalance()
  const { data: live, isLoading: loadingLive } = useLiveReadiness()
  const { data: tasks, isLoading: loadingTasks } = useRecentTasks()
  const { data: alerts, isLoading: loadingAlerts } = useRiskAlerts()

  const anyLoading =
    loadingSystem || loadingData || loadingTushare || loadingQmt ||
    loadingSemi || loadingPortfolio || loadingPaper || loadingLive

  const allLoaded =
    system && (dataOv || true) && (tushare || true) && qmt &&
    (semi || true) && (portfolio || true) && (paper || true) && (live || true)

  // ─── First-load spinner ─────────────────────────────────────────────
  if (anyLoading && !allLoaded) {
    return <LoadingState tip="加载驾驶舱数据..." size="large" />
  }

  // ─── Data aggregation ───────────────────────────────────────────────
  const healthSummary = dataOv?.summary
  const tushareSources = tushare?.sources || []
  const events = tasks?.events || []
  const riskAlerts = alerts?.alerts || []

  return (
    <div
      style={{ maxWidth: 1600, margin: '0 auto' }}
      className="stagger-fade"
    >
      {/* ─── Page Header ──────────────────────────────────────────── */}
      <PageHeader
        title="📊 投研驾驶舱"
        updatedAt={fmtTime(system?.timestamp)}
        dataSource="Hermes API v5.0"
      />

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* Row 1: Key metric cards (4 columns)                          */}
      {/* ══════════════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 8 }}>
        {/* ── 1. System Status ────────────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <MetricCard
            title="系统状态"
            value={system?.status === 'healthy' ? '健康' : system?.status || '—'}
            color={system?.status === 'healthy' ? 'success' : 'error'}
            loading={loadingSystem}
          />
          {system && (
            <div style={{ padding: '2px 12px 8px', marginTop: -8 }}>
              <Space size={12}>
                <span style={META_LABEL}><ClockCircleOutlined /> {fmtTime(system.timestamp)}</span>
                <span style={META_LABEL}>v{system.version}</span>
              </Space>
            </div>
          )}
        </Col>

        {/* ── 2. Data Health ──────────────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card
            style={{ ...CARD_HOVER, padding: 16 }}
            onClick={() => navigate('/data')}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = ''
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  <DatabaseOutlined /> 数据健康
                </Typography.Text>
                <div style={{ fontSize: 28, fontWeight: 600, color: '#0F172A', marginTop: 4 }}>
                  {healthSummary ? `${healthSummary.active}/${healthSummary.total_sources}` : '—'}
                </div>
                <Space size={8} style={{ marginTop: 4 }}>
                  {healthSummary && healthSummary.blocking_issues > 0 && (
                    <Tag color="error" style={{ cursor: 'pointer' }} onClick={() => navigate('/data')}>
                      {healthSummary.blocking_issues} 阻塞
                    </Tag>
                  )}
                  {healthSummary && healthSummary.degraded > 0 && (
                    <Tag color="warning">{healthSummary.degraded} 降级</Tag>
                  )}
                  {healthSummary && healthSummary.freshness_status && (
                    <Tag color={healthSummary.freshness_status === 'ok' ? 'success' : 'warning'}>
                      {healthSummary.freshness_status}
                    </Tag>
                  )}
                </Space>
              </div>
              <StatusDot status={healthSummary?.blocking_issues ? 'error' : 'running'} size={10} />
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: '#94A3B8' }}>
              更新时间: {fmtTime(dataOv?.checked_at)} | 数据源: HermesDB
            </div>
          </Card>
        </Col>

        {/* ── 3. Tushare Status ────────────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card style={CARD}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <ApiOutlined /> Tushare 数据源
            </Typography.Text>
            <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
              {tushareSources.length > 0 ? (
                tushareSources.slice(0, 3).map((s) => (
                  <div key={s.source_id} style={{ flex: 1, minWidth: 80 }}>
                    <div style={{ fontSize: 20, fontWeight: 600, color: '#0F172A' }}>
                      {s.health?.success_rate?.toFixed(0) || '—'}%
                    </div>
                    <div style={{ fontSize: 11, color: '#64748B' }}>{s.source_id}</div>
                    <StatusDot status={s.status === 'active' ? 'running' : 'error'} size={6} />
                    <Tag color={s.status === 'active' ? 'success' : 'error'} style={{ fontSize: 10, margin: 0 }}>
                      {s.status}
                    </Tag>
                  </div>
                ))
              ) : (
                <div style={{ fontSize: 14, color: '#94A3B8' }}>
                  <Tag color="default">无 Tushare</Tag>
                </div>
              )}
            </div>
          </Card>
        </Col>

        {/* ── 4. QMT Status ────────────────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card
            style={{ ...CARD_HOVER, padding: 16 }}
            onClick={() => navigate('/qmt')}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = ''
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <ThunderboltOutlined /> QMT 交易接口
            </Typography.Text>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
              <StatusDot
                status={qmt?.connected ? 'running' : 'error'}
                size={12}
                pulse={qmt?.connected}
              />
              <span style={{ fontSize: 18, fontWeight: 600, color: qmt?.connected ? '#059669' : '#DC2626' }}>
                {qmt?.connected ? '在线' : '离线'}
              </span>
            </div>
            {qmt && (
              <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 4 }}>
                模式: {qmt.mode} | 延迟: {qmt.latency_ms}ms | v{qmt.version}
              </div>
            )}
            <div style={{ marginTop: 4, fontSize: 11, color: '#94A3B8' }}>
              心跳: {fromNow(qmt?.last_heartbeat)} | 数据源: QMT
            </div>
          </Card>
        </Col>
      </Row>

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* Row 2: Theme & Portfolio (second row of 4)                   */}
      {/* ══════════════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 8 }}>
        {/* ── 5. Semiconductor Theme ──────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card
            style={{ ...CARD_HOVER, padding: 16 }}
            onClick={() => navigate('/semi')}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = ''
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <BarChartOutlined /> 半导体主题
            </Typography.Text>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <div>
                <div style={{ fontSize: 22, fontWeight: 600, color: '#0F172A' }}>
                  {semi ? (semi.sentiment_score * 100).toFixed(0) : '—'}
                  <span style={{ fontSize: 12, fontWeight: 400, color: '#64748B', marginLeft: 4 }}>分</span>
                </div>
                <Tag
                  color={semi?.sentiment === 'bullish' ? 'success' : semi?.sentiment === 'bearish' ? 'error' : 'warning'}
                  style={{ marginTop: 4 }}
                >
                  {semi?.sentiment === 'bullish' ? '看多' : semi?.sentiment === 'bearish' ? '看空' : '中性'}
                </Tag>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 12, color: '#64748B' }}>ETF {semi?.etf.ticker}</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: '#0F172A' }}>
                  {semi?.etf.price.toFixed(3) || '—'}
                </div>
                <span style={{ fontSize: 12, color: (semi?.etf.change_pct ?? 0) >= 0 ? '#059669' : '#DC2626' }}>
                  {(semi?.etf.change_pct ?? 0) >= 0 ? '+' : ''}{semi?.etf.change_pct?.toFixed(2)}%
                </span>
              </div>
            </div>
            {semi && (
              <div style={{ marginTop: 8, fontSize: 11, color: '#94A3B8' }}>
                PE: {semi.metrics.pe_ttm} | PB: {semi.metrics.pb} |
                营收增: {semi.metrics.yoy_revenue_growth}%
              </div>
            )}
          </Card>
        </Col>

        {/* ── 6. Latest Portfolio ──────────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card
            style={{ ...CARD_HOVER, padding: 16, borderLeft: '4px solid #2563EB' }}
            onClick={() => navigate('/portfolio')}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <SafetyCertificateOutlined /> 组合建议
            </Typography.Text>
            {portfolio ? (
              <>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#0F172A', marginTop: 8 }}>
                  {portfolio.strategy}
                </div>
                <Space size={8} style={{ marginTop: 6 }}>
                  <Tag color="blue">目标 {portfolio.expected_annual_return.toFixed(1)}%</Tag>
                  <Tag color="purple">Sharpe {portfolio.expected_sharpe.toFixed(2)}</Tag>
                  <Tag color={portfolio.risk_level === 'moderate' ? 'warning' : 'default'}>
                    {portfolio.risk_level}
                  </Tag>
                </Space>
                <div style={{ fontSize: 12, color: '#64748B', marginTop: 6 }}>
                  持仓: {portfolio.holdings.length} 只
                </div>
              </>
            ) : (
              <div style={{ padding: '12px 0', color: '#94A3B8' }}>暂无组合建议</div>
            )}
          </Card>
        </Col>

        {/* ── 7. Paper/Shadow Status ──────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card
            style={{ ...CARD_HOVER, padding: 16, borderLeft: '4px solid #D97706' }}
            onClick={() => navigate('/paper')}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <ExperimentOutlined /> Paper Trading
            </Typography.Text>
            {paper ? (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 22, fontWeight: 600, color: '#0F172A' }}>
                  {(paper.total_asset / 10000).toFixed(0)}
                  <span style={{ fontSize: 12, fontWeight: 400, color: '#64748B', marginLeft: 4 }}>万</span>
                </div>
                <Space size={12} style={{ marginTop: 4 }}>
                  <span style={{ fontSize: 12, color: '#64748B' }}>
                    现金: {(paper.cash / 10000).toFixed(1)}万
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: paper.unrealized_pnl >= 0 ? '#059669' : '#DC2626',
                    }}
                  >
                    浮盈: {paper.unrealized_pnl >= 0 ? '+' : ''}
                    {(paper.unrealized_pnl / 10000).toFixed(1)}万
                  </span>
                </Space>
              </div>
            ) : (
              <div style={{ padding: '12px 0', color: '#94A3B8' }}>—</div>
            )}
          </Card>
        </Col>

        {/* ── 8. Live Readiness ────────────────────────────────────── */}
        <Col xs={24} sm={12} lg={8} xl={6}>
          <Card
            style={{
              ...CARD_HOVER,
              borderLeft: `4px solid ${live?.overall_status === 'ready' ? '#059669' : '#DC2626'}`,
              padding: 16,
            }}
            onClick={() => navigate('/livegate')}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <FieldNumberOutlined /> Live Readiness
            </Typography.Text>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              <StatusDot
                status={live?.overall_status === 'ready' ? 'running' : 'error'}
                size={14}
              />
              <span
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: live?.overall_status === 'ready' ? '#059669' : '#DC2626',
                }}
              >
                {live?.overall_status === 'ready' ? 'READY' : 'NOT READY'}
              </span>
            </div>
            {live && (
              <>
                <Space size={4} style={{ marginTop: 4 }}>
                  {live.blocking_issues?.length > 0 && (
                    <Tooltip title={live.blocking_issues.join('; ')}>
                      <Tag color="error" style={{ cursor: 'pointer' }}>
                        {live.blocking_issues.length} 阻塞
                      </Tag>
                    </Tooltip>
                  )}
                  {live.warnings?.length > 0 && (
                    <Tag color="warning">{live.warnings.length} 警告</Tag>
                  )}
                  {(!live.blocking_issues || live.blocking_issues.length === 0) &&
                    (!live.warnings || live.warnings.length === 0) && (
                      <Tag color="success">一切正常</Tag>
                    )}
                </Space>
                <div style={{ marginTop: 4, fontSize: 11, color: '#94A3B8' }}>
                  检查时间: {fmtTime(live.checked_at)}
                </div>
              </>
            )}
          </Card>
        </Col>
      </Row>

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* Row 3: Tables (2 columns side by side)                       */}
      {/* ══════════════════════════════════════════════════════════════ */}
      <Row gutter={[16, 16]}>
        {/* ── 9. Recent Tasks ──────────────────────────────────────── */}
        <Col xs={24} lg={12}>
          <Card
            title={
              <span style={{ color: '#0F172A', fontWeight: 600 }}>
                <FileTextOutlined style={{ marginRight: 8 }} />最新任务
              </span>
            }
            extra={
              <span style={{ color: '#94A3B8', fontSize: 12 }}>
                最近 {events.length} 条
              </span>
            }
            style={CARD}
          >
            {loadingTasks ? (
              <Spin style={{ display: 'block', padding: 24 }} />
            ) : events.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center', color: '#94A3B8' }}>暂无任务记录</div>
            ) : (
              <Table
                dataSource={events}
                rowKey={(r) => r.id || r.run_id}
                size="small"
                pagination={false}
                columns={[
                  {
                    title: '任务',
                    dataIndex: 'action',
                    key: 'action',
                    width: 100,
                    ellipsis: true,
                    render: (v) => (
                      <Tooltip title={v}>
                        <span style={{ color: '#2563EB', fontSize: 12 }}>{v}</span>
                      </Tooltip>
                    ),
                  },
                  {
                    title: '状态',
                    dataIndex: 'outcome',
                    key: 'outcome',
                    width: 72,
                    render: (v) => <StatusBadge status={statusToBadge(v)} />,
                  },
                  {
                    title: 'Run ID',
                    dataIndex: 'run_id',
                    key: 'run_id',
                    width: 140,
                    ellipsis: true,
                    render: (v) => (
                      <code style={{ fontSize: 11, color: '#64748B' }}>
                        {v ? v.slice(0, 22) : '—'}
                      </code>
                    ),
                  },
                  {
                    title: '时间',
                    dataIndex: 'created_at',
                    key: 'created_at',
                    width: 130,
                    render: (v) => (
                      <Tooltip title={v}>
                        <span style={{ fontSize: 11, color: '#64748B' }}>{fromNow(v)}</span>
                      </Tooltip>
                    ),
                  },
                ]}
              />
            )}
          </Card>
        </Col>

        {/* ── 10. Latest Risk Alerts ──────────────────────────────── */}
        <Col xs={24} lg={12}>
          <Card
            title={
              <span style={{ color: '#0F172A', fontWeight: 600 }}>
                <BugOutlined style={{ marginRight: 8 }} />最新风险预警
              </span>
            }
            extra={
              riskAlerts.length > 0 ? (
                <span style={{ fontSize: 12 }}>
                  <Tag color="error">{alerts?.total || 0} 条活跃</Tag>
                </span>
              ) : (
                <Tag color="success">无风险</Tag>
              )
            }
            style={CARD}
          >
            {loadingAlerts ? (
              <Spin style={{ display: 'block', padding: 24 }} />
            ) : riskAlerts.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center', color: '#94A3B8' }}>✅ 无风险预警</div>
            ) : (
              <Table
                dataSource={riskAlerts}
                rowKey={(r) => r.id || r.triggered_at}
                size="small"
                pagination={false}
                columns={[
                  {
                    title: '严重程度',
                    dataIndex: 'severity',
                    key: 'severity',
                    width: 80,
                    render: (v) => (
                      <Tag color={v === 'critical' || v === 'high' ? 'error' : v === 'medium' ? 'warning' : 'default'}>
                        {v}
                      </Tag>
                    ),
                  },
                  {
                    title: '规则',
                    dataIndex: 'rule',
                    key: 'rule',
                    width: 120,
                    ellipsis: true,
                    render: (v) => (
                      <Tooltip title={v}>
                        <span style={{ color: '#0F172A', fontSize: 12 }}>{v}</span>
                      </Tooltip>
                    ),
                  },
                  {
                    title: '消息',
                    dataIndex: 'message',
                    key: 'message',
                    ellipsis: true,
                    render: (v) => (
                      <Tooltip title={v}>
                        <span style={{ color: '#64748B', fontSize: 12 }}>{v}</span>
                      </Tooltip>
                    ),
                  },
                  {
                    title: '时间',
                    dataIndex: 'triggered_at',
                    key: 'triggered_at',
                    width: 130,
                    render: (v) => (
                      <Tooltip title={v}>
                        <span style={{ fontSize: 11, color: '#64748B' }}>{fromNow(v)}</span>
                      </Tooltip>
                    ),
                  },
                ]}
                onRow={(record) => ({
                  onClick: () => navigate('/risk'),
                  style: {
                    cursor: 'pointer',
                    background: record.severity === 'critical' || record.severity === 'high' ? '#FFF5F5' : undefined,
                  },
                })}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* ── Footer: Global status bar ─────────────────────────────────── */}
      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col span={24}>
          <Card style={{ ...CARD, borderTop: '3px solid #2563EB' }}>
            <Space size={24} wrap>
              <span style={{ fontSize: 12, color: '#94A3B8' }}>
                <ClockCircleOutlined style={{ marginRight: 4 }} />
                页面刷新: {fmtTime(system?.timestamp)}
              </span>
              <span style={{ fontSize: 12, color: '#94A3B8' }}>
                <DatabaseOutlined style={{ marginRight: 4 }} />
                数据源: Hermes Quant Studio API v5.0
              </span>
              {live?.checked_at && (
                <span style={{ fontSize: 12, color: '#94A3B8' }}>
                  <SafetyCertificateOutlined style={{ marginRight: 4 }} />
                  Live 检查: {fromNow(live.checked_at)}
                </span>
              )}
              {alerts && alerts.total > 0 && (
                <span style={{ fontSize: 12, color: '#DC2626' }}>
                  <WarningOutlined style={{ marginRight: 4 }} />
                  {alerts.total} 条活跃风险预警
                </span>
              )}
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
