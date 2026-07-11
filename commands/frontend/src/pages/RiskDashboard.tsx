import React, { useState, useEffect } from 'react'
import { Card, Row, Col, Table, Tag, Button, Spin, Alert, Typography, Tabs, Space, Statistic, Empty } from 'antd'
import {
  WarningOutlined, CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined,
  ReloadOutlined, PropertySafetyOutlined, BugOutlined, ThunderboltOutlined, HistoryOutlined,
  InfoCircleOutlined, ExclamationCircleOutlined
} from '@ant-design/icons'
import { API } from '../App'
import StatusDot from '../components/common/StatusDot'

const { Title, Text } = Typography

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }
const statCard = (color: string) => ({ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, borderLeft: `4px solid ${color}`, marginBottom: 16 })

interface StatusConfigEntry {
  color: string
  icon: React.ReactNode
  label: string
  dot: string
  bg: string
  text: string
}

interface SeverityConfigEntry {
  color: string
  label: string
  icon: React.ReactNode
}

interface DimensionMeta {
  label: string
  icon: string
}

interface DimensionState {
  status: string
  violations: number
}

interface IncidentSummary {
  n_total?: number
  n_open?: number
  n_acknowledged?: number
  n_resolving?: number
  n_resolved?: number
  n_closed?: number
}

interface OverviewData {
  status?: string
  kill_switch_triggered?: boolean
  kill_switch_state?: string
  n_open_incidents?: number
  n_blockers?: number
  incident_summary?: IncidentSummary
  dimensions?: Record<string, DimensionState>
}

interface AlertItem {
  incident_id: string
  severity: string
  status: string
  rule_name: string
  message: string
  category: string
  triggered_at: string
  resolved_at?: string
  resolution?: string
}

interface AlertsResponse {
  total?: number
  alerts?: AlertItem[]
}

interface KillSwitchData {
  state?: string
  auto_recovery_enabled?: boolean
  n_actions_blocked?: number
  triggered_by_rule?: string
  triggered_at?: string
  blocked_actions?: Array<{
    action_id: string
    action_type: string
    action_name: string
    source: string
    blocked_at: string
    reason: string
  }>
  status?: Record<string, unknown>
}

interface CycleItem {
  cycle_id: string
  status: string
  n_rules: number
  n_violations: number
  n_blockers: number
  kill_switch_triggered: boolean
  completed_at: string
}

interface HistoryData {
  check_cycles?: CycleItem[]
  incidents?: AlertItem[]
}

const STATUS_CONFIG: Record<string, StatusConfigEntry> = {
  healthy:  { color: 'success', icon: <CheckCircleOutlined />, label: '健康',   dot: '#059669', bg: '#D1FAE5', text: '#059669' },
  degraded: { color: 'warning', icon: <ExclamationCircleOutlined />, label: '降级',   dot: '#D97706', bg: '#FEF3C7', text: '#D97706' },
  critical: { color: 'error',   icon: <CloseCircleOutlined />, label: '危急',   dot: '#DC2626', bg: '#FEE2E2', text: '#DC2626' },
  blocked:  { color: 'error',   icon: <CloseCircleOutlined />, label: '阻塞',   dot: '#7C3AED', bg: '#EDE9FE', text: '#7C3AED' },
  unknown:  { color: 'default', icon: <MinusCircleOutlined />, label: '未知',   dot: '#94A3B8', bg: '#F1F5F9', text: '#64748B' },
}

const SEVERITY_CONFIG: Record<string, SeverityConfigEntry> = {
  blocker:  { color: 'error',   label: '阻塞',   icon: <CloseCircleOutlined /> },
  critical: { color: 'warning', label: '危急',   icon: <WarningOutlined /> },
  warning:  { color: 'gold',    label: '警告',   icon: <ExclamationCircleOutlined /> },
  info:     { color: 'default', label: '信息',   icon: <InfoCircleOutlined /> },
}

