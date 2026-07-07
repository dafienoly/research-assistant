import { useState, useEffect } from 'react'
import { Card, Row, Col, Table, Tag, Badge, Button, Spin, Progress, Alert, Typography, Collapse, Tooltip } from 'antd'
import { ReloadOutlined, WarningOutlined, CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined, BugOutlined, DatabaseOutlined, FileTextOutlined } from '@ant-design/icons'
import { API } from '../App'

const cardStyle = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, marginBottom: 16 }
const statCard = (color) => ({ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 10, borderLeft: `4px solid ${color}`, marginBottom: 16 })

const STATUS_CONFIG = {
  active: { color: 'success', icon: <CheckCircleOutlined />, label: '健康', dot: '#059669' },
  degraded: { color: 'warning', icon: <WarningOutlined />, label: '降级', dot: '#D97706' },
  inactive: { color: 'error', icon: <CloseCircleOutlined />, label: '失败', dot: '#DC2626' },
  unchecked: { color: 'default', icon: <MinusCircleOutlined />, label: '待检', dot: '#94A3B8' },
}

const FRESHNESS_CONFIG = {
  ok: { color: 'success', icon: <CheckCircleOutlined />, label: '正常' },
  stale: { color: 'warning', icon: <WarningOutlined />, label: '过期' },
  missing: { color: 'error', icon: <CloseCircleOutlined />, label: '缺失' },
}

