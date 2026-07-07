import { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Table, Tag, Button, message, Modal, Descriptions, Spin, Progress, Typography, Tooltip, Alert } from 'antd'
import { ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined, RightCircleOutlined, PieChartOutlined, WarningOutlined, HistoryOutlined } from '@ant-design/icons'
import { API } from '../App'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }
const statCardBase = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }

const SERIES_COLORS = {
  'V3 Alpha Factory': '#3B82F6',
  'V4 Controlled Execution': '#8B5CF6',
  'V5 Data Platform': '#059669',
  'V6 Research Automation': '#D97706',
  'V7 Product UI/Ops': '#0891B2',
  'V8 Multi-Agent Engineering': '#DC2626',
  'V9 Future Backlog': '#94A3B8',
}

const STATUS_TAG = {
  completed: { color: 'success', icon: <CheckCircleOutlined />, label: '完成' },
  current: { color: 'processing', icon: <RightCircleOutlined />, label: '进行中' },
  failed: { color: 'error', icon: <CloseCircleOutlined />, label: '失败' },
  pending: { color: 'default', icon: <MinusCircleOutlined />, label: '待办' },
}

export default function Roadmap() {
  const [data, setData] = useState(null)
  const [progress, setProgress] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    setError(null)
    try {
      const r = await fetch(`${API}/api/roadmap/versions`, { cache: 'no-store' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setData(d.versions || [])
      setProgress(d.progress || null)
    } catch (e) {
      setError(e.message || '加载路线图失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(() => load(true), 30000); return () => clearInterval(t) }, [load])

  const mark = async (version, status) => {
    await fetch(`${API}/api/roadmap/versions/mark`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version, status })
    })
    message.success(`${version} → ${status}`)
    load(true)
  }

  if (loading && !data) return <Spin style={{ display: 'block', marginTop: 80 }} />

  // ── Series progress ──
  const seriesList = progress?.series || []
  const bySeries = {}
  for (const v of (data || [])) {
    const s = v.series || 'Other'
    if (!bySeries[s]) bySeries[s] = []
    bySeries[s].push(v)
  }

  // ── Column defs ──
  const cols = [
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v) => {
        const cfg = STATUS_TAG[v] || STATUS_TAG.pending
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
      },
    },
    { title: '版本', dataIndex: 'version', key: 'version', width: 80, render: v => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
    { title: '目标', dataIndex: 'objective', key: 'objective', ellipsis: true },
    { title: '系列', dataIndex: 'series', key: 'series', width: 160, render: v => <Tag color="geekblue">{v?.replace(/^V\d\s/, '')}</Tag> },
    {
      title: '自动', dataIndex: 'auto_allowed', key: 'auto', width: 50,
      render: v => v ? <CheckCircleOutlined style={{ color: '#059669' }} /> : <CloseCircleOutlined style={{ color: '#94A3B8' }} />,
    },
    {
      title: '交易模式', dataIndex: 'trading_mode', key: 'trading_mode', width: 100,
      render: v => v && v !== 'none' ? <Tag color="purple">{v}</Tag> : <span style={{ color: '#94A3B8' }}>-</span>,
    },
    {
      title: '操作', key: 'action', width: 160,
      render: (_, r) => {
        if (r.backlog) return <span style={{ color: '#94A3B8', fontSize: 12 }}>Backlog</span>
        return <span>
          {r.status !== 'completed' && <Button size="small" onClick={(e) => { e.stopPropagation(); mark(r.version, 'completed') }} style={{ marginRight: 4 }}>完成</Button>}
          {r.status !== 'failed' && <Button size="small" danger onClick={(e) => { e.stopPropagation(); mark(r.version, 'failed') }}>失败</Button>}
        </span>
      },
    },
  ]

  const renderSummaryCards = () => {
    const p = progress || {}
    return <Row gutter={16} style={{ marginBottom: 8 }}>
      <Col span={4}>
        <Card style={{ ...statCardBase, borderLeft: '4px solid #3B82F6' }}>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>📋 总版本</Typography.Text>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#0F172A' }}>{p.total_versions ?? '-'}</div>
        </Card>
      </Col>
      <Col span={4}>
        <Card style={{ ...statCardBase, borderLeft: '4px solid #059669' }}>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>✅ 已完成</Typography.Text>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#059669' }}>{p.completed ?? '-'}</div>
        </Card>
      </Col>
      <Col span={4}>
        <Card style={{ ...statCardBase, borderLeft: '4px solid #3B82F6' }}>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>▶ 进行中</Typography.Text>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#3B82F6' }}>{p.current ?? '-'}</div>
        </Card>
      </Col>
      <Col span={4}>
        <Card style={{ ...statCardBase, borderLeft: p.failed > 0 ? '4px solid #DC2626' : '4px solid #E2E8F0' }}>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>❌ 失败</Typography.Text>
          <div style={{ fontSize: 28, fontWeight: 700, color: p.failed > 0 ? '#DC2626' : '#94A3B8' }}>{p.failed ?? '-'}</div>
        </Card>
      </Col>
      <Col span={4}>
        <Card style={{ ...statCardBase, borderLeft: '4px solid #94A3B8' }}>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>⏳ 待办</Typography.Text>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#0F172A' }}>{p.pending ?? '-'}</div>
        </Card>
      </Col>
      <Col span={4}>
        <Card style={{ ...statCardBase, borderLeft: '4px solid #D97706' }}>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>📊 进度</Typography.Text>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#D97706' }}>{p.percent ?? 0}%</div>
        </Card>
      </Col>
    </Row>
  }

  const renderOverallProgress = () => {
    const p = progress || {}
    const activeTotal = (p.total_versions || 0) - (p.backlog || 0)
    return <Card style={{ ...cardStyle, marginBottom: 12 }}>
      <Row align="middle" gutter={16}>
        <Col span={16}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <Typography.Text strong style={{ color: '#0F172A', fontSize: 14 }}>总体路线图进度</Typography.Text>
            <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>
              {p.completed ?? 0} / {activeTotal} 激活版本 ({p.backlog ?? 0} backlog 未计)
            </Typography.Text>
          </div>
          <Progress
            percent={Number(p.percent) || 0}
            strokeColor={{
              '0%': '#3B82F6',
              '100%': '#059669',
            }}
            trailColor="#E2E8F0"
            size="default"
            format={(pct) => `${pct}%`}
          />
        </Col>
        <Col span={4} style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: '#059669' }}>{p.completed ?? 0}</div>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>已完成</Typography.Text>
        </Col>
        <Col span={4} style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: '#3B82F6' }}>{p.current ?? 0}</div>
          <Typography.Text style={{ color: '#64748B', fontSize: 12 }}>进行中</Typography.Text>
        </Col>
      </Row>
    </Card>
  }

  const renderSeriesProgress = () => {
    if (!seriesList.length) return null
    return <Row gutter={16} style={{ marginBottom: 12 }}>
      {seriesList.map(s => {
        const color = SERIES_COLORS[s.key] || '#64748B'
        return <Col span={8} key={s.key} style={{ marginBottom: 8 }}>
          <Card size="small" style={{ ...statCardBase, height: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Tooltip title={s.key}>
                <Typography.Text strong style={{ color: '#0F172A', fontSize: 12 }} ellipsis>
                  <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, backgroundColor: color, marginRight: 6 }} />
                  {s.key.replace(/^V\d\s/, '')}
                </Typography.Text>
              </Tooltip>
              <Typography.Text style={{ color: '#64748B', fontSize: 11 }}>
                {s.completed}/{s.total}
              </Typography.Text>
            </div>
            <Progress
              percent={Number(s.percent) || 0}
              strokeColor={color}
              trailColor="#E2E8F0"
              size="small"
              format={() => `${s.percent}%`}
              style={{ marginBottom: 0 }}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 6, fontSize: 11, color: '#94A3B8' }}>
              {s.failed > 0 && <span>❌ {s.failed}</span>}
              {s.current > 0 && <span>▶ {s.current}</span>}
              {s.pending > 0 && <span>⏳ {s.pending}</span>}
            </div>
          </Card>
        </Col>
      })}
    </Row>
  }

  return <div>
    {/* ── Header ── */}
    <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
      <Col>
        <Typography.Title level={4} style={{ margin: 0, color: '#0F172A' }}>
          <PieChartOutlined style={{ marginRight: 8 }} />🗺️ 路线图进度
        </Typography.Title>
      </Col>
      <Col>
        <Button icon={<ReloadOutlined />} onClick={() => load(true)} loading={refreshing}>
          刷新
        </Button>
      </Col>
    </Row>

    {error && <Alert message={error} type="error" showIcon style={{ marginBottom: 16, borderRadius: 8 }} closable />}

    {/* ── Summary Stats ── */}
    {renderSummaryCards()}

    {/* ── Overall Progress Bar ── */}
    {renderOverallProgress()}

    {/* ── Per-Series Progress -─ */}
    {renderSeriesProgress()}

    {/* ── Legend ── */}
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}>📋 版本清单</span>}
      extra={
        <span style={{ color: '#94A3B8', fontSize: 12 }}>
          当前版本: {progress?.current ? (data?.find(v => v.status === 'current')?.version || '-') : '-'} •
          点击版本行查看详情 • 自动刷新 30s
        </span>
      }
      style={cardStyle}>
      {/* Legend */}
      <div style={{ marginBottom: 12, display: 'flex', gap: 16, fontSize: 12, color: '#64748B', flexWrap: 'wrap' }}>
        {Object.entries(SERIES_COLORS).map(([name, color]) => (
          <span key={name}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, backgroundColor: color, marginRight: 4, verticalAlign: 'middle' }} />
            {name.replace(/^V\d\s/, '')}
          </span>
        ))}
      </div>

      <Table
        dataSource={data || []}
        columns={cols}
        rowKey="version"
        size="small"
        pagination={{ pageSize: 15 }}
        onRow={v => ({
          onClick: () => setDetail(v),
          style: {
            cursor: 'pointer',
            background: v.status === 'current' ? '#EFF6FF' : undefined,
          },
        })}
        locale={{ emptyText: <EmptyState /> }}
      />
    </Card>

    {/* ── Detail Modal ── */}
    <Modal open={!!detail} onCancel={() => setDetail(null)} footer={null} width={600}
      title={<span style={{ color: '#0F172A', fontWeight: 600 }}>
        <code style={{ color: '#2563EB', fontSize: 14 }}>{detail?.version}</code> — {detail?.name}
      </span>}>
      {detail && <div>
        <Descriptions column={2} size="small" bordered
          styles={{ label: { background: '#F8FAFC', color: '#64748B' }, content: { color: '#0F172A' } }}>
          <Descriptions.Item label="版本"><code style={{ color: '#2563EB' }}>{detail.version}</code></Descriptions.Item>
          <Descriptions.Item label="状态">
            {(() => {
              const cfg = STATUS_TAG[detail.status] || STATUS_TAG.pending
              return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
            })()}
          </Descriptions.Item>
          <Descriptions.Item label="名称" span={2}>{detail.name}</Descriptions.Item>
          <Descriptions.Item label="目标" span={2}>{detail.objective}</Descriptions.Item>
          <Descriptions.Item label="系列">{detail.series}</Descriptions.Item>
          <Descriptions.Item label="Backlog">{detail.backlog ? '✅' : '❌'}</Descriptions.Item>
          <Descriptions.Item label="自动允许">{detail.auto_allowed ? '✅' : '❌'}</Descriptions.Item>
          <Descriptions.Item label="人工门禁">{detail.manual_required ? '✅' : '❌'}</Descriptions.Item>
          <Descriptions.Item label="交易模式">{detail.trading_mode || 'none'}</Descriptions.Item>
        </Descriptions>

        {/* Progress in this series */}
        {seriesList.map(s => {
          if (!detail.series?.includes(s.key)) return null
          return <div key={s.key} style={{ marginTop: 16 }}>
            <Typography.Text strong style={{ color: '#0F172A', fontSize: 13 }}>{s.name} 进度</Typography.Text>
            <Progress
              percent={Number(s.percent) || 0}
              strokeColor={SERIES_COLORS[s.key]}
              trailColor="#E2E8F0"
              size="small"
              format={() => `${s.completed}/${s.total} (${s.percent}%)`}
              style={{ marginTop: 8 }}
            />
          </div>
        })}
      </div>}
    </Modal>
  </div>
}

function EmptyState() {
  return <div style={{ textAlign: 'center', padding: 32, color: '#94A3B8' }}>
    <HistoryOutlined style={{ fontSize: 32, display: 'block', marginBottom: 8 }} />
    <span>暂无路线图数据</span>
  </div>
}