const DIMENSION_LABELS: Record<string, DimensionMeta> = {
  data:      { label: '数据',      icon: '📊' },
  account:   { label: '账户',      icon: '💰' },
  execution: { label: '执行',      icon: '⚡' },
  loss:      { label: '亏损',      icon: '📉' },
  system:    { label: '系统',      icon: '🔧' },
}

const DOT_MAP: Record<string, 'running' | 'idle' | 'error' | 'warning'> = {
  healthy: 'running',
  degraded: 'warning',
  critical: 'error',
  blocked: 'error',
  unknown: 'idle',
}

const INCIDENT_DOT: Record<string, 'running' | 'idle' | 'error' | 'warning'> = {
  open: 'running',
  acknowledged: 'warning',
  resolving: 'warning',
  resolved: 'idle',
  closed: 'idle',
}

export default function RiskDashboard() {
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [alerts, setAlerts] = useState<AlertsResponse>({})
  const [killSwitch, setKillSwitch] = useState<KillSwitchData | null>(null)
  const [history, setHistory] = useState<HistoryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('overview')

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [ov, al, ks, hi] = await Promise.all([
        fetch(`${API}/api/risk/overview`).then(r => r.json() as Promise<OverviewData>),
        fetch(`${API}/api/risk/alerts?limit=100`).then(r => r.json() as Promise<AlertsResponse>),
        fetch(`${API}/api/risk/kill-switch`).then(r => r.json() as Promise<KillSwitchData>),
        fetch(`${API}/api/risk/history?cycles=20&incidents_limit=50`).then(r => r.json() as Promise<HistoryData>),
      ])
      setOverview(ov)
      setAlerts(al)
      setKillSwitch(ks)
      setHistory(hi)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载风险仪表盘失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t) }, [])

  // ── Loading / Error ──
  if (loading && !overview) {
    return <Spin style={{ display: 'block', marginTop: 80 }} />
  }

  if (error && !overview) {
    return <Alert message="加载失败" description={error} type="error" showIcon style={{ margin: 24 }} />
  }

  const statusCfg = STATUS_CONFIG[overview?.status || ''] || STATUS_CONFIG.unknown

  const getDot = (v?: string): 'running' | 'idle' | 'error' | 'warning' =>
    DOT_MAP[v || ''] || 'idle'

  // ── Alert columns ──
  const alertCols = [
    {
      title: '严重程度', dataIndex: 'severity', key: 'severity', width: 80,
      render: (v: string) => {
        const cfg = SEVERITY_CONFIG[v] || SEVERITY_CONFIG.info
        return <Tag color={cfg.color} style={{ border: 'none', borderRadius: 12, fontSize: 11 }}>{cfg.label}</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => {
        const colorMap: Record<string, string> = { open: 'error', acknowledged: 'processing', resolved: 'success', closed: 'default', resolving: 'warning' }
        return <span><StatusDot status={INCIDENT_DOT[v] || 'idle'} size={7} /> <Tag color={colorMap[v] || 'default'}>{v}</Tag></span>
      },
    },
    { title: '规则', dataIndex: 'rule_name', key: 'rule_name', width: 140, ellipsis: true },
    { title: '消息', dataIndex: 'message', key: 'message', ellipsis: true },
    { title: '分类', dataIndex: 'category', key: 'category', width: 70,
      render: (v: string) => {
        const dim = DIMENSION_LABELS[v]
        return dim ? <Tag color="geekblue">{dim.icon} {dim.label}</Tag> : <Tag>{v}</Tag>
      },
    },
    { title: '触发时间', dataIndex: 'triggered_at', key: 'triggered_at', width: 170,
      render: (v: string) => {
        if (!v) return '-'
        return <Text style={{ fontSize: 12, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text>
      },
    },
  ]

  // ── Check cycle columns ──
  const cycleCols = [
    { title: '周期 ID', dataIndex: 'cycle_id', key: 'cycle_id', width: 160,
      render: (v: string) => <code style={{ color: '#2563EB', fontSize: 11 }}>{v}</code> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => {
        const cfg = STATUS_CONFIG[v] || STATUS_CONFIG.unknown
        return <span><StatusDot status={getDot(v)} size={7} /> <Tag color={cfg.color}>{cfg.label}</Tag></span>
      },
    },
    { title: '规则数', dataIndex: 'n_rules', key: 'n_rules', width: 60, align: 'right' as const },
    { title: '违规', dataIndex: 'n_violations', key: 'n_violations', width: 60, align: 'right' as const,
      render: (v: number) => v > 0 ? <span style={{ color: '#D97706', fontWeight: 600 }}>{v}</span> : v },
    { title: '阻塞', dataIndex: 'n_blockers', key: 'n_blockers', width: 60, align: 'right' as const,
      render: (v: number) => v > 0 ? <span style={{ color: '#DC2626', fontWeight: 600 }}>{v}</span> : v },
    { title: '触发 KS', dataIndex: 'kill_switch_triggered', key: 'ks', width: 70, align: 'center' as const,
      render: (v: boolean) => v ? <Tag color="error">是</Tag> : <Tag>否</Tag> },
    { title: '完成时间', dataIndex: 'completed_at', key: 'completed_at', width: 170,
      render: (v: string) => {
        if (!v) return '-'
        return <Text style={{ fontSize: 12, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text>
      },
    },
  ]

  // ── Tab items ──
  const tabItems = [
    {
      key: 'overview',
      label: <span><PropertySafetyOutlined /> 概览</span>,
      children: renderOverview(),
    },
    {
      key: 'alerts',
      label: <span><BugOutlined /> 告警 ({alerts?.total ?? 0})</span>,
      children: renderAlerts(),
    },
    {
      key: 'kill-switch',
      label: <span><ThunderboltOutlined /> Kill Switch</span>,
      children: renderKillSwitch(),
    },
    {
      key: 'history',
      label: <span><HistoryOutlined /> 历史</span>,
      children: renderHistory(),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0, color: '#0F172A' }}>
          <PropertySafetyOutlined style={{ marginRight: 8, color: '#2563EB' }} />
          风险仪表盘
        </Title>
        <Space>
          <Tag color={statusCfg.color} style={{ padding: '2px 12px', borderRadius: 12, fontSize: 13 }}>
            {statusCfg.icon} {statusCfg.label}
          </Tag>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        </Space>
      </div>

      {error && <Alert message={error} type="error" showIcon closable style={{ marginBottom: 16 }} />}

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </div>
  )

  // ── Overview tab ──
  function renderOverview() {
    const o = overview || {} as OverviewData
    const incSummary = o.incident_summary || {}

    return (
      <div>
        {/* Stat cards row */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard('#2563EB')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>整体状态</Text>}
                value={statusCfg.label}
                prefix={<span><StatusDot status={getDot(overview?.status)} size={10} /> {statusCfg.icon}</span>}
                valueStyle={{ color: statusCfg.dot, fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard(o.kill_switch_triggered ? '#DC2626' : '#059669')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>Kill Switch</Text>}
                value={o.kill_switch_state || 'armed'}
                prefix={<ThunderboltOutlined />}
                valueStyle={{ color: o.kill_switch_triggered ? '#DC2626' : '#059669', fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard(o.n_open_incidents && o.n_open_incidents > 0 ? '#D97706' : '#059669')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>未关闭告警</Text>}
                value={o.n_open_incidents ?? 0}
                prefix={<BugOutlined />}
                valueStyle={{ color: o.n_open_incidents && o.n_open_incidents > 0 ? '#D97706' : '#059669', fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card style={statCard(o.n_blockers && o.n_blockers > 0 ? '#DC2626' : '#059669')} styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title={<Text style={{ fontSize: 12, color: '#64748B', fontWeight: 500 }}>阻塞项</Text>}
                value={o.n_blockers ?? 0}
                prefix={<CloseCircleOutlined />}
                valueStyle={{ color: o.n_blockers && o.n_blockers > 0 ? '#DC2626' : '#059669', fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Col>
        </Row>

        {/* Dimension breakdown */}
        <Title level={5} style={{ marginTop: 24, marginBottom: 12, color: '#0F172A' }}>维度状态</Title>
        <Row gutter={[16, 16]}>
          {Object.entries(DIMENSION_LABELS).map(([key, meta]) => {
            const dim = o.dimensions?.[key] || { status: 'unknown', violations: 0 }
            const cfg = STATUS_CONFIG[dim.status] || STATUS_CONFIG.unknown
            return (
              <Col xs={24} sm={12} lg={4} key={key}>
                <Card
                  hoverable
                  style={{
                    ...cardStyle,
                    borderLeft: `4px solid ${cfg.dot}`,
                    cursor: 'default',
                  }}
                  styles={{ body: { padding: '16px 20px', textAlign: 'center' } }}
                >
                  <div style={{ fontSize: 28, marginBottom: 8 }}>{meta.icon}</div>
                  <Text style={{ fontSize: 12, color: '#64748B', display: 'block', marginBottom: 4 }}>{meta.label}</Text>
                  <Tag color={cfg.color} style={{ border: 'none', borderRadius: 12, fontSize: 12 }}>
                    <StatusDot status={DOT_MAP[dim.status] || 'idle'} size={7} /> {cfg.label}
                  </Tag>
                  {dim.violations > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <Text style={{ fontSize: 12, color: '#DC2626', fontWeight: 600 }}>
                        {dim.violations} 项违规
                      </Text>
                    </div>
                  )}
                </Card>
              </Col>
            )
          })}
        </Row>

        {/* Incident summary */}
        <Title level={5} style={{ marginTop: 24, marginBottom: 12, color: '#0F172A' }}>事件统计</Title>
        <Row gutter={[16, 16]}>
          {[
            { label: '全部事件', value: incSummary.n_total ?? 0, color: '#2563EB' },
            { label: '待处理', value: incSummary.n_open ?? 0, color: '#DC2626' },
            { label: '已确认', value: incSummary.n_acknowledged ?? 0, color: '#D97706' },
            { label: '处理中', value: incSummary.n_resolving ?? 0, color: '#D97706' },
            { label: '已解决', value: incSummary.n_resolved ?? 0, color: '#059669' },
            { label: '已关闭', value: incSummary.n_closed ?? 0, color: '#94A3B8' },
          ].map(s => (
            <Col xs={12} sm={8} lg={4} key={s.label}>
              <Card style={statCard(s.color)} styles={{ body: { padding: '12px 16px' } }}>
                <Statistic
                  title={<Text style={{ fontSize: 11, color: '#64748B' }}>{s.label}</Text>}
                  value={s.value}
                  valueStyle={{ color: s.color, fontSize: 18, fontWeight: 700 }}
                />
              </Card>
            </Col>
          ))}
        </Row>
      </div>
    )
  }

  // ── Alerts tab ──
  function renderAlerts() {
    const alertList = alerts?.alerts || []
    if (!alertList.length) {
      return (
        <Card style={cardStyle}>
          <Empty description="暂无告警" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </Card>
      )
    }

    return (
      <Card
        style={cardStyle}
        title={
          <Space>
            <BugOutlined style={{ color: '#2563EB' }} />
            <span>活跃告警</span>
            <Tag>{alerts?.total ?? 0} 条</Tag>
          </Space>
        }
      >
        <Table
          dataSource={alertList}
          columns={alertCols}
          rowKey="incident_id"
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      </Card>
    )
  }

  // ── Kill Switch tab ──
  function renderKillSwitch() {
    const ks = killSwitch || {} as KillSwitchData
    const blocked = ks.blocked_actions || []

    return (
      <div>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card style={cardStyle} title={<span><ThunderboltOutlined style={{ color: '#2563EB' }} /> Kill Switch 状态</span>}>
              <Row gutter={[16, 16]}>
                <Col span={12}>
                  <Statistic
                    title="当前状态"
                    value={ks.state || 'armed'}
                    valueStyle={{
                      color: ks.state === 'triggered' ? '#DC2626'
                        : ks.state === 'disabled' ? '#64748B'
                        : '#059669',
                      fontWeight: 700,
                    }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="自动恢复"
                    value={ks.auto_recovery_enabled ? '已启用' : '已禁用'}
                    valueStyle={{ color: ks.auto_recovery_enabled ? '#059669' : '#D97706', fontWeight: 600 }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="被拦操作数"
                    value={ks.n_actions_blocked ?? 0}
                    valueStyle={{ color: (ks.n_actions_blocked ?? 0) > 0 ? '#DC2626' : '#059669', fontWeight: 700 }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="触发规则"
                    value={ks.triggered_by_rule || '-'}
                    valueStyle={{ fontSize: 14, fontWeight: 500 }}
                  />
                </Col>
              </Row>
              {ks.triggered_at && (
                <div style={{ marginTop: 12 }}>
                  <Text style={{ fontSize: 12, color: '#64748B' }}>
                    触发时间: {new Date(ks.triggered_at).toLocaleString('zh-CN')}
                  </Text>
                </div>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card style={cardStyle} title={<span><CloseCircleOutlined style={{ color: '#DC2626' }} /> 被拦操作</span>}>
              {blocked.length === 0 ? (
                <Empty description="无被拦操作" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <Table
                  dataSource={blocked.slice(-10).reverse()}
                  columns={[
                    { title: '类型', dataIndex: 'action_type', width: 80 },
                    { title: '名称', dataIndex: 'action_name', ellipsis: true },
                    { title: '来源', dataIndex: 'source', width: 80 },
                    { title: '时间', dataIndex: 'blocked_at', width: 170,
                      render: (v: string) => v ? <Text style={{ fontSize: 11, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text> : '-',
                    },
                    { title: '原因', dataIndex: 'reason', ellipsis: true },
                  ]}
                  rowKey="action_id"
                  size="small"
                  pagination={blocked.length > 10 ? { pageSize: 10 } : false}
                />
              )}
            </Card>
          </Col>
        </Row>
      </div>
    )
  }

  // ── History tab ──
  function renderHistory() {
    const checkCycles = history?.check_cycles || []
    const incidents = history?.incidents || []

    return (
      <div>
        <Card
          style={cardStyle}
          title={<span><HistoryOutlined style={{ color: '#2563EB' }} /> 检查周期历史</span>}
        >
          {checkCycles.length === 0 ? (
            <Empty description="暂无检查记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table
              dataSource={checkCycles}
              columns={cycleCols}
              rowKey="cycle_id"
              size="small"
              pagination={{ pageSize: 10, showSizeChanger: false }}
            />
          )}
        </Card>

        <Card
          style={{ ...cardStyle, marginTop: 16 }}
          title={<span><BugOutlined style={{ color: '#2563EB' }} /> 事件历史</span>}
        >
          {incidents.length === 0 ? (
            <Empty description="暂无事件记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table
              dataSource={incidents}
              columns={[
                ...alertCols,
                { title: '解决时间', dataIndex: 'resolved_at', key: 'resolved_at', width: 170,
                  render: (v: string) => v ? <Text style={{ fontSize: 12, color: '#64748B' }}>{new Date(v).toLocaleString('zh-CN')}</Text> : '-',
                },
                { title: '解决说明', dataIndex: 'resolution', key: 'resolution', width: 150, ellipsis: true },
              ]}
              rowKey="incident_id"
              size="small"
              pagination={{ pageSize: 15, showSizeChanger: false }}
            />
          )}
        </Card>
      </div>
    )
  }
}