export default function DataStatus() {
  const [overview, setOverview] = useState(null)
  const [providers, setProviders] = useState(null)
  const [freshness, setFreshness] = useState(null)
  const [gaps, setGaps] = useState(null)
  const [fetchLog, setFetchLog] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedRow, setExpandedRow] = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [ov, pr, fr, ga, fl] = await Promise.all([
        fetch(`${API}/api/data/overview`).then(r => r.json()),
        fetch(`${API}/api/data/providers`).then(r => r.json()),
        fetch(`${API}/api/data/freshness`).then(r => r.json()),
        fetch(`${API}/api/data/gaps`).then(r => r.json()),
        fetch(`${API}/api/data/fetch-log?limit=100`).then(r => r.json()),
      ])
      setOverview(ov)
      setProviders(pr)
      setFreshness(fr)
      setGaps(ga)
      setFetchLog(fl)
    } catch (e) {
      setError(e.message || '加载数据状态失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t) }, [])

  if (loading && !overview) return <Spin style={{ display: 'block', marginTop: 80 }} />

  const summary = overview?.summary || {}
  const blockingIssues = summary.blocking_issues || 0

  // ── Provider columns ──
  const providerCols = [
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 70,
      render: (v) => {
        const cfg = STATUS_CONFIG[v] || STATUS_CONFIG.unchecked
        return <Tooltip title={cfg.label}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', backgroundColor: cfg.dot }} /></Tooltip>
      },
    },
    { title: '数据源', dataIndex: 'source_id', key: 'source_id', width: 140, render: v => <code style={{ color: '#2563EB', fontSize: 12 }}>{v}</code> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 180, ellipsis: true },
    { title: '分类', dataIndex: 'category', key: 'category', width: 80, render: v => <Tag color="geekblue">{v}</Tag> },
    {
      title: '状态', dataIndex: 'status', key: 'status_label', width: 60,
      render: (v) => {
        const cfg = STATUS_CONFIG[v] || STATUS_CONFIG.unchecked
        return <Tag color={cfg.color}>{cfg.label}</Tag>
      },
    },
    {
      title: '成功率', dataIndex: ['health', 'success_rate'], key: 'success_rate', width: 160,
      render: (v, record) => {
        const rate = v ?? 100
        const color = rate >= 80 ? '#059669' : rate >= 50 ? '#D97706' : '#DC2626'
        return <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Progress percent={Math.round(rate)} size="small" strokeColor={color} style={{ flex: 1, marginBottom: 0 }} />
          <span style={{ fontSize: 12, color, fontWeight: 600, minWidth: 40 }}>{rate}%</span>
        </div>
      },
    },
    {
      title: '延迟', dataIndex: ['health', 'avg_latency_ms'], key: 'latency', width: 70,
      render: v => v ? <span style={{ color: '#64748B', fontSize: 12 }}>{v.toFixed(0)}ms</span> : <span style={{ color: '#94A3B8' }}>-</span>,
    },
    {
      title: '调用', dataIndex: ['health', 'total_calls'], key: 'calls', width: 60,
      render: v => <span style={{ color: '#64748B', fontSize: 12 }}>{v ?? 0}</span>,
    },
    {
      title: '最近检查', dataIndex: ['health', 'last_check'], key: 'last_check', width: 160,
      render: v => v ? <span style={{ color: '#64748B', fontSize: 12 }}>{v.slice(0, 19)}</span> : <span style={{ color: '#94A3B8' }}>-</span>,
    },
  ]

  // ── Freshness columns ──
  const freshCols = [
    { title: '文件', dataIndex: 'path', key: 'path', render: v => <code style={{ color: '#0F172A', fontSize: 12 }}>{v}</code> },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => {
        const cfg = FRESHNESS_CONFIG[v] || { color: 'default', label: v, icon: null }
        return <Tag color={cfg.color}>{cfg.label}</Tag>
      },
    },
    {
      title: '延迟', dataIndex: 'actual_age_seconds', key: 'age', width: 100,
      render: (v, record) => {
        if (!v && v !== 0) return <span style={{ color: '#94A3B8' }}>-</span>
        const maxAge = record.max_age_seconds || 1
        const pct = Math.min(100, Math.round((v / maxAge) * 100))
        const color = pct >= 100 ? '#DC2626' : pct >= 80 ? '#D97706' : '#059669'
        return <div>
          <Progress percent={pct} size="small" strokeColor={color} format={() => `${Math.floor(v / 60)}m${Math.floor(v % 60)}s`} style={{ marginBottom: 0 }} />
        </div>
      },
    },
    { title: '阈值', dataIndex: 'max_age_seconds', key: 'max', width: 80, render: v => v ? <span style={{ color: '#64748B', fontSize: 12 }}>{Math.floor(v / 60)}m</span> : <span style={{ color: '#94A3B8' }}>-</span> },
    { title: '备注', dataIndex: 'note', key: 'note', ellipsis: true, render: v => v ? <span style={{ color: '#64748B', fontSize: 12 }}>{v}</span> : null },
  ]

  // ── Gap columns ──
  const gapsArr = gaps?.gaps || []
  const gapCols = [
    { title: '分类', dataIndex: 'category', key: 'category', width: 80, render: v => <Tag color="geekblue">{v}</Tag> },
    { title: '类型', dataIndex: 'gap_type', key: 'gap_type', width: 100 },
    {
      title: '影响', dataIndex: 'impact', key: 'impact', width: 80,
      render: v => {
        const cfg = { blocking: { color: 'error', label: '阻塞' }, partial: { color: 'warning', label: '部分' }, minor: { color: 'default', label: '轻微' } }
        const c = cfg[v] || { color: 'default', label: v }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
    { title: '失败原因', dataIndex: 'failure_reason', key: 'failure_reason', ellipsis: true },
    { title: '建议', dataIndex: 'recommendation', key: 'recommendation', ellipsis: true, render: v => <span style={{ color: '#64748B', fontSize: 12 }}>{v}</span> },
  ]

  // ── Fetch log columns ──
  const logEntries = fetchLog?.entries || []
  const logCols = [
    { title: '时间', dataIndex: 'timestamp', key: 'ts', width: 160, render: v => <span style={{ color: '#64748B', fontSize: 12 }}>{v}</span> },
    { title: '操作', dataIndex: 'action', key: 'action', width: 120 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => {
        const cfg = { ok: { color: 'success', label: '成功' }, error: { color: 'error', label: '失败' }, stale: { color: 'warning', label: '过期' } }
        const c = cfg[v] || { color: 'default', label: v }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
    { title: '错误信息', dataIndex: 'error', key: 'error', ellipsis: true, render: v => v ? <span style={{ color: '#DC2626', fontSize: 12 }}>{v}</span> : null },
    { title: '耗时', dataIndex: 'duration_ms', key: 'dur', width: 70, render: v => v ? <span style={{ color: '#64748B', fontSize: 12 }}>{v}ms</span> : null },
  ]

  return <div>
    <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
      <Col><Typography.Title level={4} style={{ margin: 0, color: '#0F172A' }}>📡 数据状态</Typography.Title></Col>
      <Col><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button></Col>
    </Row>

    {error && <Alert message={error} type="error" showIcon style={{ marginBottom: 16, borderRadius: 8 }} closable />}

    {blockingIssues > 0 && (
      <Alert
        message={`存在 ${blockingIssues} 个阻塞性数据问题，请尽快处理`}
        type="error" showIcon icon={<WarningOutlined />}
        style={{ marginBottom: 16, borderRadius: 8 }}
      />
    )}

    {/* ─── Summary Cards ─── */}
    <Row gutter={16} style={{ marginBottom: 8 }}>
      <Col span={4}><Card style={statCard('#2563EB')}><span style={{ color: '#64748B', fontSize: 12 }}>📦 数据源</span><div style={{ fontSize: 28, fontWeight: 700, color: '#0F172A' }}>{summary.total_sources ?? '-'}</div></Card></Col>
      <Col span={4}><Card style={statCard('#059669')}><span style={{ color: '#64748B', fontSize: 12 }}>✅ 健康</span><div style={{ fontSize: 28, fontWeight: 700, color: '#059669' }}>{summary.active ?? '-'}</div></Card></Col>
      <Col span={4}><Card style={statCard('#D97706')}><span style={{ color: '#64748B', fontSize: 12 }}>⚠️ 降级</span><div style={{ fontSize: 28, fontWeight: 700, color: '#D97706' }}>{summary.degraded ?? '-'}</div></Card></Col>
      <Col span={4}><Card style={statCard('#DC2626')}><span style={{ color: '#64748B', fontSize: 12 }}>❌ 失败</span><div style={{ fontSize: 28, fontWeight: 700, color: '#DC2626' }}>{summary.inactive ?? '-'}</div></Card></Col>
      <Col span={4}><Card style={statCard('#94A3B8')}><span style={{ color: '#64748B', fontSize: 12 }}>⏳ 待检</span><div style={{ fontSize: 28, fontWeight: 700, color: '#0F172A' }}>{summary.unchecked ?? '-'}</div></Card></Col>
      <Col span={4}><Card style={statCard(blockingIssues > 0 ? '#DC2626' : '#059669')}><span style={{ color: '#64748B', fontSize: 12 }}>🚫 阻塞</span><div style={{ fontSize: 28, fontWeight: 700, color: blockingIssues > 0 ? '#DC2626' : '#059669' }}>{blockingIssues}</div></Card></Col>
    </Row>

    {/* ─── Provider Health ─── */}
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}><DatabaseOutlined style={{ marginRight: 8 }} />数据提供者健康状态</span>}
      extra={<span style={{ color: '#94A3B8', fontSize: 12 }}>状态指示: 🟢健康 🟡降级 🔴失败 ⚪待检 • 点击行查看近期错误</span>}
      style={cardStyle}>
      <Table
        dataSource={providers?.sources || []}
        columns={providerCols}
        rowKey="source_id"
        size="small"
        pagination={{ pageSize: 10 }}
        expandable={{
          expandedRowRender: (record) => {
            const errors = record.health?.recent_errors || []
            return <div style={{ padding: '12px 0' }}>
              <Typography.Text strong style={{ fontSize: 12, color: '#64748B', display: 'block', marginBottom: 8 }}>近期错误记录 ({errors.length} 条)</Typography.Text>
              {errors.length === 0
                ? <span style={{ color: '#94A3B8', fontSize: 12 }}>无近期错误</span>
                : errors.map((err, i) => <div key={i} style={{ color: '#DC2626', fontSize: 12, fontFamily: 'monospace', padding: '4px 0', borderBottom: i < errors.length - 1 ? '1px solid #FEE2E2' : 'none' }}>⚠ {err}</div>)
              }
            </div>
          },
          rowExpandable: (record) => (record.health?.recent_errors || []).length > 0,
        }}
      />
    </Card>

    {/* ─── Data Freshness ─── */}
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}><FileTextOutlined style={{ marginRight: 8 }} />数据新鲜度</span>}
      extra={<Tag color={freshness?.overall_status === 'ok' ? 'success' : freshness?.overall_status === 'stale' ? 'warning' : 'error'}>{freshness?.overall_status || '未知'}</Tag>}
      style={cardStyle}>
      <Table
        dataSource={freshness?.files || []}
        columns={freshCols}
        rowKey="path"
        size="small"
        pagination={false}
      />
    </Card>

    {/* ─── Data Gaps ─── */}
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}><WarningOutlined style={{ marginRight: 8 }} />数据缺口</span>}
      extra={gapsArr.length > 0
        ? <span><Tag color="error">{gaps?.summary?.blocking_gaps || 0} 阻塞</Tag><Tag color="warning">{gaps?.summary?.partial_gaps || 0} 部分</Tag></span>
        : <Tag color="success">无缺口</Tag>}
      style={cardStyle}>
      {gapsArr.length === 0
        ? <div style={{ padding: 16, textAlign: 'center', color: '#94A3B8' }}>✅ 无数据缺口</div>
        : <Table dataSource={gapsArr} columns={gapCols} rowKey={(r, i) => `${r.category}-${i}`} size="small" pagination={false} />
      }
    </Card>

    {/* ─── Fetch Log ─── */}
    <Card title={<span style={{ color: '#0F172A', fontWeight: 600 }}><BugOutlined style={{ marginRight: 8 }} />拉取日志（最近 {logEntries.length} 条）</span>}
      style={cardStyle}>
      {logEntries.length === 0
        ? <div style={{ padding: 16, textAlign: 'center', color: '#94A3B8' }}>暂无拉取日志</div>
        : <Table dataSource={logEntries} columns={logCols} rowKey={(r, i) => `${r.timestamp}-${i}`} size="small" pagination={{ pageSize: 15 }} />
      }
    </Card>
  </div>
}
